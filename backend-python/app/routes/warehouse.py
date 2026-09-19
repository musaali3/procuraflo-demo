from ..receiving import receipt_progress, refresh_receipt_status
from ..supplier_documents import supplier_document_fields
from datetime import datetime
from math import isfinite
import json
from fastapi import APIRouter,Depends,HTTPException
from ..audit import log_audit
from ..calculations import base_unit_cost,convert_with_snapshot,inventory_value,money,uom_snapshot
from ..approval_engine import evaluate_authority
from ..calculations import decimal_value
from ..approval_routing import approval_authorized,employee_for_user,route_approver
from ..database import company_base_currency,fetch_all,fetch_one,transaction
from ..security import User,roles
from ..delegated_authority import active_delegation,record_delegated_use
from ..replenishment import create_pr_from_draft,create_replenishment_draft,draft_detail,complete_review,revalidate_draft
from ..stock import receive,consume,is_terminal_storage_location
from .inventory import approval_history
from .procurement import number
router=APIRouter(prefix='/api/warehouse',tags=['warehouse']);WH=['SupplyChainManager','WarehouseManager','WarehouseSupervisor','Storekeeper'];VIEW=WH
def refresh_supplier_rating(connection,supplier_id):
    totals=connection.execute('''SELECT COALESCE(SUM(gi.quantity_received),0) received,COALESCE(SUM(gi.accepted_qty),0) accepted
      FROM grn_items gi JOIN grns g ON g.id=gi.grn_id WHERE g.supplier_id=?''',(supplier_id,)).fetchone()
    delivery=connection.execute('''SELECT COUNT(*) deliveries,SUM(CASE WHEN po.committed_delivery_date IS NOT NULL AND date(g.grn_date)<=date(po.committed_delivery_date) THEN 1 ELSE 0 END) on_time
      FROM grns g JOIN purchase_orders po ON po.id=g.po_id WHERE g.supplier_id=? AND po.committed_delivery_date IS NOT NULL''',(supplier_id,)).fetchone()
    ordered=connection.execute('''SELECT COALESCE(SUM(pi.quantity),0) quantity FROM po_items pi JOIN purchase_orders po ON po.id=pi.po_id
      WHERE po.supplier_id=? AND EXISTS(SELECT 1 FROM grns g WHERE g.po_id=po.id)''',(supplier_id,)).fetchone()['quantity']
    received=float(totals['received']or 0);accepted=float(totals['accepted']or 0)
    if not received:rating=0
    else:
        quality=min(1,accepted/received);quantity=min(1,accepted/float(ordered or accepted or 1));timeliness=float(delivery['on_time']or 0)/float(delivery['deliveries']or 1)
        rating=round(5*(quality*.45+quantity*.25+timeliness*.30),2)
    connection.execute('UPDATE suppliers SET rating=? WHERE id=?',(rating,supplier_id));return rating
def scope(user,wid,authority=None):
    delegation=None if wid in user['warehouse_ids'] else active_delegation(user,authority,warehouse_id=wid)if authority else None
    if wid not in user['warehouse_ids']and not delegation:raise HTTPException(403,'This employee is not assigned to the selected warehouse and has no matching delegated authority')
    if not fetch_one('SELECT id FROM warehouses WHERE id=? AND deleted_at IS NULL',(wid,)):raise HTTPException(409,'The selected warehouse is inactive; its operational workflow is disabled')
    return delegation

def replenishment_scope(user,wid):
    if user['role'] not in WH:raise HTTPException(403,'Warehouse access is required')
    if user['role']=='SupplyChainManager':return
    if wid not in user.get('warehouse_ids',[]):raise HTTPException(403,'Warehouse is outside your authorized scope')

@router.get('/replenishment/drafts')
def replenishment_drafts(user:User):
    if user['role'] not in WH:raise HTTPException(403,'Warehouse access is required')
    ids=user['warehouse_ids'] if user['role']!='SupplyChainManager' else [row['id'] for row in fetch_all('SELECT id FROM warehouses WHERE deleted_at IS NULL')]
    rows=fetch_all(f"""SELECT d.*,w.name warehouse_name,w.warehouse_code,u.full_name checked_by_name,pr.pr_number,pr.status pr_status,
      (SELECT COUNT(*) FROM replenishment_draft_lines l WHERE l.draft_id=d.id) item_count,
      (SELECT COUNT(*) FROM replenishment_draft_lines l WHERE l.draft_id=d.id AND l.system_recommended_qty>0) replenishment_required_count,
      (SELECT COUNT(*) FROM replenishment_draft_lines l WHERE l.draft_id=d.id AND l.reviewed_qty=0) zero_reviewed_count
      FROM replenishment_drafts d JOIN warehouses w ON w.id=d.warehouse_id LEFT JOIN users u ON u.id=d.checked_by
      LEFT JOIN purchase_requisitions pr ON pr.id=d.resulting_pr_id WHERE d.warehouse_id IN({','.join('?' for _ in ids) or 'NULL'}) ORDER BY d.id DESC""",ids)
    return rows

@router.post('/replenishment/check',status_code=201)
def run_replenishment_check(body:dict,user:User):
    result=create_replenishment_draft(body.get('warehouse_id'),user)
    if not result.get('created'):
        from fastapi.responses import JSONResponse
        return JSONResponse(result,status_code=200)
    return result

@router.get('/replenishment/drafts/{draft_id}')
def get_replenishment_draft(draft_id:int,user:User):
    with transaction() as c:
        draft=draft_detail(c,draft_id)
    if not draft:raise HTTPException(404,'Replenishment draft not found')
    replenishment_scope(user,draft['warehouse_id'])
    return draft

@router.put('/replenishment/drafts/{draft_id}/review')
def review_replenishment_draft(draft_id:int,body:dict,user:User):
    return complete_review(draft_id,body.get('lines'),user)

@router.post('/replenishment/drafts/{draft_id}/revalidate')
def revalidate_replenishment_draft(draft_id:int,user:User):
    with transaction(immediate=True) as c:
        draft=draft_detail(c,draft_id)
        if not draft:raise HTTPException(404,'Replenishment draft not found')
        replenishment_scope(user,draft['warehouse_id'])
        changes=revalidate_draft(c,draft)
    return {'changed':bool(changes),'changes':changes}

@router.post('/replenishment/drafts/{draft_id}/create-pr',status_code=201)
def create_replenishment_pr(draft_id:int,user:User):
    try:
        return create_pr_from_draft(draft_id,user)
    except HTTPException as exc:
        if exc.status_code==409 and isinstance(exc.detail,dict):
            from fastapi.responses import JSONResponse
            return JSONResponse({'error':exc.detail},status_code=409)
        raise

@router.put('/replenishment/drafts/{draft_id}/cancel')
def cancel_replenishment_draft(draft_id:int,body:dict,user:User):
    reason=str(body.get('reason')or'Cancelled by warehouse').strip()
    with transaction(immediate=True) as c:
        draft=draft_detail(c,draft_id)
        if not draft:raise HTTPException(404,'Replenishment draft not found')
        replenishment_scope(user,draft['warehouse_id'])
        if draft['status']=='Converted to PR':raise HTTPException(409,'Converted drafts cannot be cancelled')
        c.execute("UPDATE replenishment_drafts SET status='Cancelled',cancelled_at=datetime('now'),cancel_reason=? WHERE id=?",(reason,draft_id))
        log_audit(c,'replenishment_drafts',draft_id,'REJECT',user['id'],before={'status':draft['status']},after={'status':'Cancelled','reason':reason})
    return {'success':True,'status':'Cancelled'}
def locations(wid,lid):
    row=fetch_one("SELECT * FROM locations WHERE id=? AND warehouse_id=? AND COALESCE(active_yn,1)=1 AND status NOT IN('Inactive','Blocked','Maintenance','Full') AND deleted_at IS NULL",(lid,wid))
    if not row or not is_terminal_storage_location(row):raise HTTPException(400,'Select a valid active terminal storage location in the warehouse')
def receiving_location(wid,lid):
    if lid in(None,''):return None
    row=fetch_one("SELECT * FROM locations WHERE id=? AND warehouse_id=? AND COALESCE(active_yn,1)=1 AND deleted_at IS NULL",(lid,wid))
    if not row or(str(row.get('structure_type')or'').upper()not in('STAGING','QUARANTINE_AREA')and str(row.get('storage_classification')or'').upper()not in('RECEIVING','QUARANTINE')):raise HTTPException(400,'GRN may reference only an active Receiving, Staging, Inspection, or Quarantine staging location; final storage is selected during Put-Away')
    return row
@router.get('/grns')
def grns(user:dict=Depends(roles(*VIEW))):
    ids=user['warehouse_ids'];rows=fetch_all(f"SELECT g.*,'Posted' status,s.name supplier_name,po.po_number,COALESCE((SELECT SUM(gi.accepted_qty*gi.unit_cost) FROM grn_items gi WHERE gi.grn_id=g.id),0) calculated_accepted_value,COALESCE(be.name,u.full_name) received_by_name,be.employee_code received_for_employee_code FROM grns g JOIN suppliers s ON s.id=g.supplier_id JOIN purchase_orders po ON po.id=g.po_id LEFT JOIN users u ON u.id=g.created_by LEFT JOIN employees be ON be.id=g.received_for_employee_id WHERE EXISTS(SELECT 1 FROM grn_items gi WHERE gi.grn_id=g.id AND gi.warehouse_id IN({','.join('?'for _ in ids)or'NULL'})) ORDER BY g.id DESC",ids)
    for row in rows:row['accepted_value']=float(money(row.pop('calculated_accepted_value')))
    return rows
@router.get('/grns/{grn_id}')
def grn(grn_id:int,user:dict=Depends(roles(*VIEW))):
    row=fetch_one("SELECT g.*,'Posted' status,s.name supplier_name,po.po_number,po.committed_delivery_date,po.total_amount po_total_amount,COALESCE(be.name,u.full_name) received_by_name,be.employee_code received_for_employee_code,COALESCE(be.signature_url,e.signature_url) received_by_signature_url FROM grns g JOIN suppliers s ON s.id=g.supplier_id JOIN purchase_orders po ON po.id=g.po_id LEFT JOIN users u ON u.id=g.created_by LEFT JOIN employees e ON e.id=u.employee_id LEFT JOIN employees be ON be.id=g.received_for_employee_id WHERE g.id=?",(grn_id,));
    if not row:raise HTTPException(404,'GRN not found')
    row['items']=fetch_all('SELECT gi.*,i.item_code,i.description,i.uom,i.purchase_uom,w.name warehouse_name,l.code location_code FROM grn_items gi JOIN items i ON i.id=gi.item_id JOIN warehouses w ON w.id=gi.warehouse_id LEFT JOIN locations l ON l.id=gi.location_id WHERE gi.grn_id=?',(grn_id,));
    if not row['items']:raise HTTPException(404,'GRN lines not found')
    row['accepted_value']=float(money(sum(decimal_value(line['accepted_qty'])*decimal_value(line['unit_cost']) for line in row['items'])))
    scope(user,row['items'][0]['warehouse_id']);row['inspections']=fetch_all('SELECT * FROM goods_inspections WHERE grn_id=? ORDER BY inspected_at,id',(grn_id,));row.update(supplier_document_fields(row.get('supplier_id')));row['company']=fetch_one('SELECT * FROM company WHERE deleted_at IS NULL ORDER BY id LIMIT 1')or{};return row
@router.post('/grns',status_code=201)
def create_grn(body:dict,user:dict=Depends(roles(*WH))):
    items=body.get('items');employee_id=body.get('received_for_employee_id');wid=body.get('warehouse_id')or(user['warehouse_ids'][0]if len(user['warehouse_ids'])==1 else None);delegation=scope(user,wid,'WH_GRN_RECEIVE');employee=fetch_one("""SELECT e.id FROM employees e JOIN departments d ON d.id=e.department_id WHERE e.id=? AND e.status='Active' AND e.deleted_at IS NULL AND lower(d.name) LIKE '%warehouse%' AND(e.warehouse_id=? OR EXISTS(SELECT 1 FROM employee_warehouse_assignments a WHERE a.employee_id=e.id AND a.active_yn=1 AND(a.all_warehouses_yn=1 OR a.warehouse_id=?)))""",(employee_id,wid,wid))
    if not employee:raise HTTPException(400,'Select a valid active employee responsible for this receipt')
    if not isinstance(items,list)or not items:raise HTTPException(400,'At least one item required')
    request_key=str(body.get('request_key') or '').strip()
    if not request_key or len(request_key)>100:raise HTTPException(400,'A receipt request key is required; refresh the GRN form before posting')
    request_payload=json.dumps({k:v for k,v in body.items() if k!='request_key'},sort_keys=True,separators=(',',':'))
    def prior_receipt(c):
        previous=c.execute('SELECT * FROM grns WHERE request_key=?',(request_key,)).fetchone()
        if previous:
            if previous['request_payload']!=request_payload:raise HTTPException(409,'This receipt request was already used for different quantities; open a new GRN')
            return {'id':previous['id'],'grn_number':previous['grn_number'],'accepted_value':previous['accepted_value']}
    with transaction(immediate=True) as c:
        previous=prior_receipt(c)
        if previous:return previous
    po=fetch_one('SELECT * FROM purchase_orders WHERE id=?',(body.get('po_id'),));
    if not po:raise HTTPException(404,'PO not found')
    if po['status']=='Closed' and receipt_progress(po['id'])['receiving_status']=='Partially Received':po['status']='Partially Received'
    if po['status']not in['Approved','Printed','Partially Received']:raise HTTPException(400,'GRN can only be created against an approved PO')
    intended=po.get('delivery_warehouse_id')or(fetch_one('SELECT delivery_warehouse_id FROM rfqs WHERE id=?',(po.get('rfq_id'),))or{}).get('delivery_warehouse_id')
    if intended is None:raise HTTPException(409,'This Purchase Order has no delivery warehouse; assign one before creating a GRN')
    if int(intended)!=int(wid):raise HTTPException(403,'This Purchase Order is assigned to a different delivery warehouse')
    poitems={x['item_id']:x for x in fetch_all('SELECT * FROM po_items WHERE po_id=?',(po['id'],))}
    with transaction(immediate=True)as c:
        previous=prior_receipt(c)
        if previous:return previous
        num=number(c,'GRN');cur=c.execute('INSERT INTO grns(grn_number,po_id,supplier_id,delivery_note,created_by,received_for_employee_id)VALUES(?,?,?,?,?,?)',(num,po['id'],po['supplier_id'],body.get('delivery_note'),user['id'],employee_id));accepted_total=0
        c.execute('UPDATE grns SET request_key=?,request_payload=? WHERE id=?',(request_key,request_payload,cur.lastrowid))
        for x in items:
            if x.get('item_id')not in poitems:raise HTTPException(400,f"Item {x.get('item_id')} is not on this PO")
            accepted=float(x.get('accepted_qty',x.get('quantity_received',0)));rejected=float(x.get('rejected_qty',0));received_qty=float(x.get('quantity_received',0))
            if received_qty<0 or accepted<0 or rejected<0:raise HTTPException(400,'Received, accepted, and rejected quantities cannot be negative')
            if abs(accepted+rejected-received_qty)>.0001:raise HTTPException(400,'Accepted plus rejected must equal received')
            outstanding=next(line['receivable_quantity'] for line in receipt_progress(po['id'],c)['receipt_lines'] if line['item_id']==x['item_id'])
            if accepted>outstanding+.0001:raise HTTPException(409,f"Accepted quantity exceeds the PO outstanding quantity of {outstanding:g}")
            damaged=float(x.get('damaged_qty') or 0);short=float(x.get('short_qty') or 0)
            if not all(isfinite(v) for v in (received_qty,accepted,rejected,damaged,short)) or damaged<0 or damaged>rejected or short<0:raise HTTPException(400,'Damaged quantity must be part of rejected quantity; all quantities must be finite and nonnegative')
            if (damaged or short) and not str(x.get('receiving_issue_reason') or x.get('rejection_reason') or '').strip():raise HTTPException(400,'Enter the receiving issue reason for damaged or short quantities')
            if accepted:receiving_location(wid,x.get('location_id'))
            poitem=poitems[x['item_id']];master=dict(c.execute('SELECT * FROM items WHERE id=?',(x['item_id'],)).fetchone())
            if accepted and master.get('batch_control_yn') and not str(x.get('batch')or'').strip():raise HTTPException(400,f"Batch is required for {master['item_code']}")
            if accepted and master.get('expiry_control_yn') and not str(x.get('expiry_date')or'').strip():raise HTTPException(400,f"Expiry date is required for {master['item_code']}")
            factor=poitem.get('conversion_factor_used')or(1 if str(master.get('purchase_uom')or master['uom']).upper()==str(master['uom']).upper()else master.get('conversion_factor')or 1);transaction_uom=poitem.get('transaction_uom')or master.get('purchase_uom')or master['uom'];base_uom=poitem.get('base_uom')or master['uom'];received_snapshot=convert_with_snapshot(received_qty,transaction_uom,factor,base_uom);accepted_snapshot=convert_with_snapshot(accepted,transaction_uom,factor,base_uom)if accepted else {**received_snapshot,'base_quantity':money(0)};rejected_snapshot=convert_with_snapshot(rejected,transaction_uom,factor,base_uom)if rejected else {**received_snapshot,'base_quantity':money(0)};price=float(poitem['price']);inventory_cost=float(base_unit_cost(price,factor));accepted_value=float(inventory_value(accepted_snapshot['base_quantity'],inventory_cost));gi=c.execute('''INSERT INTO grn_items(grn_id,item_id,quantity_received,accepted_qty,rejected_qty,rejection_reason,unit_cost,batch,expiry_date,warehouse_id,location_id,transaction_uom,conversion_factor_used,received_base_quantity,accepted_base_quantity,rejected_base_quantity,base_uom,inventory_unit_cost,inventory_value)VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(cur.lastrowid,x['item_id'],received_qty,accepted,rejected,x.get('rejection_reason'),price,x.get('batch'),x.get('expiry_date'),wid,x.get('location_id'),transaction_uom,float(factor),float(received_snapshot['base_quantity']),float(accepted_snapshot['base_quantity']),float(rejected_snapshot['base_quantity']),base_uom,inventory_cost,accepted_value))
            c.execute('UPDATE grn_items SET damaged_qty=?,short_qty=?,receiving_issue_reason=?,receiving_notes=? WHERE id=?',(damaged,short,x.get('receiving_issue_reason'),x.get('receiving_notes'),gi.lastrowid))
            if master.get('consumable_returnable')=='Returnable':
                units=float(accepted_snapshot['base_quantity'])
                if not units.is_integer():raise HTTPException(400,'Returnable tools must be received as whole base units')
                for unit in range(1,int(units)+1):
                    code=f'TOOL-GRN-{gi.lastrowid:07d}-{unit:05d}'
                    created=c.execute("""INSERT INTO tools(tool_code,item_id,warehouse_id,condition,status,source_grn_item_id,source_unit_number)
                        VALUES(?,?,?,'Good','Pending Tool Registration',?,?) ON CONFLICT(source_grn_item_id,source_unit_number) WHERE source_grn_item_id IS NOT NULL DO NOTHING""",(code,x['item_id'],wid,gi.lastrowid,unit))
                    if created.rowcount:log_audit(c,'tools',created.lastrowid,'CREATE',user['id'],after={'event':'GRN_PENDING_REGISTRATION','tool_code':code,'grn_id':cur.lastrowid,'source_grn_item_id':gi.lastrowid,'source_unit_number':unit,'warehouse_id':wid})
            if rejected:
                c.execute("INSERT INTO inventory_quarantine(item_id,warehouse_id,location_id,quantity,unit_cost,inventory_status,source_table,source_id,created_by,batch,expiry_date,source_grn_item_id,transaction_uom,base_uom,audit_reference)VALUES(?,?,?,?,?,'REJECTED','grn_items',?,?,?,?,?,?,?,?)",(x['item_id'],wid,x.get('location_id'),float(rejected_snapshot['base_quantity']),inventory_cost,gi.lastrowid,user['id'],x.get('batch'),x.get('expiry_date'),gi.lastrowid,transaction_uom,base_uom,f'{num}-REJECTED-{gi.lastrowid}'))
            if accepted:
                pending_status='INSPECTION_PENDING'if master.get('inspection_required_yn')else'PUT_AWAY_PENDING';audit_reference=f'{num}-LINE-{gi.lastrowid}'
                c.execute('''INSERT INTO inventory_quarantine(item_id,warehouse_id,location_id,quantity,unit_cost,inventory_status,source_table,source_id,created_by,batch,expiry_date,source_grn_item_id,transaction_uom,base_uom,audit_reference)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(x['item_id'],wid,x.get('location_id'),float(accepted_snapshot['base_quantity']),inventory_cost,pending_status,'grn_items',gi.lastrowid,user['id'],x.get('batch'),x.get('expiry_date'),gi.lastrowid,transaction_uom,base_uom,audit_reference))
                c.execute('UPDATE items SET last_purchase_price=? WHERE id=?',(price,x['item_id']));log_audit(c,'grn_items',gi.lastrowid,'UPDATE',user['id'],after={'event':'INSPECTION_PENDING'if master.get('inspection_required_yn')else'RELEASED_FOR_PUT_AWAY','quantity':float(accepted_snapshot['base_quantity']),'audit_reference':audit_reference});accepted_total+=accepted_value
        supplier_rating=refresh_supplier_rating(c,po['supplier_id']);delegated=record_delegated_use(c,delegation,user,'grns',cur.lastrowid,'CREATE',{'warehouse_id':wid})if delegation else{};log_audit(c,'grns',cur.lastrowid,'CREATE',user['id'],after={**body,'supplier_performance_rating':supplier_rating,**delegated});gid=cur.lastrowid
        c.execute('UPDATE grns SET accepted_value=? WHERE id=?',(float(money(accepted_total)),gid))
        refresh_receipt_status(c,po['id'])
    return {'id':gid,'grn_number':num,'accepted_value':float(money(accepted_total))}

@router.get('/receiving-queue')
def receiving_queue(user:dict=Depends(roles(*WH))):
    ids=user['warehouse_ids'];marks=','.join('?'for _ in ids)or'NULL'
    return fetch_all(f'''SELECT q.*,i.item_code,i.description,COALESCE(q.base_uom,i.uom)uom,g.grn_number,gi.grn_id,l.code current_location_code,
      COALESCE((SELECT SUM(x.inspected_quantity)FROM goods_inspections x WHERE x.hold_id=q.id),0)inspected_quantity
      FROM inventory_quarantine q JOIN items i ON i.id=q.item_id LEFT JOIN grn_items gi ON gi.id=q.source_grn_item_id
      LEFT JOIN grns g ON g.id=gi.grn_id LEFT JOIN locations l ON l.id=q.location_id
      WHERE q.released_at IS NULL AND q.inventory_status IN('INSPECTION_PENDING','PUT_AWAY_PENDING') AND q.warehouse_id IN({marks}) ORDER BY q.created_at,q.id''',ids)

@router.post('/inspections',status_code=201)
def inspect_goods(body:dict,user:dict=Depends(roles('SupplyChainManager','WarehouseManager','WarehouseSupervisor'))):
    hold=fetch_one("SELECT * FROM inventory_quarantine WHERE id=? AND inventory_status='INSPECTION_PENDING' AND released_at IS NULL",(body.get('hold_id'),))
    if not hold:raise HTTPException(404,'Open inspection-controlled receipt not found')
    scope(user,hold['warehouse_id'])
    try:inspected=float(body.get('inspected_quantity'));passed=float(body.get('passed_quantity'));failed=float(body.get('failed_quantity'))
    except(TypeError,ValueError):raise HTTPException(400,'Inspection quantities must be numeric')
    if not all(isfinite(v) for v in (inspected,passed,failed)) or inspected<=0 or passed<0 or failed<0 or abs(passed+failed-inspected)>.0001:raise HTTPException(400,'Passed plus failed must equal the positive inspected quantity')
    already=float((fetch_one('SELECT COALESCE(SUM(inspected_quantity),0) quantity FROM goods_inspections WHERE hold_id=?',(hold['id'],))or{}).get('quantity')or 0)
    if already+inspected>float(hold['quantity'])+.0001:raise HTTPException(409,'Inspection decisions exceed the accepted GRN quantity')
    decision='PASSED'if failed==0 else('FAILED'if passed==0 else'PARTIALLY_PASSED')
    with transaction(immediate=True)as c:
        current=c.execute('SELECT released_at FROM inventory_quarantine WHERE id=?',(hold['id'],)).fetchone()
        current_inspected=float(c.execute('SELECT COALESCE(SUM(inspected_quantity),0) FROM goods_inspections WHERE hold_id=?',(hold['id'],)).fetchone()[0])
        if current['released_at'] or abs(current_inspected-already)>.0001:raise HTTPException(409,'This receipt was inspected by another user. Refresh before recording another decision')
        sequence=c.execute('SELECT COUNT(*) FROM goods_inspections WHERE hold_id=?',(hold['id'],)).fetchone()[0]+1
        audit_reference=f"INSP-{hold['id']}-{sequence:03d}"
        grn_item=c.execute('SELECT grn_id FROM grn_items WHERE id=?',(hold.get('source_grn_item_id'),)).fetchone();grn_id=grn_item['grn_id']if grn_item else None
        controlled=c.execute('SELECT 1 FROM tools WHERE source_grn_item_id=?',(hold.get('source_grn_item_id'),)).fetchone()
        if hold.get('tool_id'):
            if inspected!=1 or passed not in (0,1) or failed not in (0,1):raise HTTPException(400,'Inspect the transferred tool as one whole unit')
            c.execute('UPDATE tools SET status=?,condition=? WHERE id=?',('Quarantined' if failed else 'Available','Damaged' if failed else 'Good',hold['tool_id']))
            log_audit(c,'tools',hold['tool_id'],'UPDATE',user['id'],after={'event':'TRANSFER_INSPECTION','passed':passed,'failed':failed,'hold_id':hold['id']})
        if controlled:
            if not all(v.is_integer() for v in (inspected,passed,failed,already)):raise HTTPException(400,'Controlled tool inspections require whole units')
            failed_tools=c.execute('SELECT * FROM tools WHERE source_grn_item_id=? AND source_unit_number>? AND source_unit_number<=?',(hold['source_grn_item_id'],int(already+passed),int(already+inspected))).fetchall()
            for failed_tool in failed_tools:
                status='Pending Tool Registration' if not failed_tool['registered_at'] else 'Quarantined'
                c.execute("UPDATE tools SET condition='Damaged',status=? WHERE id=?",(status,failed_tool['id']))
                log_audit(c,'tools',failed_tool['id'],'UPDATE',user['id'],dict(failed_tool),{'event':'GRN_INSPECTION_FAILED','status':status,'hold_id':hold['id']})
        cur=c.execute('''INSERT INTO goods_inspections(inspection_number,grn_id,grn_item_id,hold_id,source_table,source_id,item_id,warehouse_id,inspected_quantity,passed_quantity,failed_quantity,decision,remarks,inspected_by,audit_reference)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(audit_reference,grn_id,hold.get('source_grn_item_id'),hold['id'],hold['source_table'],hold['source_id'],hold['item_id'],hold['warehouse_id'],inspected,passed,failed,decision,body.get('remarks'),user['id'],audit_reference))
        damaged=float(body.get('damaged_quantity') or 0)
        if not isfinite(damaged) or damaged<0 or damaged>failed:raise HTTPException(400,'Damaged quantity must be between zero and failed quantity')
        c.execute('UPDATE goods_inspections SET damaged_quantity=?,issue_reason=? WHERE id=?',(damaged,body.get('issue_reason'),cur.lastrowid))
        employee=employee_for_user(user) or {}
        employee['department_name']=(c.execute('SELECT name FROM departments WHERE id=?',(employee.get('department_id'),)).fetchone() or {'name':''})['name']
        inspector={key:str(body.get(key) or fallback or '').strip() for key,fallback in [('inspector_name',employee.get('name') or user.get('full_name')),('inspector_department',employee.get('department_name')),('inspector_designation',employee.get('position'))]}
        c.execute('UPDATE goods_inspections SET inspector_name=?,inspector_department=?,inspector_designation=? WHERE id=?',(*inspector.values(),cur.lastrowid))
        common=(hold['item_id'],hold['warehouse_id'],hold['location_id'],hold['unit_cost'],'grn_inspections',cur.lastrowid,user['id'],hold.get('batch'),hold.get('expiry_date'),hold.get('source_grn_item_id'),hold.get('transaction_uom'),hold.get('base_uom'),audit_reference)
        if passed:c.execute('''INSERT INTO inventory_quarantine(item_id,warehouse_id,location_id,quantity,unit_cost,inventory_status,source_table,source_id,created_by,batch,expiry_date,source_grn_item_id,transaction_uom,base_uom,audit_reference)VALUES(?,?,?,?,?,'PUT_AWAY_PENDING',?,?,?,?,?,?,?,?,?)''',(common[0],common[1],common[2],passed,*common[3:]))
        if failed:c.execute('''INSERT INTO inventory_quarantine(item_id,warehouse_id,location_id,quantity,unit_cost,inventory_status,source_table,source_id,created_by,batch,expiry_date,source_grn_item_id,transaction_uom,base_uom,audit_reference)VALUES(?,?,?,?,?,'REJECTED',?,?,?,?,?,?,?,?,?)''',(common[0],common[1],common[2],failed,*common[3:]))
        if hold.get('tool_id'):c.execute("UPDATE inventory_quarantine SET tool_id=? WHERE source_table='grn_inspections' AND source_id=?",(hold['tool_id'],cur.lastrowid))
        completed=already+inspected>=float(hold['quantity'])-.0001
        if completed:c.execute("UPDATE inventory_quarantine SET released_at=datetime('now'),released_by=? WHERE id=?",(user['id'],hold['id']))
        log_audit(c,'goods_inspections',cur.lastrowid,'CREATE',user['id'],after={**inspector,'event':'INSPECTION_PASSED'if decision=='PASSED'else('INSPECTION_FAILED'if decision=='FAILED'else'INSPECTION_PARTIALLY_PASSED'),'passed_quantity':passed,'failed_quantity':failed,'remaining_quantity':max(0,float(hold['quantity'])-already-inspected),'audit_reference':audit_reference})
        if grn_id:
            refresh_receipt_status(c,c.execute('SELECT po_id FROM grns WHERE id=?',(grn_id,)).fetchone()['po_id'])
    return {'id':cur.lastrowid,'decision':decision,'passed_quantity':passed,'failed_quantity':failed,'remaining_quantity':max(0,float(hold['quantity'])-already-inspected)}
@router.get('/returns')
def returns(user:dict=Depends(roles(*WH))):
    ids=user['warehouse_ids'];return fetch_all(f"SELECT r.*,i.item_code,i.description,e.name employee_name,w.name warehouse_name,l.code location_code FROM returns r JOIN items i ON i.id=r.item_id LEFT JOIN employees e ON e.id=r.employee_id LEFT JOIN warehouses w ON w.id=r.warehouse_id LEFT JOIN locations l ON l.id=r.location_id WHERE r.warehouse_id IN({','.join('?'for _ in ids)or'NULL'}) ORDER BY r.id DESC",ids)
@router.get('/returns/outstanding')
def outstanding_returns(employee_id:int|None=None,item_id:int|None=None,user:dict=Depends(roles(*WH))):
    filters=[];params=[]
    if employee_id is not None:filters.append('mi.employee_id=?');params.append(employee_id)
    if item_id is not None:filters.append('mii.item_id=?');params.append(item_id)
    ids=[int(value)for value in user.get('warehouse_ids',[])]
    filters.append(f"mii.warehouse_id IN({','.join('?'for _ in ids)or'NULL'})");params.extend(ids)
    where=(' AND '+' AND '.join(filters))if filters else''
    return fetch_all(f'''SELECT e.id employee_id,e.employee_code,e.name employee_name,d.name department_name,
      i.id item_id,i.item_code,i.description,i.uom,SUM(mii.quantity) issued_quantity,
      COALESCE((SELECT SUM(r.quantity)FROM returns r WHERE r.employee_id=e.id AND r.item_id=i.id AND r.warehouse_id=mii.warehouse_id),0)returned_quantity,
      SUM(mii.quantity)-COALESCE((SELECT SUM(r.quantity)FROM returns r WHERE r.employee_id=e.id AND r.item_id=i.id AND r.warehouse_id=mii.warehouse_id),0)outstanding_quantity,
      w.name source_warehouses,mii.warehouse_id
      FROM material_issue_items mii JOIN material_issues mi ON mi.id=mii.issue_id
      JOIN employees e ON e.id=mi.employee_id LEFT JOIN departments d ON d.id=e.department_id
      JOIN items i ON i.id=mii.item_id JOIN warehouses w ON w.id=mii.warehouse_id
      WHERE mi.status='Posted' AND i.consumable_returnable='Returnable'{where}
      GROUP BY e.id,i.id,mii.warehouse_id HAVING outstanding_quantity>.000001 ORDER BY e.name,i.item_code''',params)
def issue_fifo_value(lines, breakdown=False):
    reserved={};total=0;values=[]
    for line in lines:
        before=total;left=float(line.get('base_quantity') or line['quantity'])
        layers=fetch_all('SELECT id,quantity_remaining,unit_cost FROM inventory_layers WHERE item_id=? AND warehouse_id=? AND location_id IS ? AND quantity_remaining>0 ORDER BY received_date,id',(line['item_id'],line['warehouse_id'],line.get('location_id')))
        for layer in layers:
            take=min(left,max(0,layer['quantity_remaining']-reserved.get(layer['id'],0)))
            total+=take*layer['unit_cost'];left-=take;reserved[layer['id']]=reserved.get(layer['id'],0)+take
            if left<=1e-8:break
        if left>1e-8:raise HTTPException(409,'Insufficient available stock for Material Issue valuation')
        values.append(float(money(total-before)))
    return values if breakdown else float(money(total))

@router.post('/material-issue-preview')
def preview_issue(body:dict,user:dict=Depends(roles(*WH))):
    from ..approval_routing import employee_limit
    lines=body.get('items')
    if not isinstance(lines,list) or not lines:raise HTTPException(400,'Select at least one issue item')
    valued=[]
    for line in lines:
        wid=line.get('warehouse_id');scope(user,wid,'WH_MATERIAL_ISSUE');locations(wid,line.get('location_id'))
        master=fetch_one('SELECT * FROM items WHERE id=? AND deleted_at IS NULL',(line.get('item_id'),))
        if not master:raise HTTPException(400,'Select a valid item')
        snapshot=uom_snapshot(master,line.get('quantity'),line.get('transaction_uom'),purpose='issue')
        valued.append({**line,'base_quantity':float(snapshot['base_quantity'])})
    if len({line['warehouse_id'] for line in valued})!=1:raise HTTPException(400,'A Material Issue must contain items from one authorized warehouse')
    value=issue_fifo_value(valued);requester=employee_for_user(user)
    if not requester:raise HTTPException(403,'An active Warehouse employee record is required')
    wid=valued[0]['warehouse_id'];limit=employee_limit(requester,'ISSUE',wid)
    approver,_,_,_=route_approver(requester['id'],value,'ISSUE',wid)
    return {'estimated_value':value,'approval_limit':limit,'exceeds_limit':user['role']!='SupplyChainManager' and value>limit,'approval_required':True,'approver_name':approver['name'],'approver_role':approver['user_role']}

@router.get('/material-issues')
def issues(user:dict=Depends(roles(*WH))):
    ids=user['warehouse_ids'];rows=fetch_all(f"SELECT mi.*,e.name employee_name,e.employee_code,d.name employee_department_name FROM material_issues mi JOIN employees e ON e.id=mi.employee_id LEFT JOIN departments d ON d.id=e.department_id WHERE EXISTS(SELECT 1 FROM material_issue_items mii WHERE mii.issue_id=mi.id AND mii.warehouse_id IN({','.join('?'for _ in ids)or'NULL'})) ORDER BY mi.id DESC",ids)
    for row in rows:
        row['can_edit']=may_edit_issue(row,user)
        row['can_approve']=False
        if row['status']=='PendingApproval':
            lines=fetch_all('SELECT * FROM material_issue_items WHERE issue_id=?',(row['id'],))
            pending=fetch_one("SELECT * FROM approval_log WHERE document_type='ISSUE' AND document_id=? AND decision='Pending' ORDER BY sequence,id LIMIT 1",(row['id'],))
            try:
                value=issue_fifo_value(lines);row['total_value']=value
                if pending:
                    approval_authorized(user,row['created_by'],value,'ISSUE',lines[0]['warehouse_id'],pending)
                    row['can_approve']=True
            except HTTPException:pass
    return rows
@router.get('/material-issues/{issue_id}')
def issue(issue_id:int,user:dict=Depends(roles(*WH))):
    row=fetch_one('SELECT mi.*,e.name employee_name,e.employee_code,d.name employee_department_name FROM material_issues mi JOIN employees e ON e.id=mi.employee_id LEFT JOIN departments d ON d.id=e.department_id WHERE mi.id=?',(issue_id,));
    if not row:raise HTTPException(404,'Material issue not found')
    row['items']=fetch_all('SELECT mii.*,i.item_code,i.description,i.uom,w.name warehouse_name,w.site_name,l.code location_code FROM material_issue_items mii JOIN items i ON i.id=mii.item_id JOIN warehouses w ON w.id=mii.warehouse_id LEFT JOIN locations l ON l.id=mii.location_id WHERE mii.issue_id=?',(issue_id,));
    if not row['items']:raise HTTPException(404,'Material issue lines not found')
    scope(user,row['items'][0]['warehouse_id'])
    row['can_edit']=may_edit_issue(row,user)
    row['company']=fetch_one('SELECT * FROM company WHERE deleted_at IS NULL ORDER BY id LIMIT 1') or {}
    row['prepared_by_name']=(fetch_one('SELECT full_name FROM users WHERE id=?',(row['created_by'],)) or {}).get('full_name')
    row['approved_by_name']=(fetch_one('SELECT full_name FROM users WHERE id=?',(row.get('approved_by'),)) or {}).get('full_name')
    for prefix,user_id in [('prepared_by',row['created_by']),('approved_by',row.get('approved_by'))]:
        row[prefix+'_signature_url']=(fetch_one('SELECT e.signature_url FROM users u JOIN employees e ON e.id=u.employee_id WHERE u.id=?',(user_id,)) or {}).get('signature_url')
    row['received_by_signature_url']=(fetch_one('SELECT signature_url FROM employees WHERE id=?',(row['employee_id'],)) or {}).get('signature_url')
    row['approved_at']=(fetch_one("SELECT decision_date FROM approval_log WHERE document_type='ISSUE' AND document_id=? AND decision='Approved' ORDER BY id DESC LIMIT 1",(issue_id,)) or {}).get('decision_date')

    if row['status']=='PendingApproval':
        values=issue_fifo_value(row['items'],breakdown=True)
        for line,value in zip(row['items'],values):line['value']=value
        row['total_value']=float(money(sum(values)))
    return row
def may_edit_issue(row,user):
    if row['status']!='PendingApproval':return False
    pending=fetch_one("SELECT approver_employee_id FROM approval_log WHERE document_type='ISSUE' AND document_id=? AND decision='Pending' ORDER BY sequence,id LIMIT 1",(row['id'],))
    employee=employee_for_user(user) or {}
    return row['created_by']==user['id'] or user['role']=='SupplyChainManager' or bool(pending and pending['approver_employee_id']==employee.get('id'))

@router.put('/material-issues/{issue_id}')
def edit_issue(issue_id:int,body:dict,user:dict=Depends(roles(*WH))):
    with transaction(immediate=True) as c:
        row=fetch_one('SELECT * FROM material_issues WHERE id=?',(issue_id,))
        if not row:raise HTTPException(404,'Material Issue not found')
        if row['status']!='PendingApproval':raise HTTPException(409,'Only Material Issues awaiting approval can be edited')
        old_lines=fetch_all('SELECT * FROM material_issue_items WHERE issue_id=?',(issue_id,))
        for line in old_lines:scope(user,line['warehouse_id'])
        if not may_edit_issue(row,user):raise HTTPException(403,'Only the creator or assigned approver may edit this pending Material Issue')
        preview_issue(body,user)
        recipient=fetch_one("SELECT id FROM employees WHERE id=? AND status='Active' AND deleted_at IS NULL",(body.get('employee_id'),))
        if not recipient:raise HTTPException(400,'Select a valid active employee receiving the material')
        lines=[]
        for line in body['items']:
            master=fetch_one('SELECT * FROM items WHERE id=?',(line['item_id'],))
            snap=uom_snapshot(master,line['quantity'],line.get('transaction_uom'),purpose='issue')
            lines.append({**line,**{k:float(v) if k in ('transaction_quantity','conversion_factor_used','base_quantity') else v for k,v in snap.items()}})
        values=issue_fifo_value(lines,breakdown=True);total=float(money(sum(values)))
        requester=employee_for_user({'id':row['created_by']})
        if not requester:raise HTTPException(409,'The original requester must have an active employee record before revising approval routing')
        approver,limit,level,rule=route_approver(requester['id'],total,'ISSUE',lines[0]['warehouse_id'])
        c.execute('DELETE FROM material_issue_items WHERE issue_id=?',(issue_id,))
        for line,value in zip(lines,values):
            c.execute('INSERT INTO material_issue_items(issue_id,item_id,warehouse_id,location_id,quantity,value,transaction_quantity,transaction_uom,conversion_factor_used,base_quantity,base_uom)VALUES(?,?,?,?,?,?,?,?,?,?,?)',(issue_id,line['item_id'],line['warehouse_id'],line['location_id'],line['quantity'],value,line['transaction_quantity'],line['transaction_uom'],line['conversion_factor_used'],line['base_quantity'],line['base_uom']))
        c.execute('UPDATE material_issues SET employee_id=?,purpose=?,total_value=? WHERE id=?',(recipient['id'],body.get('purpose'),total,issue_id))
        c.execute("UPDATE approval_log SET approval_value=?,required_role=?,approver_employee_id=?,approver_role=?,workflow_level=?,escalation_rule=? WHERE document_type='ISSUE' AND document_id=? AND decision='Pending'",(total,approver['user_role'],approver['id'],approver['user_role'],str(level),rule,issue_id))
        log_audit(c,'material_issues',issue_id,'UPDATE',user['id'],{**row,'items':old_lines},{**body,'total_value':total,'approver_employee_id':approver['id'],'workflow_action':'REVIEW_AND_EDIT'})
    return {'id':issue_id,'status':'PendingApproval','total_value':total}

@router.post('/material-issues',status_code=201)
def create_issue(body:dict,user:dict=Depends(roles(*WH))):
    items=body.get('items');
    employee=fetch_one("SELECT id FROM employees WHERE id=? AND status='Active' AND deleted_at IS NULL",(body.get('employee_id'),))
    if not employee:raise HTTPException(400,'Select a valid active employee receiving the material')
    if not isinstance(items,list)or not items:raise HTTPException(400,'At least one item required')
    masters=[]
    for x in items:
        scope(user,x.get('warehouse_id'),'WH_MATERIAL_ISSUE');locations(x.get('warehouse_id'),x.get('location_id'));master=fetch_one('SELECT * FROM items WHERE id=?',(x.get('item_id'),));
        if not master or not isinstance(x.get('quantity'),(int,float))or x['quantity']<=0:raise HTTPException(400,'Every issue line requires a valid item, warehouse, Bin, and positive quantity')
        masters.append((x,master,uom_snapshot(master,x['quantity'],x.get('transaction_uom'),purpose='issue')))
        if master.get('consumable_returnable')=='Returnable':raise HTTPException(409,'Issue returnable tools manually in Tool Management by selecting their Tool Codes')
    if len({x['warehouse_id']for x,_,_ in masters})!=1:raise HTTPException(400,'A Material Issue must contain items from one authorized warehouse')
    line_values=issue_fifo_value([{**x,'base_quantity':float(snapshot['base_quantity'])} for x,m,snapshot in masters],breakdown=True);estimate=float(money(sum(line_values)));wid=items[0]['warehouse_id'];requester=employee_for_user(user)
    if not requester:raise HTTPException(403,'An active Warehouse employee record is required')
    approver,limit,level,rule=route_approver(requester['id'],estimate,'ISSUE',wid);required=True;status='PendingApproval'
    with transaction(immediate=True)as c:
        num=number(c,'ISSUE');cur=c.execute('INSERT INTO material_issues(issue_number,employee_id,purpose,approval_required,status,created_by,total_value)VALUES(?,?,?,?,?,?,?)',(num,body.get('employee_id'),body.get('purpose'),int(required),status,user['id'],estimate));iid=cur.lastrowid
        for (x,m,snapshot),line_value in zip(masters,line_values):
            if required:cost=line_value;used=[]
            else:cost,used=consume(c,item_id=x['item_id'],warehouse_id=x['warehouse_id'],location_id=x['location_id'],quantity=float(snapshot['base_quantity']),transaction_type='MATERIAL_ISSUE',reference_number=num,reference_table='material_issues',reference_id=iid,created_by=user['id'])
            line=c.execute('''INSERT INTO material_issue_items(issue_id,item_id,warehouse_id,location_id,quantity,value,transaction_quantity,transaction_uom,conversion_factor_used,base_quantity,base_uom)VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(iid,x['item_id'],x['warehouse_id'],x['location_id'],x['quantity'],cost,float(snapshot['transaction_quantity']),snapshot['transaction_uom'],float(snapshot['conversion_factor_used']),float(snapshot['base_quantity']),snapshot['base_uom']))
            for layer_id,qty,cost_each in used:c.execute('INSERT INTO material_issue_layer_usage(material_issue_item_id,inventory_layer_id,quantity,unit_cost)VALUES(?,?,?,?)',(line.lastrowid,layer_id,qty,cost_each))
        if required:c.execute("INSERT INTO approval_log(document_type,document_id,document_number,required_role,requested_by,decision,approval_value,approval_currency,approver_employee_id,approver_role,workflow_level,escalation_rule)VALUES('ISSUE',?,?,?,?,'Pending',?,?,?,?,?,?)",(iid,num,approver['user_role'],user['id'],estimate,company_base_currency(),approver['id'],approver['user_role'],str(level),rule))
        log_audit(c,'material_issues',iid,'CREATE',user['id'],after=body)
    return {'id':iid,'issue_number':num,'status':status}
@router.put('/material-issues/{issue_id}/approve')
def approve_issue(issue_id:int,user:dict=Depends(roles(*WH))):
    row=fetch_one('SELECT * FROM material_issues WHERE id=?',(issue_id,));
    if not row:raise HTTPException(404,'Not found')
    if row['status']!='PendingApproval':raise HTTPException(400,'This issue is not pending approval')
    lines=fetch_all('SELECT * FROM material_issue_items WHERE issue_id=?',(issue_id,));wid=lines[0]['warehouse_id']if lines else None;scope(user,wid);pending=fetch_one("SELECT * FROM approval_log WHERE document_type='ISSUE'AND document_id=?AND decision='Pending' ORDER BY sequence,id LIMIT 1",(issue_id,))
    if not pending:raise HTTPException(409,'This Material Issue has no pending approval')
    employee,limit,authority=approval_authorized(user,row['created_by'],issue_fifo_value(lines),'ISSUE',wid,pending);total=0
    with transaction(immediate=True)as c:
        current=c.execute('SELECT status FROM material_issues WHERE id=?',(issue_id,)).fetchone()
        if current['status']!='PendingApproval':raise HTTPException(409,'This issue is no longer pending approval')
        lines=[dict(line) for line in c.execute('SELECT * FROM material_issue_items WHERE issue_id=?',(issue_id,))]
        wid=lines[0]['warehouse_id'] if lines else None;scope(user,wid)
        pending=dict(c.execute("SELECT * FROM approval_log WHERE document_type='ISSUE' AND document_id=? AND decision='Pending' ORDER BY sequence,id LIMIT 1",(issue_id,)).fetchone())
        for x in lines:
            cost,used=consume(c,item_id=x['item_id'],warehouse_id=x['warehouse_id'],location_id=x['location_id'],quantity=float(x.get('base_quantity')or x['quantity']),transaction_type='MATERIAL_ISSUE',reference_number=row['issue_number'],reference_table='material_issues',reference_id=issue_id,created_by=user['id']);c.execute('UPDATE material_issue_items SET value=? WHERE id=?',(cost,x['id']));total+=cost
            for layer_id,qty,unit in used:c.execute('INSERT INTO material_issue_layer_usage(material_issue_item_id,inventory_layer_id,quantity,unit_cost)VALUES(?,?,?,?)',(x['id'],layer_id,qty,unit))
        employee,limit,authority=approval_authorized(user,row['created_by'],float(money(total)),'ISSUE',wid,pending)
        c.execute("UPDATE material_issues SET status='Posted',approved_by=?,total_value=? WHERE id=?",(user['id'],total,issue_id));c.execute("UPDATE approval_log SET decision='Approved',decision_by=?,decision_date=datetime('now'),approval_limit_used=?,approval_limit_source=? WHERE id=?",(user['id'],limit,authority,pending['id']));log_audit(c,'material_issues',issue_id,'APPROVE',user['id'],row,{'authority':authority,'approval_limit':limit})
    return {'success':True}
@router.put('/material-issues/{issue_id}/reject')
def reject_issue(issue_id:int,user:dict=Depends(roles(*WH))):
    row=fetch_one('SELECT * FROM material_issues WHERE id=?',(issue_id,));
    if not row:raise HTTPException(404,'Not found')
    if row['status']!='PendingApproval':raise HTTPException(409,f"Issue is {row['status']} and can no longer be amended")
    lines=fetch_all('SELECT * FROM material_issue_items WHERE issue_id=?',(issue_id,));wid=lines[0]['warehouse_id']if lines else None;scope(user,wid);pending=fetch_one("SELECT * FROM approval_log WHERE document_type='ISSUE'AND document_id=?AND decision='Pending' ORDER BY sequence,id LIMIT 1",(issue_id,))
    if not pending:raise HTTPException(409,'This Material Issue has no pending approval')
    approval_authorized(user,row['created_by'],issue_fifo_value(lines),'ISSUE',wid,pending)
    with transaction(immediate=True)as c:c.execute("UPDATE material_issues SET status='Rejected' WHERE id=?",(issue_id,));c.execute("UPDATE approval_log SET decision='Rejected',decision_by=?,decision_date=datetime('now') WHERE document_type='ISSUE'AND document_id=?AND decision='Pending'",(user['id'],issue_id));log_audit(c,'material_issues',issue_id,'REJECT',user['id'])
    return {'success':True}
@router.get('/material-issues/{issue_id}/approval-history')
def issue_history(issue_id:int,_u:User):return approval_history('ISSUE',issue_id)
def allocate_original_custody(connection,employee_id,item_id,warehouse_id,requested_quantity):
    rows=connection.execute('''SELECT mii.id,mii.quantity,mii.transaction_uom,mii.conversion_factor_used,mii.base_quantity,mii.base_uom,mii.value,
      COALESCE((SELECT SUM(a.transaction_quantity)FROM employee_return_allocations a WHERE a.issue_item_id=mii.id),0)allocated
      FROM material_issue_items mii JOIN material_issues mi ON mi.id=mii.issue_id JOIN items i ON i.id=mii.item_id
      WHERE mi.employee_id=?AND mii.item_id=?AND mii.warehouse_id=?AND mi.status='Posted' ORDER BY mi.issue_date,mi.id,mii.id''',(employee_id,item_id,warehouse_id)).fetchall()
    legacy=float((connection.execute('''SELECT COALESCE(SUM(r.quantity),0)quantity FROM returns r WHERE r.employee_id=?AND r.item_id=?AND r.warehouse_id=?
      AND NOT EXISTS(SELECT 1 FROM employee_return_allocations a WHERE a.return_id=r.id)''',(employee_id,item_id,warehouse_id)).fetchone()or{'quantity':0})['quantity']or 0)
    available=[]
    for row in rows:
        remaining=max(0,float(row['quantity'])-float(row['allocated']or 0))
        legacy_take=min(remaining,legacy);remaining-=legacy_take;legacy-=legacy_take
        if remaining>0:available.append((row,remaining))
    left=float(requested_quantity);allocations=[]
    for row,remaining in available:
        if left<=.000001:break
        take=min(left,remaining);factor=float(row['conversion_factor_used']or 1);base_qty=take*factor;line_base=float(row['base_quantity']or row['quantity']or 0);unit_cost=float(row['value']or 0)/line_base if line_base else 0;allocations.append({'issue_item_id':row['id'],'transaction_quantity':take,'base_quantity':base_qty,'unit_cost':unit_cost,'value':float(money(base_qty*unit_cost)),'transaction_uom':row['transaction_uom'],'factor':factor,'base_uom':row['base_uom']});left-=take
    if left>.000001:raise HTTPException(409,f'Return quantity exceeds the employee outstanding custody quantity of {float(requested_quantity)-left:g}')
    return allocations
@router.post('/returns',status_code=201)
def create_return(body:dict,user:dict=Depends(roles(*WH))):
    wid=body.get('warehouse_id');location_id=body.get('location_id');employee_id=body.get('employee_id');scope(user,wid,'WH_MATERIAL_RETURN');locations(wid,location_id)
    if not fetch_one("SELECT id FROM employees WHERE id=? AND deleted_at IS NULL",(employee_id,)):raise HTTPException(400,'Select a valid employee')
    lines=body.get('items')if isinstance(body.get('items'),list)else[body]
    if not lines:raise HTTPException(400,'Select at least one outstanding item to return')
    normalized=[];seen=set()
    for line in lines:
        try:item_id=int(line.get('item_id'));qty=float(line.get('quantity'))
        except(TypeError,ValueError):raise HTTPException(400,'Every return line requires an item and positive quantity')
        condition=str(line.get('condition')or'').strip()
        if item_id in seen:raise HTTPException(400,'Each item may appear only once in a return')
        if qty<=0 or condition not in ['Good','Damaged','Needs Repair']:raise HTTPException(400,'Every return line requires a positive quantity and a valid condition')
        seen.add(item_id);normalized.append({'item_id':item_id,'quantity':qty,'condition':condition})
    with transaction(immediate=True)as c:
        created=[]
        for line in normalized:
            item=c.execute('SELECT * FROM items WHERE id=?',(line['item_id'],)).fetchone()
            if not item:raise HTTPException(404,'Item not found')
            if item['consumable_returnable']!='Returnable':raise HTTPException(400,f"{item['item_code']} is consumable and does not support returns")
            allocations=allocate_original_custody(c,employee_id,line['item_id'],wid,line['quantity']);base_quantity=sum(a['base_quantity']for a in allocations);return_value=float(money(sum(a['value']for a in allocations)));return_cost=float(money(return_value/base_quantity))if base_quantity else 0;first=allocations[0];inventory_status='PUT_AWAY_PENDING'if line['condition']=='Good'else('DAMAGED'if line['condition']=='Damaged'else'REPAIR_PENDING')
            num=number(c,'RETURN');cur=c.execute('''INSERT INTO returns(return_number,item_id,employee_id,quantity,condition,warehouse_id,location_id,transaction_quantity,transaction_uom,conversion_factor_used,base_quantity,base_uom,unit_cost,return_value,inventory_status)VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(num,line['item_id'],employee_id,line['quantity'],line['condition'],wid,location_id,line['quantity'],first['transaction_uom'],base_quantity/line['quantity'],base_quantity,first['base_uom'],return_cost,return_value,inventory_status))
            for allocation in allocations:c.execute('INSERT INTO employee_return_allocations(return_id,issue_item_id,transaction_quantity,base_quantity,unit_cost,value)VALUES(?,?,?,?,?,?)',(cur.lastrowid,allocation['issue_item_id'],allocation['transaction_quantity'],allocation['base_quantity'],allocation['unit_cost'],allocation['value']))
            c.execute("INSERT INTO inventory_quarantine(item_id,warehouse_id,location_id,quantity,unit_cost,inventory_status,source_table,source_id,created_by,transaction_uom,base_uom,audit_reference)VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(line['item_id'],wid,location_id,base_quantity,return_cost,inventory_status,'returns',cur.lastrowid,user['id'],first['transaction_uom'],first['base_uom'],num))
            log_audit(c,'returns',cur.lastrowid,'CREATE',user['id'],after={**line,'employee_id':employee_id,'warehouse_id':wid,'location_id':location_id,'base_quantity':base_quantity,'unit_cost':return_cost,'return_value':return_value,'inventory_status':inventory_status,'source_issue_item_ids':[a['issue_item_id']for a in allocations]});created.append({'id':cur.lastrowid,'return_number':num})
        from .clearance import refresh_active_for_employee
        refresh_active_for_employee(c,employee_id)
    return created[0]if len(created)==1 else{'returns':created,'count':len(created)}
@router.get('/transfers')
def transfers(user:User):
    ids=user['warehouse_ids'];rows=fetch_all(f"SELECT t.*,i.item_code,i.description,fw.name from_warehouse_name,tw.name to_warehouse_name,fl.code from_location_code,tl.code to_location_code,(SELECT receipt_number FROM transfer_receipts WHERE transfer_id=t.id ORDER BY id DESC LIMIT 1) receipt_number,du.full_name dispatched_by_name,de.signature_url dispatched_by_signature_url,ru.full_name received_by_name,re.signature_url received_by_signature_url FROM transfers t JOIN items i ON i.id=t.item_id LEFT JOIN warehouses fw ON fw.id=t.from_warehouse_id LEFT JOIN warehouses tw ON tw.id=t.to_warehouse_id LEFT JOIN locations fl ON fl.id=t.from_location_id LEFT JOIN locations tl ON tl.id=t.to_location_id LEFT JOIN users du ON du.id=t.dispatched_by LEFT JOIN employees de ON de.id=du.employee_id LEFT JOIN users ru ON ru.id=t.received_by LEFT JOIN employees re ON re.id=ru.employee_id WHERE t.from_warehouse_id IN({','.join('?'for _ in ids)or'NULL'})OR t.to_warehouse_id IN({','.join('?'for _ in ids)or'NULL'}) ORDER BY t.id DESC",ids+ids)
    for row in rows:
        row['items']=_transfer_items(row['id'])
        row['item_count']=len(row['items'])
        row['receipt_items']=_transfer_receipt_items(row['id'])
        latest=fetch_one('SELECT receiving_note,remarks FROM transfer_receipts WHERE transfer_id=? ORDER BY id DESC LIMIT 1',(row['id'],))
        row['receiving_note']=latest['receiving_note'] if latest else None
    return rows

def _transfer_items(transfer_id):
    return fetch_all('''SELECT ti.*,i.item_code,i.description,fl.code from_location_code,tl.code to_location_code
        FROM transfer_items ti JOIN items i ON i.id=ti.item_id
        LEFT JOIN locations fl ON fl.id=ti.from_location_id LEFT JOIN locations tl ON tl.id=ti.to_location_id
        WHERE ti.transfer_id=? ORDER BY ti.id''',(transfer_id,))

def _transfer_receipt_items(transfer_id):
    return fetch_all('''SELECT ri.*,r.receipt_number,r.received_at,i.item_code,i.description,l.code location_code
        FROM transfer_receipt_items ri JOIN transfer_receipts r ON r.id=ri.receipt_id
        JOIN items i ON i.id=ri.item_id LEFT JOIN locations l ON l.id=ri.location_id
        WHERE r.transfer_id=? ORDER BY r.id,ri.id''',(transfer_id,))
@router.get('/bin-transfers')
def bin_transfers(user:dict=Depends(roles(*WH))):
    ids=user['warehouse_ids'];return fetch_all(f"SELECT bt.*,w.warehouse_code,w.name warehouse_name,i.item_code,i.description,fl.code from_bin,tl.code to_bin,u.full_name completed_by_name FROM bin_transfers bt JOIN warehouses w ON w.id=bt.warehouse_id JOIN items i ON i.id=bt.item_id JOIN locations fl ON fl.id=bt.from_location_id JOIN locations tl ON tl.id=bt.to_location_id LEFT JOIN users u ON u.id=bt.completed_by WHERE bt.warehouse_id IN({','.join('?'for _ in ids)or'NULL'}) ORDER BY bt.id DESC",ids)
@router.post('/bin-transfers',status_code=201)
def create_bin_transfer(body:dict,user:dict=Depends(roles(*WH))):
    wid=body.get('warehouse_id');qty=body.get('quantity');scope(user,wid);locations(wid,body.get('from_location_id'));locations(wid,body.get('to_location_id'))
    if body.get('from_location_id')==body.get('to_location_id'):raise HTTPException(400,'Source and destination BIN must be different')
    if not isinstance(qty,(int,float))or qty<=0 or not str(body.get('reason')or'').strip():raise HTTPException(400,'Item, positive quantity and transfer reason are required')
    with transaction(immediate=True)as c:num=number(c,'BINTRANSFER');cost,_=consume(c,item_id=body.get('item_id'),warehouse_id=wid,location_id=body.get('from_location_id'),quantity=qty,transaction_type='BIN_TRANSFER_OUT',reference_number=num,reference_table='bin_transfers',created_by=user['id']);receive(c,item_id=body.get('item_id'),warehouse_id=wid,location_id=body.get('to_location_id'),quantity=qty,unit_cost=cost/qty,transaction_type='BIN_TRANSFER_IN',reference_number=num,reference_table='bin_transfers',created_by=user['id']);cur=c.execute('INSERT INTO bin_transfers(transfer_number,warehouse_id,item_id,from_location_id,to_location_id,quantity,reason,completed_by)VALUES(?,?,?,?,?,?,?,?)',(num,wid,body.get('item_id'),body.get('from_location_id'),body.get('to_location_id'),qty,str(body['reason']).strip(),user['id']));log_audit(c,'bin_transfers',cur.lastrowid,'CREATE',user['id'],after=body);bid=cur.lastrowid
    return {'id':bid,'transfer_number':num}
@router.post('/transfers',status_code=201)
def create_transfer(body:dict,user:dict=Depends(roles(*WH))):
    if isinstance(body.get('items'),list):
        return _create_multi_transfer(body,user)
    fw=body.get('from_warehouse_id');tw=body.get('to_warehouse_id');qty=body.get('quantity')
    if fw==tw:raise HTTPException(400,'Source and destination warehouses must be different')
    scope(user,fw,'WH_TRANSFER');locations(fw,body.get('from_location_id'))
    item=fetch_one('SELECT * FROM items WHERE id=? AND deleted_at IS NULL',(body.get('item_id'),))
    if not item:raise HTTPException(400,'Select a valid active item')
    snap=uom_snapshot(item,qty,body.get('transaction_uom'),purpose='issue');base_qty=float(snap['base_quantity'])
    with transaction(immediate=True)as c:
        selected_tool=None
        if body.get('tool_id'):
            from .advanced import scoped_tool,issue_eligible
            if 'task.transfers' not in user.get('permission_keys',[]):raise HTTPException(403,'Warehouse transfer permission is required')
            selected_tool=scoped_tool(c,body['tool_id'],user);issue_eligible(c,selected_tool,fw)
            if not selected_tool['source_grn_item_id'] or selected_tool['item_id']!=item['id'] or selected_tool['location_id']!=body.get('from_location_id') or base_qty!=1:raise HTTPException(409,'Transfer the selected Tool Code as one base unit from its current location')
        num=number(c,'TRANSFER');cost,used=consume(c,item_id=body.get('item_id'),warehouse_id=fw,location_id=body.get('from_location_id'),quantity=base_qty,transaction_type='TOOL_TRANSFER_OUT' if selected_tool else 'TRANSFER_DISPATCH',reference_number=num,reference_table='transfers',created_by=user['id'],source_grn_item_id=selected_tool['source_grn_item_id'] if selected_tool else None);unit_cost=cost/base_qty
        cur=c.execute("""INSERT INTO transfers(transfer_number,item_id,quantity,from_warehouse_id,from_location_id,to_warehouse_id,to_location_id,transport_mode,vehicle_reference,driver_name,tracking_reference,remarks,status,dispatched_by,dispatched_at,unit_cost,transaction_quantity,transaction_uom,conversion_factor_used,base_quantity,base_uom,dispatched_quantity,outstanding_quantity,total_value)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'In Transit',?,datetime('now'),?,?,?,?,?,?,?,?,?)""",(num,body.get('item_id'),base_qty,fw,body.get('from_location_id'),tw,None,body.get('transport_mode'),body.get('vehicle_reference'),body.get('driver_name'),body.get('tracking_reference'),body.get('remarks'),user['id'],unit_cost,float(snap['transaction_quantity']),snap['transaction_uom'],float(snap['conversion_factor_used']),base_qty,snap['base_uom'],base_qty,base_qty,cost));tid=cur.lastrowid
        item_cur=c.execute('''INSERT INTO transfer_items(transfer_id,item_id,from_location_id,to_location_id,quantity,
          transaction_quantity,transaction_uom,conversion_factor_used,base_uom,unit_cost,total_value,
          dispatched_quantity,outstanding_quantity)VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
          (tid,body.get('item_id'),body.get('from_location_id'),None,base_qty,
           float(snap['transaction_quantity']),snap['transaction_uom'],float(snap['conversion_factor_used']),
           snap['base_uom'],unit_cost,cost,base_qty,base_qty))
        transfer_item_id=item_cur.lastrowid
        for layer_id,take,layer_cost in used:c.execute('INSERT INTO transfer_cost_allocations(transfer_id,transfer_item_id,source_layer_id,dispatched_quantity,unit_cost)VALUES(?,?,?,?,?)',(tid,transfer_item_id,layer_id,take,layer_cost))
        if selected_tool:
            c.execute("UPDATE tools SET status='Quarantined',transfer_id=?,transfer_pending_yn=1,custody_unit_cost=? WHERE id=?",(tid,cost,selected_tool['id']))
            log_audit(c,'tools',selected_tool['id'],'UPDATE',user['id'],selected_tool,{'event':'TRANSFER_DISPATCHED','transfer_id':tid,'from_warehouse_id':fw,'to_warehouse_id':tw})
        c.execute("INSERT INTO in_transit_inventory(transfer_id,item_id,from_warehouse_id,to_warehouse_id,dispatched_quantity,outstanding_quantity,unit_cost,total_value)VALUES(?,?,?,?,?,?,?,?)",(tid,body.get('item_id'),fw,tw,base_qty,base_qty,unit_cost,cost))
        c.execute("INSERT INTO transfer_events(transfer_id,event_type,event_data,performed_by)VALUES(?,?,?,?)",(tid,'DISPATCHED',json.dumps({'quantity':base_qty,'value':cost}),user['id']));log_audit(c,'transfers',tid,'CREATE',user['id'],after={'event':'DISPATCHED','quantity':base_qty,'from_warehouse_id':fw,'to_warehouse_id':tw,'cost':cost})
    return {'id':tid,'transfer_number':num}

def _create_multi_transfer(body,user):
    fw=body.get('from_warehouse_id');tw=body.get('to_warehouse_id')
    if not fw or not tw or fw==tw:raise HTTPException(400,'Select different source and destination warehouses')
    scope(user,fw,'WH_TRANSFER')
    if not fetch_one('SELECT id FROM warehouses WHERE id=? AND deleted_at IS NULL',(tw,)):
        raise HTTPException(400,'Select an active destination warehouse')
    if not str(body.get('transport_mode')or'').strip():raise HTTPException(400,'Select a transport mode')
    if body.get('tool_id'):raise HTTPException(400,'Individual tools must use the Tool Management transfer workflow')
    lines=body['items']
    if not lines:raise HTTPException(400,'Add at least one transfer item')
    seen=set();prepared=[]
    for index,line in enumerate(lines,1):
        item_id=line.get('item_id');source=line.get('from_location_id')
        if not item_id or not source:raise HTTPException(400,f'Line {index}: select an item and source Bin')
        locations(fw,source)
        key=(item_id,source)
        if key in seen:raise HTTPException(400,f'Line {index}: this item and source Bin are already on the transfer')
        seen.add(key)
        item=fetch_one('SELECT * FROM items WHERE id=? AND deleted_at IS NULL AND COALESCE(active_yn,1)=1',(item_id,))
        if not item:raise HTTPException(400,f'Line {index}: select a valid active item')
        if item.get('tool_control_yn') or item.get('consumable_returnable')=='Returnable':
            raise HTTPException(409,f'Line {index}: controlled tools must be transferred by Tool Code in Tool Management')
        snap=uom_snapshot(item,line.get('quantity'),line.get('transaction_uom'),purpose='issue')
        prepared.append((line,snap,float(snap['base_quantity'])))
    with transaction(immediate=True) as c:
        num=number(c,'TRANSFER');first=prepared[0];first_line,first_snap,first_qty=first
        cur=c.execute('''INSERT INTO transfers(transfer_number,item_id,quantity,from_warehouse_id,from_location_id,
            to_warehouse_id,to_location_id,transport_mode,vehicle_reference,driver_name,tracking_reference,remarks,
            status,dispatched_by,dispatched_at,transaction_quantity,transaction_uom,conversion_factor_used,
            base_quantity,base_uom,multi_item_yn)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'In Transit',?,datetime('now'),?,?,?,?,?,1)''',
            (num,first_line['item_id'],first_qty,fw,first_line['from_location_id'],tw,None,
             body['transport_mode'],body.get('vehicle_reference'),body.get('driver_name'),body.get('tracking_reference'),
             body.get('remarks'),user['id'],float(first_snap['transaction_quantity']),first_snap['transaction_uom'],
             float(first_snap['conversion_factor_used']),first_qty,first_snap['base_uom']))
        tid=cur.lastrowid;total_value=0;total_quantity=0
        for index,(line,snap,base_qty) in enumerate(prepared,1):
            cost,used=consume(c,item_id=line['item_id'],warehouse_id=fw,location_id=line['from_location_id'],
                quantity=base_qty,transaction_type='TRANSFER_DISPATCH',reference_number=num,
                reference_table='transfers',reference_id=tid,created_by=user['id'])
            item_cur=c.execute('''INSERT INTO transfer_items(transfer_id,item_id,from_location_id,to_location_id,quantity,
                transaction_quantity,transaction_uom,conversion_factor_used,base_uom,unit_cost,total_value,
                dispatched_quantity,outstanding_quantity) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (tid,line['item_id'],line['from_location_id'],None,base_qty,
                 float(snap['transaction_quantity']),snap['transaction_uom'],float(snap['conversion_factor_used']),
                 snap['base_uom'],cost/base_qty,cost,base_qty,base_qty))
            for layer_id,take,layer_cost in used:
                c.execute('''INSERT INTO transfer_cost_allocations(transfer_id,transfer_item_id,source_layer_id,dispatched_quantity,unit_cost)
                    VALUES(?,?,?,?,?)''',(tid,item_cur.lastrowid,layer_id,take,layer_cost))
            total_value+=cost;total_quantity+=base_qty
        c.execute('''UPDATE transfers SET unit_cost=?,dispatched_quantity=?,outstanding_quantity=?,total_value=? WHERE id=?''',
            (total_value/total_quantity,total_quantity,total_quantity,total_value,tid))
        c.execute("INSERT INTO transfer_events(transfer_id,event_type,event_data,performed_by)VALUES(?,?,?,?)",
            (tid,'DISPATCHED',json.dumps({'item_count':len(prepared),'total_value':total_value}),user['id']))
        log_audit(c,'transfers',tid,'CREATE',user['id'],after={'event':'DISPATCHED','items':lines,
            'from_warehouse_id':fw,'to_warehouse_id':tw,'total_value':total_value})
    return {'id':tid,'transfer_number':num,'item_count':len(prepared)}

def _transfer_allocations(c,transfer_id,quantity,transfer_item_id=None):
    remaining=float(quantity);result=[]
    query='SELECT * FROM transfer_cost_allocations WHERE transfer_id=? AND accounted_quantity<dispatched_quantity'
    params=[transfer_id]
    if transfer_item_id is not None:query+=' AND transfer_item_id=?';params.append(transfer_item_id)
    for row in c.execute(query+' ORDER BY id',params).fetchall():
        take=min(remaining,float(row['dispatched_quantity'])-float(row['accounted_quantity']));
        if take>0:result.append((row,take));remaining-=take
        if remaining<=1e-8:break
    if remaining>1e-6:raise HTTPException(409,'Receipt exceeds the remaining dispatched quantity')
    for row,take in result:c.execute('UPDATE transfer_cost_allocations SET accounted_quantity=accounted_quantity+? WHERE id=?',(take,row['id']))
    return result
@router.put('/transfers/{transfer_id}/receive')
def receive_transfer(transfer_id:int,body:dict,user:dict=Depends(roles(*WH))):
    row=fetch_one("SELECT * FROM transfers WHERE id=?",(transfer_id,));
    if not row:raise HTTPException(404,'Transfer not found')
    if row['dispatched_by']==user['id']:raise HTTPException(403,'The dispatching user cannot receive their own transfer')
    scope(user,row['to_warehouse_id'])
    if row.get('multi_item_yn'):
        return _receive_multi_transfer(transfer_id,body,user,row)
    if row['status'] not in ('In Transit','Partially Received'):raise HTTPException(409,f"Transfer is {row['status']} and cannot receive more stock")
    lid=body.get('to_location_id');locations(row['to_warehouse_id'],lid)
    legacy_full=not any(key in body for key in ('physical_quantity','good_quantity','damaged_quantity','rejected_quantity','shortage_quantity','quantity_received'))
    good=float(decimal_value(row.get('outstanding_quantity')or row['quantity'] if legacy_full else body.get('good_quantity',body.get('quantity_received',0)),'Good quantity',nonnegative=True));damaged=float(decimal_value(body.get('damaged_quantity',0),'Damaged quantity',nonnegative=True));rejected=float(decimal_value(body.get('rejected_quantity',0),'Rejected quantity',nonnegative=True));shortage=float(decimal_value(body.get('shortage_quantity',0),'Shortage quantity',nonnegative=True));physical=float(decimal_value(body.get('physical_quantity',good+damaged+rejected),'Physical quantity',nonnegative=True))
    if physical<=0 and shortage<=0:raise HTTPException(400,'Receipt must account for a positive physical or shortage quantity')
    if good+damaged+rejected>physical+1e-6:raise HTTPException(400,'Good, damaged, and rejected quantities cannot exceed physical quantity')
    if abs((good+damaged+rejected)-physical)>1e-6:raise HTTPException(400,'Every physical unit must be classified as good, damaged, or rejected')
    accounted=physical+shortage
    with transaction(immediate=True)as c:
        current=dict(c.execute('SELECT * FROM transfers WHERE id=?',(transfer_id,)).fetchone());outstanding=float(current.get('outstanding_quantity')or current['quantity']);receipt_sequence=c.execute('SELECT COUNT(*) n FROM transfer_receipts WHERE transfer_id=?',(transfer_id,)).fetchone()['n']+1;ref=f"TRR-{current['transfer_number']}-{receipt_sequence:02d}"
        selected_tool=c.execute('SELECT * FROM tools WHERE transfer_id=?',(transfer_id,)).fetchone()
        if selected_tool:
            if not selected_tool['transfer_pending_yn']:raise HTTPException(409,'This tool transfer has already been received')
            if not all(value.is_integer() for value in (good,damaged,rejected,shortage)) or accounted!=1:raise HTTPException(400,'Receive the individual tool as one whole unit')
        if accounted>outstanding+1e-6:raise HTTPException(409,'Receipt exceeds the remaining dispatched quantity')
        allocations=_transfer_allocations(c,transfer_id,accounted);avg=sum(take*float(a['unit_cost'])for a,take in allocations)/accounted
        cur=c.execute('''INSERT INTO transfer_receipts(receipt_number,transfer_id,warehouse_id,location_id,item_id,quantity_received,receiving_note,received_by,physical_quantity,good_quantity,damaged_quantity,rejected_quantity,shortage_quantity,unit_cost,total_value,receipt_status,remarks)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(ref,transfer_id,current['to_warehouse_id'],lid,current['item_id'],physical,body.get('receiving_note'),user['id'],physical,good,damaged,rejected,shortage,avg,accounted*avg,'POSTED',body.get('remarks')));receipt_id=cur.lastrowid
        transfer_item=c.execute('SELECT id,outstanding_quantity FROM transfer_items WHERE transfer_id=? ORDER BY id LIMIT 1',(transfer_id,)).fetchone()
        if transfer_item:
            c.execute('''INSERT INTO transfer_receipt_items(receipt_id,transfer_item_id,item_id,location_id,
              physical_quantity,good_quantity,damaged_quantity,rejected_quantity,shortage_quantity,unit_cost,total_value)
              VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(receipt_id,transfer_item['id'],current['item_id'],lid,physical,good,damaged,rejected,shortage,avg,accounted*avg))
            c.execute('''UPDATE transfer_items SET to_location_id=COALESCE(to_location_id,?),received_good_quantity=received_good_quantity+?,damaged_quantity=damaged_quantity+?,
              rejected_quantity=rejected_quantity+?,shortage_quantity=shortage_quantity+?,outstanding_quantity=? WHERE id=?''',
              (lid,good,damaged,rejected,shortage,max(0,float(transfer_item['outstanding_quantity'])-accounted),transfer_item['id']))
        item_master=dict(c.execute('SELECT * FROM items WHERE id=?',(current['item_id'],)).fetchone());good_status='INSPECTION_PENDING'if item_master.get('inspection_required_yn')else'PUT_AWAY_PENDING';buckets=[('good',good),('damaged',damaged),('rejected',rejected),('shortage',shortage)];allocation_queue=[[a,take]for a,take in allocations]
        for kind,qty in buckets:
            left=qty
            while left>1e-8:
                a,available=allocation_queue[0];take=min(left,available);cost=float(a['unit_cost'])
                if kind=='good':c.execute("INSERT INTO inventory_quarantine(item_id,warehouse_id,location_id,quantity,unit_cost,inventory_status,source_table,source_id,created_by,transaction_uom,base_uom,audit_reference)VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(current['item_id'],current['to_warehouse_id'],lid,take,cost,good_status,'transfer_receipts',receipt_id,user['id'],current.get('transaction_uom'),current.get('base_uom'),ref))
                elif kind in ('damaged','rejected'):c.execute("INSERT INTO inventory_quarantine(item_id,warehouse_id,location_id,quantity,unit_cost,inventory_status,source_table,source_id,created_by)VALUES(?,?,?,?,?,?,?,?,?)",(current['item_id'],current['to_warehouse_id'],lid,take,cost,kind.upper(),'transfer_receipts',receipt_id,user['id']))
                else:c.execute("INSERT INTO transfer_shortages(transfer_id,receipt_id,item_id,quantity,unit_cost,total_value,remarks,recorded_by)VALUES(?,?,?,?,?,?,?,?)",(transfer_id,receipt_id,current['item_id'],take,cost,take*cost,body.get('remarks')or body.get('receiving_note'),user['id']))
                left-=take;allocation_queue[0][1]-=take
                if allocation_queue[0][1]<=1e-8:allocation_queue.pop(0)
        if selected_tool:
            tool_status='Lost' if shortage else ('Available' if good else 'Quarantined')
            tool_condition='Lost' if shortage else ('Good' if good else 'Damaged')
            c.execute('UPDATE tools SET warehouse_id=?,location_id=NULL,status=?,condition=?,transfer_pending_yn=0 WHERE id=?',(current['to_warehouse_id'],tool_status,tool_condition,selected_tool['id']))
            c.execute("UPDATE inventory_quarantine SET tool_id=? WHERE source_table='transfer_receipts' AND source_id=?",(selected_tool['id'],receipt_id))
            log_audit(c,'tools',selected_tool['id'],'UPDATE',user['id'],dict(selected_tool),{'event':'TRANSFER_RECEIVED','transfer_id':transfer_id,'receipt_id':receipt_id,'status':tool_status,'warehouse_id':current['to_warehouse_id']})
        remaining=max(0,outstanding-accounted);status='Partially Received'if remaining>1e-6 else('Received With Variance'if damaged+rejected+shortage>0 else'Received')
        c.execute('''UPDATE transfers SET status=?,to_location_id=?,received_by=?,received_at=datetime('now'),receiving_reference=?,received_good_quantity=received_good_quantity+?,damaged_quantity=damaged_quantity+?,rejected_quantity=rejected_quantity+?,shortage_quantity=shortage_quantity+?,outstanding_quantity=? WHERE id=?''',(status,lid,user['id'],ref,good,damaged,rejected,shortage,remaining,transfer_id));c.execute("UPDATE in_transit_inventory SET outstanding_quantity=?,status=?,updated_at=datetime('now') WHERE transfer_id=?",(remaining,'RECEIVED'if remaining<=1e-6 else'IN_TRANSIT',transfer_id));c.execute("INSERT INTO transfer_events(transfer_id,event_type,event_data,performed_by)VALUES(?,?,?,?)",(transfer_id,'RECEIPT_POSTED',json.dumps({'receipt_id':receipt_id,'good':good,'damaged':damaged,'rejected':rejected,'shortage':shortage}),user['id']));log_audit(c,'transfers',transfer_id,'UPDATE',user['id'],current,{'event':'RECEIPT_POSTED','status':status,'outstanding_quantity':remaining})
    return {'success':True,'status':status,'receipt_number':ref,'outstanding_quantity':remaining}

def _receive_multi_transfer(transfer_id,body,user,row):
    if row['status'] not in ('In Transit','Partially Received'):
        raise HTTPException(409,f"Transfer is {row['status']} and cannot receive more stock")
    scope(user,row['to_warehouse_id'])
    submitted=body.get('items')
    if not isinstance(submitted,list) or not submitted:raise HTTPException(400,'Add at least one receipt item')
    seen=set();prepared=[]
    for index,line in enumerate(submitted,1):
        item_line_id=line.get('transfer_item_id')
        if not item_line_id or item_line_id in seen:raise HTTPException(400,f'Line {index}: select each transfer item once')
        seen.add(item_line_id)
        lid=line.get('to_location_id')
        locations(row['to_warehouse_id'],lid)
        good=float(decimal_value(line.get('good_quantity',0),f'Line {index} good quantity',nonnegative=True))
        damaged=float(decimal_value(line.get('damaged_quantity',0),f'Line {index} damaged quantity',nonnegative=True))
        rejected=float(decimal_value(line.get('rejected_quantity',0),f'Line {index} rejected quantity',nonnegative=True))
        shortage=float(decimal_value(line.get('shortage_quantity',0),f'Line {index} shortage quantity',nonnegative=True))
        physical=float(decimal_value(line.get('physical_quantity',good+damaged+rejected),f'Line {index} physical quantity',nonnegative=True))
        if abs(good+damaged+rejected-physical)>1e-6:
            raise HTTPException(400,f'Line {index}: physical quantity must equal good, damaged and rejected quantities')
        if physical+shortage<=0:continue
        prepared.append((item_line_id,lid,physical,good,damaged,rejected,shortage))
    if not prepared:raise HTTPException(400,'Receipt must account for at least one item')
    with transaction(immediate=True) as c:
        current=dict(c.execute('SELECT * FROM transfers WHERE id=?',(transfer_id,)).fetchone())
        if current['status'] not in ('In Transit','Partially Received'):
            raise HTTPException(409,'This transfer has already been received')
        item_rows={entry['id']:dict(entry) for entry in c.execute('SELECT * FROM transfer_items WHERE transfer_id=?',(transfer_id,)).fetchall()}
        for index,(item_line_id,_,physical,_,_,_,shortage) in enumerate(prepared,1):
            if item_line_id not in item_rows:raise HTTPException(400,f'Line {index}: item does not belong to this transfer')
            if physical+shortage>float(item_rows[item_line_id]['outstanding_quantity'])+1e-6:
                raise HTTPException(409,f'Line {index}: receipt exceeds outstanding quantity')
        sequence=c.execute('SELECT COUNT(*) n FROM transfer_receipts WHERE transfer_id=?',(transfer_id,)).fetchone()['n']+1
        ref=f"TRR-{current['transfer_number']}-{sequence:02d}"
        first=item_rows[prepared[0][0]]
        totals={'physical':0,'good':0,'damaged':0,'rejected':0,'shortage':0,'value':0}
        header_accounted=sum(entry[2]+entry[6] for entry in prepared)
        receipt_cur=c.execute('''INSERT INTO transfer_receipts(receipt_number,transfer_id,warehouse_id,location_id,item_id,
            quantity_received,receiving_note,received_by,physical_quantity,good_quantity,damaged_quantity,
            rejected_quantity,shortage_quantity,unit_cost,total_value,receipt_status,remarks)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (ref,transfer_id,current['to_warehouse_id'],prepared[0][1],first['item_id'],header_accounted,body.get('receiving_note'),
             user['id'],0,0,0,0,0,0,0,'POSTED',body.get('remarks')))
        receipt_id=receipt_cur.lastrowid
        for item_line_id,lid,physical,good,damaged,rejected,shortage in prepared:
            line=item_rows[item_line_id];accounted=physical+shortage
            allocations=_transfer_allocations(c,transfer_id,accounted,item_line_id)
            line_value=sum(take*float(a['unit_cost']) for a,take in allocations)
            unit_cost=line_value/accounted
            receipt_line_cur=c.execute('''INSERT INTO transfer_receipt_items(receipt_id,transfer_item_id,item_id,location_id,
                physical_quantity,good_quantity,damaged_quantity,rejected_quantity,shortage_quantity,unit_cost,total_value)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                (receipt_id,item_line_id,line['item_id'],lid,physical,good,damaged,rejected,shortage,unit_cost,line_value))
            receipt_line_id=receipt_line_cur.lastrowid
            master=dict(c.execute('SELECT * FROM items WHERE id=?',(line['item_id'],)).fetchone())
            good_status='INSPECTION_PENDING' if master.get('inspection_required_yn') else 'PUT_AWAY_PENDING'
            allocation_queue=[[allocation,take] for allocation,take in allocations]
            for kind,quantity in (('good',good),('damaged',damaged),('rejected',rejected),('shortage',shortage)):
                left=quantity
                while left>1e-8:
                    allocation,available=allocation_queue[0];take=min(left,available);cost=float(allocation['unit_cost'])
                    if kind=='good':
                        c.execute('''INSERT INTO inventory_quarantine(item_id,warehouse_id,location_id,quantity,unit_cost,
                            inventory_status,source_table,source_id,created_by,transaction_uom,base_uom,audit_reference)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (line['item_id'],current['to_warehouse_id'],lid,take,cost,good_status,'transfer_receipt_items',
                             receipt_line_id,user['id'],line['transaction_uom'],line['base_uom'],ref))
                    elif kind in ('damaged','rejected'):
                        c.execute('''INSERT INTO inventory_quarantine(item_id,warehouse_id,location_id,quantity,unit_cost,
                            inventory_status,source_table,source_id,created_by)VALUES(?,?,?,?,?,?,?,?,?)''',
                            (line['item_id'],current['to_warehouse_id'],lid,take,cost,kind.upper(),'transfer_receipt_items',receipt_line_id,user['id']))
                    else:
                        c.execute('''INSERT INTO transfer_shortages(transfer_id,receipt_id,transfer_item_id,item_id,quantity,
                            unit_cost,total_value,remarks,recorded_by)VALUES(?,?,?,?,?,?,?,?,?)''',
                            (transfer_id,receipt_id,item_line_id,line['item_id'],take,cost,take*cost,
                             body.get('remarks') or body.get('receiving_note'),user['id']))
                    left-=take;allocation_queue[0][1]-=take
                    if allocation_queue[0][1]<=1e-8:allocation_queue.pop(0)
            remaining=max(0,float(line['outstanding_quantity'])-accounted)
            c.execute('''UPDATE transfer_items SET to_location_id=COALESCE(to_location_id,?),received_good_quantity=received_good_quantity+?,
                damaged_quantity=damaged_quantity+?,rejected_quantity=rejected_quantity+?,
                shortage_quantity=shortage_quantity+?,outstanding_quantity=? WHERE id=?''',
                (lid,good,damaged,rejected,shortage,remaining,item_line_id))
            for key,value in (('physical',physical),('good',good),('damaged',damaged),('rejected',rejected),('shortage',shortage),('value',line_value)):
                totals[key]+=value
        outstanding=c.execute('SELECT COALESCE(SUM(outstanding_quantity),0) n FROM transfer_items WHERE transfer_id=?',(transfer_id,)).fetchone()['n']
        has_variance=c.execute('SELECT 1 FROM transfer_items WHERE transfer_id=? AND (damaged_quantity>0 OR rejected_quantity>0 OR shortage_quantity>0) LIMIT 1',(transfer_id,)).fetchone()
        status='Partially Received' if outstanding>1e-6 else ('Received With Variance' if has_variance else 'Received')
        c.execute('''UPDATE transfer_receipts SET quantity_received=?,physical_quantity=?,good_quantity=?,
            damaged_quantity=?,rejected_quantity=?,shortage_quantity=?,unit_cost=?,total_value=? WHERE id=?''',
            (header_accounted,totals['physical'],totals['good'],totals['damaged'],totals['rejected'],
             totals['shortage'],totals['value']/(totals['physical']+totals['shortage']),totals['value'],receipt_id))
        c.execute('''UPDATE transfers SET status=?,to_location_id=COALESCE(to_location_id,?),received_by=?,received_at=datetime('now'),receiving_reference=?,
            received_good_quantity=received_good_quantity+?,damaged_quantity=damaged_quantity+?,
            rejected_quantity=rejected_quantity+?,shortage_quantity=shortage_quantity+?,outstanding_quantity=? WHERE id=?''',
            (status,prepared[0][1],user['id'],ref,totals['good'],totals['damaged'],totals['rejected'],totals['shortage'],outstanding,transfer_id))
        c.execute('INSERT INTO transfer_events(transfer_id,event_type,event_data,performed_by)VALUES(?,?,?,?)',
            (transfer_id,'RECEIPT_POSTED',json.dumps({'receipt_id':receipt_id,'items':len(prepared),'status':status}),user['id']))
        log_audit(c,'transfers',transfer_id,'UPDATE',user['id'],current,
            {'event':'RECEIPT_POSTED','receipt_id':receipt_id,'status':status,'outstanding_quantity':outstanding})
    return {'success':True,'status':status,'receipt_number':ref,'outstanding_quantity':outstanding}

@router.put('/transfers/{transfer_id}/shortages/{shortage_id}/resolve')
def resolve_transfer_shortage(transfer_id:int,shortage_id:int,body:dict,user:dict=Depends(roles(*WH))):
    transfer=fetch_one('SELECT * FROM transfers WHERE id=?',(transfer_id,));shortage=fetch_one("SELECT * FROM transfer_shortages WHERE id=? AND transfer_id=? AND status='OPEN'",(shortage_id,transfer_id))
    if not transfer or not shortage:raise HTTPException(404,'Open transfer shortage not found')
    scope(user,transfer['to_warehouse_id']);resolution=str(body.get('resolution_type')or'').upper()
    if resolution not in ('FOUND_AND_RECEIVED','RETURNED_TO_SOURCE','APPROVED_ADJUSTMENT'):raise HTTPException(400,'Select a controlled shortage resolution')
    if resolution=='APPROVED_ADJUSTMENT':
        adjustment=fetch_one("SELECT * FROM stock_adjustments WHERE id=? AND status='Approved'",(body.get('adjustment_id'),))
        if not adjustment:raise HTTPException(409,'An approved stock adjustment is required for a shortage write-off')
    with transaction(immediate=True)as c:
        current_shortage=c.execute('SELECT status FROM transfer_shortages WHERE id=?',(shortage_id,)).fetchone()
        if current_shortage['status']!='OPEN':raise HTTPException(409,'This shortage was already resolved')
        selected_tool=c.execute('SELECT * FROM tools WHERE transfer_id=?',(transfer_id,)).fetchone()
        if resolution in ('FOUND_AND_RECEIVED','RETURNED_TO_SOURCE'):
            wid=transfer['to_warehouse_id'] if resolution=='FOUND_AND_RECEIVED' else transfer['from_warehouse_id']
            scope(user,wid)
            item_line=c.execute('SELECT * FROM transfer_items WHERE id=? AND transfer_id=?',(shortage.get('transfer_item_id'),transfer_id)).fetchone() if shortage.get('transfer_item_id') else None
            lid=body.get('location_id') or ((item_line['to_location_id'] if resolution=='FOUND_AND_RECEIVED' else item_line['from_location_id']) if item_line else (transfer['to_location_id'] if resolution=='FOUND_AND_RECEIVED' else transfer['from_location_id']))
            locations(wid,lid)
            receive(c,item_id=shortage['item_id'],warehouse_id=wid,location_id=lid,quantity=shortage['quantity'],unit_cost=shortage['unit_cost'],transaction_type='TRANSFER_SHORTAGE_RESOLUTION',reference_number=transfer['transfer_number'],reference_table='transfer_shortages',reference_id=shortage_id,created_by=user['id'],source_grn_item_id=selected_tool['source_grn_item_id'] if selected_tool else None)
            if selected_tool:c.execute("UPDATE tools SET warehouse_id=?,location_id=?,condition='Good',status='Available' WHERE id=?",(wid,lid,selected_tool['id']))
        if selected_tool:log_audit(c,'tools',selected_tool['id'],'UPDATE',user['id'],dict(selected_tool),{'event':'TRANSFER_SHORTAGE_RESOLVED','resolution':resolution,'transfer_id':transfer_id})
        c.execute("UPDATE transfer_shortages SET status='RESOLVED',resolution_type=?,resolution_reference=?,resolved_by=?,resolved_at=datetime('now') WHERE id=?",(resolution,str(body.get('adjustment_id')or body.get('resolution_reference')or''),user['id'],shortage_id));c.execute("INSERT INTO transfer_events(transfer_id,event_type,event_data,performed_by)VALUES(?,?,?,?)",(transfer_id,'SHORTAGE_RESOLVED',json.dumps({'shortage_id':shortage_id,'resolution_type':resolution}),user['id']));log_audit(c,'transfer_shortages',shortage_id,'UPDATE',user['id'],shortage,body)
    return {'success':True,'status':'RESOLVED'}

@router.put('/transfers/{transfer_id}/close')
def close_transfer(transfer_id:int,user:dict=Depends(roles(*WH))):
    row=fetch_one('SELECT * FROM transfers WHERE id=?',(transfer_id,));
    if not row:raise HTTPException(404,'Transfer not found')
    scope(user,row['to_warehouse_id'])
    if float(row.get('outstanding_quantity')or 0)>1e-6:raise HTTPException(409,'Transfer cannot close while quantity remains in transit')
    if fetch_one("SELECT id FROM transfer_shortages WHERE transfer_id=? AND status='OPEN' LIMIT 1",(transfer_id,)):raise HTTPException(409,'Resolve all transfer shortages before closure')
    with transaction(immediate=True)as c:c.execute("UPDATE transfers SET status='Closed',closed_by=?,closed_at=datetime('now') WHERE id=?",(user['id'],transfer_id));c.execute("INSERT INTO transfer_events(transfer_id,event_type,performed_by)VALUES(?,?,?)",(transfer_id,'CLOSED',user['id']));log_audit(c,'transfers',transfer_id,'UPDATE',user['id'],row,{'event':'CLOSED','status':'Closed'})
    return {'success':True,'status':'Closed'}
@router.get('/adjustments')
def adjustments(user:User):
    ids=user['warehouse_ids'];return fetch_all(f"SELECT a.*,i.item_code,i.description,w.name warehouse_name,l.code location_code FROM stock_adjustments a JOIN items i ON i.id=a.item_id JOIN warehouses w ON w.id=a.warehouse_id LEFT JOIN locations l ON l.id=a.location_id WHERE a.warehouse_id IN({','.join('?'for _ in ids)or'NULL'}) ORDER BY a.id DESC",ids)
@router.post('/adjustments',status_code=201)
def create_adjustment(body:dict,user:User):
    delegation=None if user['role']=='SupplyChainManager'else active_delegation(user,'WH_INVENTORY_ADJUST',warehouse_id=body.get('warehouse_id'))
    if user['role']!='SupplyChainManager'and not delegation:raise HTTPException(403,'Only the Supply Chain Manager or a matching active delegate may create this adjustment')
    warehouse_id=body.get('warehouse_id');location_id=body.get('location_id');scope(user,warehouse_id,'WH_INVENTORY_ADJUST');locations(warehouse_id,location_id)
    try:change=float(body.get('quantity_change'))
    except(TypeError,ValueError):raise HTTPException(400,'Adjustment quantity must be numeric')
    reason=str(body.get('reason')or'').strip();remarks=str(body.get('detailed_remarks')or'').strip()
    if not change or not reason or len(remarks)<10:raise HTTPException(400,'A non-zero quantity, reason, and detailed remarks are required')
    item=fetch_one('SELECT standard_cost FROM items WHERE id=? AND deleted_at IS NULL',(body.get('item_id'),))
    if not item:raise HTTPException(400,'Select a valid active item')
    current=fetch_one('SELECT quantity FROM inventory_stock WHERE item_id=? AND warehouse_id=? AND location_id IS ?',(body.get('item_id'),warehouse_id,location_id))or{'quantity':0}
    before=decimal_value(current['quantity']);after=before+decimal_value(change)
    if after<0:raise HTTPException(400,'Adjustment would create negative stock')
    unit_cost=decimal_value(item.get('standard_cost')or 0);impact=money(abs(decimal_value(change))*unit_cost);evaluation=evaluate_authority(user,impact,'ADJUSTMENT',warehouse_id)
    if not evaluation:raise HTTPException(409,'No active adjustment approval authority is available')
    auto=evaluation.outcome=='AUTO_APPROVED_WITHIN_AUTHORITY';attachment_required=not auto
    with transaction(immediate=True)as c:
        num=number(c,'ADJUSTMENT');cur=c.execute("""INSERT INTO stock_adjustments(adjustment_number,item_id,warehouse_id,location_id,quantity_change,reason,status,created_by,quantity_before,quantity_after,unit_cost,total_value_impact,detailed_remarks,attachment_required,approved_by,approved_at,authority_reference,approval_method)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(num,body.get('item_id'),warehouse_id,location_id,change,reason,'Approved'if auto else'Pending',user['id'],float(before),float(after),float(unit_cost),float(impact),remarks,int(attachment_required),user['id']if auto else None,datetime.now().isoformat()if auto else None,evaluation.authority_reference,evaluation.outcome));aid=cur.lastrowid
        c.execute("""INSERT INTO approval_log(document_type,document_id,document_number,required_role,requested_by,decision,decision_by,decision_date,approval_value,approval_currency,approval_limit_used,approver_employee_id,approver_role,approval_method,authority_reference,event_type)
          VALUES('ADJUSTMENT',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(aid,num,evaluation.role,user['id'],'Approved'if auto else'Pending',user['id']if auto else None,datetime.now().isoformat()if auto else None,float(impact),company_base_currency(),float(evaluation.limit),evaluation.employee_id,evaluation.role,evaluation.outcome,evaluation.authority_reference,evaluation.outcome))
        if auto:
            if change>0:receive(c,item_id=body.get('item_id'),warehouse_id=warehouse_id,location_id=location_id,quantity=change,unit_cost=float(unit_cost),transaction_type='ADJUSTMENT_IN',reference_number=num,reference_table='stock_adjustments',reference_id=aid,created_by=user['id'])
            else:consume(c,item_id=body.get('item_id'),warehouse_id=warehouse_id,location_id=location_id,quantity=-change,transaction_type='ADJUSTMENT_OUT',reference_number=num,reference_table='stock_adjustments',reference_id=aid,created_by=user['id'])
        delegated=record_delegated_use(c,delegation,user,'stock_adjustments',aid,'CREATE',{'warehouse_id':warehouse_id})if delegation else{};log_audit(c,'stock_adjustments',aid,'CREATE',user['id'],after={**body,'quantity_before':float(before),'quantity_after':float(after),'total_value_impact':float(impact),'approval_method':evaluation.outcome,**delegated})
    return {'id':aid,'adjustment_number':num,'status':'Approved'if auto else'Pending','approval_method':evaluation.outcome}
@router.put('/adjustments/{adjustment_id}/approve')
def approve_adjustment(adjustment_id:int,user:User):
    row=fetch_one('SELECT * FROM stock_adjustments WHERE id=?',(adjustment_id,));
    if not row:raise HTTPException(404,'Not found')
    scope(user,row['warehouse_id'],'WH_INVENTORY_ADJUST_APPROVE')
    delegation=None if user['role']=='SupplyChainManager'else active_delegation(user,'WH_INVENTORY_ADJUST_APPROVE','INVENTORY_ADJUSTMENT',adjustment_id,warehouse_id=row['warehouse_id'])
    if user['role']!='SupplyChainManager'and not delegation:raise HTTPException(403,'Only the Supply Chain Manager or a matching active delegate may approve this adjustment')
    if row['status']!='Pending':raise HTTPException(409,f"Adjustment is {row['status']} and cannot be approved again")
    if row.get('attachment_required')and not fetch_one("SELECT id FROM document_attachments WHERE document_type='ADJUSTMENT' AND document_id=? LIMIT 1",(adjustment_id,)):raise HTTPException(409,'A supporting attachment is required before this adjustment can be approved')
    with transaction(immediate=True)as c:
        if row['quantity_change']>0:receive(c,item_id=row['item_id'],warehouse_id=row['warehouse_id'],location_id=row['location_id'],quantity=row['quantity_change'],unit_cost=(fetch_one('SELECT standard_cost FROM items WHERE id=?',(row['item_id'],))or{}).get('standard_cost',0),transaction_type='ADJUSTMENT_IN',reference_number=row['adjustment_number'],reference_table='stock_adjustments',reference_id=row['id'],created_by=user['id'])
        else:consume(c,item_id=row['item_id'],warehouse_id=row['warehouse_id'],location_id=row['location_id'],quantity=-row['quantity_change'],transaction_type='ADJUSTMENT_OUT',reference_number=row['adjustment_number'],reference_table='stock_adjustments',reference_id=row['id'],created_by=user['id'])
        c.execute("UPDATE stock_adjustments SET status='Approved',approved_by=?,approved_at=datetime('now') WHERE id=?",(user['id'],row['id']));c.execute("UPDATE approval_log SET decision='Approved',decision_by=?,decision_date=datetime('now'),approval_method='APPROVED_BY_SCM',event_type='APPROVED_BY_SCM' WHERE document_type='ADJUSTMENT'AND document_id=?AND decision='Pending'",(user['id'],row['id']));delegated=record_delegated_use(c,delegation,user,'stock_adjustments',row['id'],'APPROVE',{'warehouse_id':row['warehouse_id']})if delegation else{};log_audit(c,'stock_adjustments',row['id'],'APPROVE',user['id'],row,{'self_approved':row.get('created_by')==user['id'],**delegated})
    return {'success':True}
@router.get('/adjustments/{row_id}/approval-history')
def adjustment_history(row_id:int,_u:User):return approval_history('ADJUSTMENT',row_id)
