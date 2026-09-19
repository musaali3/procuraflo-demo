from ..approval_routing import allows_self_approval
from datetime import datetime,timezone
from fastapi import APIRouter,Depends,HTTPException
from ..audit import log_audit
from ..calculations import decimal_value,money
from ..database import company_base_currency,fetch_all,fetch_one,transaction
from ..security import User,roles
from ..stock import receive

router=APIRouter(prefix='/api/inventory',tags=['inventory']); INV=['SupplyChainManager','WarehouseManager','WarehouseSupervisor','Storekeeper']
def scope_ids(user,warehouse_id=None):
    ids=[int(value) for value in user.get('warehouse_ids',[])]
    if warehouse_id is not None:
        scoped(user,warehouse_id);return[warehouse_id]
    return ids
def valuation(item_id,warehouse_ids):
    if not warehouse_ids:return {'totalQty':0,'totalValue':0,'layers':[]}
    marks=','.join('?'for _ in warehouse_ids)
    layers=fetch_all(f'''SELECT il.*,w.warehouse_code,w.name warehouse_name,l.code location_code
      FROM inventory_layers il JOIN warehouses w ON w.id=il.warehouse_id LEFT JOIN locations l ON l.id=il.location_id
      WHERE il.item_id=? AND il.quantity_remaining>0 AND il.warehouse_id IN({marks}) ORDER BY il.received_date,il.id''',(item_id,*warehouse_ids));return {'totalQty':sum(r['quantity_remaining'] for r in layers),'totalValue':sum(r['quantity_remaining']*r['unit_cost'] for r in layers),'layers':layers}
def scoped(user,warehouse_id):
    if user.get('role')!='SupplyChainManager' and warehouse_id not in user['warehouse_ids']:raise HTTPException(403,'This employee is not assigned to the selected warehouse')
    if not fetch_one('SELECT id FROM warehouses WHERE id=? AND deleted_at IS NULL',(warehouse_id,)):raise HTTPException(409,'The selected warehouse is inactive; its operational workflow is disabled')
def approval_history(kind,row_id):return fetch_all('''SELECT al.*,u1.full_name requested_by_name,u2.full_name decision_by_name,e1.signature_url requested_by_signature_url,e2.signature_url decision_by_signature_url FROM approval_log al LEFT JOIN users u1 ON u1.id=al.requested_by LEFT JOIN users u2 ON u2.id=al.decision_by LEFT JOIN employees e1 ON e1.id=u1.employee_id LEFT JOIN employees e2 ON e2.id=u2.employee_id WHERE al.document_type=? AND al.document_id=? ORDER BY al.sequence,al.id''',(kind,row_id))

def supervisor_assigned(warehouse_id):
    return bool(fetch_one("""SELECT 1 FROM users u LEFT JOIN employees e ON e.id=u.employee_id
      WHERE u.role='WarehouseSupervisor' AND u.is_active=1 AND u.deleted_at IS NULL AND COALESCE(e.status,'Active')='Active'
      AND (EXISTS(SELECT 1 FROM user_warehouse_assignments uwa WHERE uwa.user_id=u.id AND uwa.warehouse_id=? AND uwa.is_active=1)
        OR (NOT EXISTS(SELECT 1 FROM user_warehouse_assignments active_uwa WHERE active_uwa.user_id=u.id AND active_uwa.is_active=1)
          AND (u.warehouse_id=? OR e.warehouse_id=?))) LIMIT 1""",(warehouse_id,warehouse_id,warehouse_id)))

def require_count_performer(user,warehouse_id):
    scoped(user,warehouse_id)
    if user['role']=='WarehouseSupervisor':return
    if user['role']=='Storekeeper' and not supervisor_assigned(warehouse_id):return
    raise HTTPException(403,'Cycle count must be performed by the assigned Warehouse Supervisor, or by a Storekeeper only when no supervisor is assigned')

def require_count_reviewer(user,warehouse_id):
    scoped(user,warehouse_id)
    if user['role'] in ('WarehouseManager','SupplyChainManager'):return
    raise HTTPException(403,'Only the Warehouse Manager or Supply Chain Manager may review cycle counts')

def count_variances(c,count_id):
    return [dict(row) for row in c.execute('SELECT * FROM cycle_count_items WHERE count_id=? AND ABS(COALESCE(variance,0))>.000001 ORDER BY id',(count_id,))]

def adjustment_location(c,warehouse_id,item_id):
    return None

def consume_warehouse(c,*,item_id,warehouse_id,quantity,reference_number,reference_id,created_by):
    if quantity<=0:raise HTTPException(400,'Issue quantity must be greater than zero')
    layers=c.execute('SELECT id,location_id,quantity_remaining,unit_cost FROM inventory_layers WHERE item_id=? AND warehouse_id=? AND quantity_remaining>0 ORDER BY received_date,id',(item_id,warehouse_id)).fetchall();available=sum(x['quantity_remaining'] for x in layers)
    if available<quantity:raise HTTPException(400,f'Insufficient stock: requested {quantity}, available {available} for item {item_id} in warehouse {warehouse_id}')
    left=quantity
    for layer in layers:
        if left<=1e-8:break
        take=min(layer['quantity_remaining'],left)
        c.execute('UPDATE inventory_layers SET quantity_remaining=quantity_remaining-? WHERE id=?',(take,layer['id']))
        c.execute('UPDATE inventory_stock SET quantity=quantity-? WHERE item_id=? AND warehouse_id=? AND location_id IS ?',(take,item_id,warehouse_id,layer['location_id']))
        c.execute('INSERT INTO stock_ledger(transaction_type,item_id,warehouse_id,location_id,quantity_change,unit_cost,inventory_layer_id,reference_number,reference_table,reference_id,created_by)VALUES(?,?,?,?,?,?,?,?,?,?,?)',('CYCLE_COUNT_ADJUSTMENT_OUT',item_id,warehouse_id,layer['location_id'],-take,layer['unit_cost'],layer['id'],reference_number,'stock_adjustments',reference_id,created_by))
        left-=take

@router.get('/stock')
def stock(user:dict=Depends(roles(*INV)),warehouse_id:int|None=None):
    ids=scope_ids(user,warehouse_id)
    if not ids:return []
    return fetch_all(f'''SELECT s.*,i.item_code,i.description,i.uom,w.name warehouse_name,w.warehouse_code,w.site_type,w.site_name,w.address warehouse_address,w.city warehouse_city,l.code location_code,l.type location_type,l.label location_label,l.status location_status,l.max_quantity,COALESCE((SELECT SUM(r.quantity) FROM stock_reservations r WHERE r.item_id=s.item_id AND r.warehouse_id=s.warehouse_id AND r.location_id=s.location_id AND r.status='Active'),0) reserved_quantity,s.quantity-COALESCE((SELECT SUM(r.quantity) FROM stock_reservations r WHERE r.item_id=s.item_id AND r.warehouse_id=s.warehouse_id AND r.location_id=s.location_id AND r.status='Active'),0) available_quantity FROM inventory_stock s JOIN items i ON i.id=s.item_id JOIN warehouses w ON w.id=s.warehouse_id LEFT JOIN locations l ON l.id=s.location_id WHERE s.quantity>0 AND s.warehouse_id IN({','.join('?' for _ in ids)}) ORDER BY i.item_code''',ids)
@router.get('/valuation')
def valuations(warehouse_id:int|None=None,user:dict=Depends(roles(*INV))):
    ids=scope_ids(user,warehouse_id)
    out=[]
    for item in fetch_all('SELECT * FROM items WHERE deleted_at IS NULL'):
        v=valuation(item['id'],ids);out.append({'item_id':item['id'],'item_code':item['item_code'],'description':item['description'],'quantity':v['totalQty'],'value':round(v['totalValue'],2),'avg_unit_cost':round(v['totalValue']/v['totalQty'],2) if v['totalQty'] else 0})
    return out
@router.get('/valuation/{item_id}/layers')
def layers(item_id:int,warehouse_id:int|None=None,user:dict=Depends(roles(*INV))):return valuation(item_id,scope_ids(user,warehouse_id))
@router.get('/expiry')
def expiry(warehouse_id:int|None=None,user:dict=Depends(roles(*INV))):
    ids=scope_ids(user,warehouse_id)
    if not ids:return[]
    rows=fetch_all(f"SELECT il.*,i.item_code,i.description,w.name warehouse_name,CAST(julianday(il.expiry_date)-julianday('now') AS INTEGER) days_remaining FROM inventory_layers il JOIN items i ON i.id=il.item_id JOIN warehouses w ON w.id=il.warehouse_id WHERE il.quantity_remaining>0 AND il.expiry_date IS NOT NULL AND il.warehouse_id IN({','.join('?'for _ in ids)}) ORDER BY il.expiry_date",ids)
    for r in rows:r['alert']='Expired' if r['days_remaining']<0 else '30-day' if r['days_remaining']<=30 else '60-day' if r['days_remaining']<=60 else '90-day' if r['days_remaining']<=90 else None
    return rows
@router.get('/abc-classification')
def abc(warehouse_id:int|None=None,user:dict=Depends(roles(*INV))):
    ids=scope_ids(user,warehouse_id)
    rows=[]
    for i in fetch_all('SELECT * FROM items WHERE deleted_at IS NULL'):rows.append({'item_id':i['id'],'item_code':i['item_code'],'description':i['description'],'value':valuation(i['id'],ids)['totalValue']})
    rows.sort(key=lambda x:x['value'],reverse=True);total=sum(r['value'] for r in rows) or 1;cumulative=0
    for r in rows:cumulative+=r['value'];pct=cumulative/total;r.update(cumulative_pct=round(pct*100,1),classification='A' if pct<=.8 else 'B' if pct<=.95 else 'C')
    return rows
@router.get('/dead-stock')
def dead(warehouse_id:int|None=None,user:dict=Depends(roles(*INV))):
    ids=scope_ids(user,warehouse_id)
    if not ids:return[]
    rows=fetch_all(f'''SELECT i.id item_id,i.item_code,i.description,w.id warehouse_id,w.name warehouse_name,SUM(s.quantity)quantity,
      (SELECT MAX(sl.created_at)FROM stock_ledger sl WHERE sl.item_id=i.id AND sl.warehouse_id=w.id)last_movement
      FROM items i JOIN inventory_stock s ON s.item_id=i.id AND s.quantity>0 JOIN warehouses w ON w.id=s.warehouse_id
      WHERE i.deleted_at IS NULL AND s.warehouse_id IN({','.join('?'for _ in ids)}) GROUP BY i.id,w.id''',ids);out=[]
    for r in rows:
        days=(datetime.now(timezone.utc)-datetime.fromisoformat(r['last_movement']).replace(tzinfo=timezone.utc)).days if r['last_movement'] else None;bucket='Never Moved' if days is None else '365+ days' if days>=365 else '180+ days' if days>=180 else '90+ days' if days>=90 else None
        if bucket:r.update(days_since_movement=days,bucket=bucket);out.append(r)
    return out
@router.get('/cycle-counts')
def counts(user:User):
    ids=user['warehouse_ids'] if user['role']!='SupplyChainManager' else [row['id'] for row in fetch_all('SELECT id FROM warehouses WHERE deleted_at IS NULL')]
    rows=fetch_all(f"SELECT cc.*,w.name warehouse_name FROM cycle_counts cc JOIN warehouses w ON w.id=cc.warehouse_id WHERE cc.warehouse_id IN({','.join('?' for _ in ids) or 'NULL'}) ORDER BY cc.id DESC",ids)
    for row in rows:
        row['has_variance']=bool(fetch_one('SELECT 1 FROM cycle_count_items WHERE count_id=? AND ABS(COALESCE(variance,0))>.000001 LIMIT 1',(row['id'],)))
        row['can_count']=row['status'] in ('Draft','Recount Requested') and ((user['role']=='WarehouseSupervisor' and row['warehouse_id'] in user['warehouse_ids']) or (user['role']=='Storekeeper' and row['warehouse_id'] in user['warehouse_ids'] and not supervisor_assigned(row['warehouse_id'])))
        row['can_review']=row['status']=='Counted' and user['role'] in ('WarehouseManager','SupplyChainManager') and row.get('submitted_by')!=user['id'] and row.get('created_by')!=user['id']
        row['can_approve_adjustments']=row['status']=='Adjustment Pending SCM Approval' and user['role']=='SupplyChainManager'
    return rows

@router.get('/cycle-count-warehouses')
def cycle_count_warehouses(user:User):
    ids=user['warehouse_ids'] if user['role']!='SupplyChainManager' else [row['id'] for row in fetch_all('SELECT id FROM warehouses WHERE deleted_at IS NULL')]
    rows=fetch_all(f"SELECT id,name,warehouse_code FROM warehouses WHERE deleted_at IS NULL AND id IN({','.join('?' for _ in ids) or 'NULL'}) ORDER BY name",ids)
    for row in rows:
        has_supervisor=supervisor_assigned(row['id'])
        row['supervisor_assigned']=has_supervisor
        row['can_create_cycle_count']=user['role'] in ('SupplyChainManager','WarehouseManager','WarehouseSupervisor') or (user['role']=='Storekeeper' and not has_supervisor)
        row['cycle_count_block_reason']='Assigned Warehouse Supervisor must perform cycle count' if user['role']=='Storekeeper' and has_supervisor else None
    return rows

@router.post('/cycle-counts',status_code=201)
def create_count(body:dict,user:dict=Depends(roles('SupplyChainManager','WarehouseManager','WarehouseSupervisor','Storekeeper'))):
    wid=body.get('warehouse_id');items=body.get('item_ids')
    try:
        wid=int(wid)
    except (TypeError,ValueError):
        raise HTTPException(400,'A valid warehouse is required')
    if user['role'] in ('WarehouseSupervisor','Storekeeper'):require_count_performer(user,wid)
    else:scoped(user,wid)
    if not isinstance(items,list) or not items:raise HTTPException(400,'Select at least one item')
    try:
        items=[int(item) for item in items]
    except (TypeError,ValueError):
        raise HTTPException(400,'Item selection contains invalid values')
    if len(set(items))!=len(items) or any(item<=0 for item in items):raise HTTPException(400,'Item selection contains invalid or duplicate values')
    with transaction(immediate=True) as c:
        marks=','.join('?' for _ in items)
        valid_items={row['id'] for row in c.execute(f'SELECT id FROM items WHERE deleted_at IS NULL AND active_yn<>0 AND id IN({marks})',items)}
        if len(valid_items)!=len(items):raise HTTPException(400,'One or more selected items are inactive or unavailable')
        year=str((c.execute('SELECT financial_year FROM company ORDER BY id DESC LIMIT 1').fetchone() or {'financial_year':datetime.now().year})['financial_year']);import re;years=re.findall(r'\d{4}',year);year=years[-1] if years else str(datetime.now().year);row=c.execute("SELECT last_number FROM numbering_counters WHERE doc_type='CYCLECOUNT' AND year=?",(year,)).fetchone();seq=(row['last_number'] if row else 0)+1;c.execute("INSERT INTO numbering_counters(doc_type,year,last_number) VALUES('CYCLECOUNT',?,?) ON CONFLICT(doc_type,year) DO UPDATE SET last_number=excluded.last_number",(year,seq));number=f'CC-{year}-{seq:06d}';cur=c.execute('INSERT INTO cycle_counts(count_number,warehouse_id,created_by)VALUES(?,?,?)',(number,wid,user['id']))
        for item in items:c.execute('INSERT INTO cycle_count_items(count_id,item_id,system_qty)VALUES(?,?,COALESCE((SELECT SUM(quantity) FROM inventory_stock WHERE item_id=? AND warehouse_id=?),0))',(cur.lastrowid,item,item,wid))
        log_audit(c,'cycle_counts',cur.lastrowid,'CREATE',user['id'],after=body);count_id=cur.lastrowid
    return {'id':count_id,'count_number':number}
@router.get('/cycle-counts/{count_id}')
def count(count_id:int,user:User):
    row=fetch_one('SELECT * FROM cycle_counts WHERE id=?',(count_id,));
    if not row:raise HTTPException(404,'Cycle count not found')
    scoped(user,row['warehouse_id']);row['items']=fetch_all('SELECT cci.*,i.item_code,i.description FROM cycle_count_items cci JOIN items i ON i.id=cci.item_id WHERE cci.count_id=?',(count_id,));row['adjustments']=fetch_all('SELECT a.*,i.item_code,i.description FROM stock_adjustments a JOIN items i ON i.id=a.item_id WHERE a.cycle_count_id=? ORDER BY a.id',(count_id,));row['can_count']=row['status'] in ('Draft','Recount Requested') and ((user['role']=='WarehouseSupervisor' and row['warehouse_id'] in user['warehouse_ids']) or (user['role']=='Storekeeper' and row['warehouse_id'] in user['warehouse_ids'] and not supervisor_assigned(row['warehouse_id'])));row['can_review']=row['status']=='Counted' and user['role'] in ('WarehouseManager','SupplyChainManager') and row.get('submitted_by')!=user['id'] and row.get('created_by')!=user['id'];row['can_approve_adjustments']=row['status']=='Adjustment Pending SCM Approval' and user['role']=='SupplyChainManager' and not any(a['created_by']==user['id'] for a in row['adjustments']);return row
@router.put('/cycle-counts/{count_id}/submit-counts')
def submit(count_id:int,body:dict,user:dict=Depends(roles('WarehouseSupervisor','Storekeeper'))):
    row=fetch_one('SELECT * FROM cycle_counts WHERE id=?',(count_id,));
    if not row:raise HTTPException(404,'Cycle count not found')
    require_count_performer(user,row['warehouse_id']);counts=body.get('counts')
    if row['status'] not in ('Draft','Recount Requested'):raise HTTPException(409,f"Cycle count is {row['status']} and cannot accept physical counts")
    if not isinstance(counts,list) or not counts:raise HTTPException(400,'At least one count is required')
    with transaction(immediate=True) as c:
        valid={line['item_id'] for line in c.execute('SELECT item_id FROM cycle_count_items WHERE count_id=?',(count_id,))}
        if {value.get('item_id') for value in counts}!=valid:raise HTTPException(400,'Submit one counted quantity for every count line')
        for value in counts:
            qty=decimal_value(value.get('counted_qty'),'Counted quantity',nonnegative=True)
            c.execute('UPDATE cycle_count_items SET counted_qty=?,variance=?-system_qty,count_note=? WHERE count_id=? AND item_id=?',(float(qty),float(qty),value.get('count_note'),count_id,value['item_id']))
        c.execute("UPDATE cycle_counts SET status='Counted',submitted_by=?,submitted_at=datetime('now') WHERE id=?",(user['id'],count_id))
        log_audit(c,'cycle_counts',count_id,'UPDATE',user['id'],row,{'status':'Counted','workflow_action':'PHYSICAL_COUNT_SUBMITTED','counts':counts})
    return {'success':True}

@router.put('/cycle-counts/{count_id}/approve')
def approve(count_id:int,user:dict=Depends(roles('WarehouseManager','SupplyChainManager'))):
    row=fetch_one('SELECT * FROM cycle_counts WHERE id=?',(count_id,));
    if not row:raise HTTPException(404,'Not found')
    require_count_reviewer(user,row['warehouse_id'])
    if row['status']!='Counted':raise HTTPException(409,f"Cycle count is {row['status']} and cannot be approved")
    if not allows_self_approval(user) and (row.get('submitted_by')==user['id'] or row.get('created_by')==user['id']):raise HTTPException(403,'Segregation of duties: the count creator/performer cannot approve the same cycle count')
    with transaction(immediate=True) as c:
        if count_variances(c,count_id):raise HTTPException(409,'Cycle count has variances. Create adjustment proposals before approval')
        c.execute("UPDATE cycle_counts SET status='Approved',reviewed_by=?,reviewed_at=datetime('now'),review_comments=? WHERE id=?",(user['id'],None,count_id));c.execute("INSERT INTO approval_log(document_type,document_id,decision,decision_by,decision_date,event_type)VALUES('CYCLECOUNT',?,'Approved',?,datetime('now'),'NO_VARIANCE_APPROVED')",(count_id,user['id']));log_audit(c,'cycle_counts',count_id,'APPROVE',user['id'],row,{'status':'Approved','workflow_action':'NO_VARIANCE_APPROVAL','self_approved':user['id'] in (row.get('created_by'),row.get('submitted_by'))})
    return {'success':True}

@router.put('/cycle-counts/{count_id}/decision')
def decision(count_id:int,body:dict,user:dict=Depends(roles('WarehouseManager','SupplyChainManager'))):
    action=str(body.get('action')or'').strip()
    if action not in ('Reject','Request Recount'):raise HTTPException(400,'Select Reject or Request Recount')
    reason=str(body.get('reason')or'').strip()
    if len(reason)<5:raise HTTPException(400,'A review reason is required')
    row=fetch_one('SELECT * FROM cycle_counts WHERE id=?',(count_id,))
    if not row:raise HTTPException(404,'Cycle count not found')
    require_count_reviewer(user,row['warehouse_id'])
    status='Rejected' if action=='Reject' else 'Recount Requested'
    with transaction(immediate=True) as c:
        c.execute('UPDATE cycle_counts SET status=?,reviewed_by=?,reviewed_at=datetime(\'now\'),review_comments=? WHERE id=?',(status,user['id'],reason,count_id))
        c.execute("INSERT INTO approval_log(document_type,document_id,decision,decision_by,decision_date,event_type)VALUES('CYCLECOUNT',?,?,?,datetime('now'),?)",(count_id,status,user['id'],action.upper().replace(' ','_')))
        log_audit(c,'cycle_counts',count_id,'UPDATE',user['id'],row,{'status':status,'reason':reason,'workflow_action':action.upper().replace(' ','_')})
    return {'success':True,'status':status}

@router.post('/cycle-counts/{count_id}/adjustments',status_code=201)
def propose_adjustments(count_id:int,body:dict,user:dict=Depends(roles('WarehouseManager','SupplyChainManager'))):
    reason=str(body.get('reason')or'').strip();remarks=str(body.get('comments')or'').strip()
    if not reason or len(remarks)<10:raise HTTPException(400,'Adjustment reason and detailed comments are required')
    row=fetch_one('SELECT * FROM cycle_counts WHERE id=?',(count_id,))
    if not row:raise HTTPException(404,'Cycle count not found')
    require_count_reviewer(user,row['warehouse_id'])
    if row['status']!='Counted':raise HTTPException(409,f"Cycle count is {row['status']} and cannot create adjustments")
    with transaction(immediate=True) as c:
        variances=count_variances(c,count_id)
        if not variances:raise HTTPException(400,'No variance exists for adjustment')
        created=[]
        for line in variances:
            if c.execute('SELECT 1 FROM stock_adjustments WHERE cycle_count_item_id=? AND status IN (\'Pending\',\'Approved\')',(line['id'],)).fetchone():continue
            location_id=adjustment_location(c,row['warehouse_id'],line['item_id'])
            item=c.execute('SELECT standard_cost FROM items WHERE id=?',(line['item_id'],)).fetchone() or {'standard_cost':0}
            before=decimal_value(line['system_qty']);change=decimal_value(line['variance']);after=decimal_value(line['counted_qty'])
            unit_cost=decimal_value(item['standard_cost'] or 0);impact=money(abs(change)*unit_cost);num='ADJ-'+row['count_number']+'-'+str(line['id'])
            cur=c.execute("""INSERT INTO stock_adjustments(adjustment_number,item_id,warehouse_id,location_id,quantity_change,reason,status,created_by,quantity_before,quantity_after,unit_cost,total_value_impact,detailed_remarks,attachment_required,authority_reference,approval_method,cycle_count_id,cycle_count_item_id)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,0,'CYCLE_COUNT_VARIANCE','PENDING_SCM_APPROVAL',?,?)""",(num,line['item_id'],row['warehouse_id'],location_id,float(change),reason,'Pending',user['id'],float(before),float(after),float(unit_cost),float(impact),remarks,count_id,line['id']));aid=cur.lastrowid
            c.execute('UPDATE cycle_count_items SET adjustment_id=? WHERE id=?',(aid,line['id']))
            c.execute("""INSERT INTO approval_log(document_type,document_id,document_number,required_role,requested_by,decision,approval_value,approval_currency,approver_role,approval_method,authority_reference,event_type)
              VALUES('ADJUSTMENT',?,?,'SupplyChainManager',?,'Pending',? ,?,'SupplyChainManager','PENDING_SCM_APPROVAL','CYCLE_COUNT_VARIANCE','CYCLE_COUNT_ADJUSTMENT_PROPOSED')""",(aid,num,user['id'],float(impact),company_base_currency()))
            log_audit(c,'stock_adjustments',aid,'CREATE',user['id'],after={'cycle_count_id':count_id,'cycle_count_item_id':line['id'],'system_qty':line['system_qty'],'counted_qty':line['counted_qty'],'variance':line['variance'],'reason':reason,'comments':remarks})
            created.append({'id':aid,'adjustment_number':num})
        c.execute("UPDATE cycle_counts SET status='Adjustment Pending SCM Approval',reviewed_by=?,reviewed_at=datetime('now'),review_comments=? WHERE id=?",(user['id'],remarks,count_id))
        log_audit(c,'cycle_counts',count_id,'UPDATE',user['id'],row,{'status':'Adjustment Pending SCM Approval','adjustments':created,'workflow_action':'CYCLE_COUNT_ADJUSTMENT_PROPOSED'})
    return {'adjustments':created,'status':'Adjustment Pending SCM Approval'}

@router.put('/cycle-counts/{count_id}/adjustments/approve')
def approve_adjustments(count_id:int,user:dict=Depends(roles('SupplyChainManager'))):
    row=fetch_one('SELECT * FROM cycle_counts WHERE id=?',(count_id,))
    if not row:raise HTTPException(404,'Cycle count not found')
    scoped(user,row['warehouse_id'])
    adjustments=fetch_all("SELECT * FROM stock_adjustments WHERE cycle_count_id=? AND status='Pending' ORDER BY id",(count_id,))
    if not adjustments:raise HTTPException(409,'No pending cycle-count adjustments are available for approval')
    if not allows_self_approval(user) and any(adjustment['created_by']==user['id'] for adjustment in adjustments):raise HTTPException(403,'Segregation of duties: the adjustment proposer cannot approve the same adjustment')
    with transaction(immediate=True) as c:
        for adjustment in adjustments:
            if adjustment['quantity_change']>0:receive(c,item_id=adjustment['item_id'],warehouse_id=adjustment['warehouse_id'],location_id=adjustment['location_id'],quantity=adjustment['quantity_change'],unit_cost=adjustment['unit_cost'] or 0,transaction_type='CYCLE_COUNT_ADJUSTMENT_IN',reference_number=adjustment['adjustment_number'],reference_table='stock_adjustments',reference_id=adjustment['id'],created_by=user['id'])
            else:consume_warehouse(c,item_id=adjustment['item_id'],warehouse_id=adjustment['warehouse_id'],quantity=-adjustment['quantity_change'],reference_number=adjustment['adjustment_number'],reference_id=adjustment['id'],created_by=user['id'])
            c.execute("UPDATE stock_adjustments SET status='Approved',approved_by=?,approved_at=datetime('now') WHERE id=?",(user['id'],adjustment['id']))
            c.execute("UPDATE approval_log SET decision='Approved',decision_by=?,decision_date=datetime('now'),approval_method='APPROVED_BY_SCM',event_type='CYCLE_COUNT_ADJUSTMENT_APPROVED' WHERE document_type='ADJUSTMENT' AND document_id=? AND decision='Pending'",(user['id'],adjustment['id']))
            log_audit(c,'stock_adjustments',adjustment['id'],'APPROVE',user['id'],adjustment,{'cycle_count_id':count_id,'workflow_action':'CYCLE_COUNT_ADJUSTMENT_APPROVED','self_approved':adjustment['created_by']==user['id']})
        c.execute("UPDATE cycle_counts SET status='Approved',reviewed_by=?,reviewed_at=datetime('now') WHERE id=?",(user['id'],count_id))
        c.execute("INSERT INTO approval_log(document_type,document_id,decision,decision_by,decision_date,event_type)VALUES('CYCLECOUNT',?,'Approved',?,datetime('now'),'CYCLE_COUNT_ADJUSTMENTS_APPROVED')",(count_id,user['id']))
        log_audit(c,'cycle_counts',count_id,'APPROVE',user['id'],row,{'status':'Approved','workflow_action':'CYCLE_COUNT_ADJUSTMENTS_APPROVED'})
    return {'success':True,'status':'Approved'}
@router.get('/cycle-counts/{count_id}/approval-history')
def history(count_id:int,user:User):return approval_history('CYCLECOUNT',count_id)
