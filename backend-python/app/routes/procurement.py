from ..approval_routing import allows_self_approval
from ..receiving import receipt_progress
from ..pr_workflow import can_manage_pr_draft, require_pr_draft_management
from ..supplier_documents import supplier_document_fields
from datetime import datetime
import json
from fastapi import APIRouter,Depends,HTTPException
from ..audit import log_audit
from ..calculations import calculate_po,decimal_value,money,uom_snapshot
from ..approval_engine import evaluate_authority
from ..three_way_match import classify,compare_component
from ..approval_routing import approval_authorized,employee_for_user,route_approver
from ..database import fetch_all,fetch_one,transaction
from ..security import User,roles
from ..delegated_authority import active_delegation,record_delegated_use
from ..rfq_workflow import source_items,save_items,save_suppliers
from ..pr_workflow import (warehouse_owned,warehouse_draft,require_pr_access,visibility_sql,pr_lines,pr_summary,
    require_eligible,refresh_pr_order_status,allocation_candidates,default_payment_terms,VALID_PO_STATUSES,plan_allocations)
from ..approval_engine import _active_limit
from ..approval_routing import active_manager,final_scm
from .inventory import approval_history
router=APIRouter(prefix='/api/procurement',tags=['procurement']);PROC=['SupplyChainManager','PurchaseManager','PurchaseOfficer'];ALL=PROC+['WarehouseManager','WarehouseSupervisor','Storekeeper']
WAREHOUSE_ROLES={'WarehouseManager','WarehouseSupervisor','Storekeeper'}
PREFIX={'PR':'PR','RFQ':'RFQ','PO':'PO','MAR':'MAR','FINPACK':'FVP','GRN':'GRN','ISSUE':'GIN','RETURN':'ERN','TRANSFER':'STN','ADJUSTMENT':'ADJ','CYCLECOUNT':'CC','BINTRANSFER':'BT'}
def number(c,kind):
    company=c.execute('SELECT financial_year FROM company ORDER BY id DESC LIMIT 1').fetchone();import re;ys=re.findall(r'\d{4}',str(company['financial_year'] if company else ''));year=ys[-1] if ys else str(datetime.now().year);row=c.execute('SELECT last_number FROM numbering_counters WHERE doc_type=? AND year=?',(kind,year)).fetchone();seq=(row['last_number'] if row else 0)+1;c.execute('INSERT INTO numbering_counters(doc_type,year,last_number)VALUES(?,?,?) ON CONFLICT(doc_type,year)DO UPDATE SET last_number=excluded.last_number',(kind,year,seq));return f'{PREFIX[kind]}-{year}-{seq:06d}'
def po_warehouse_ids(po_id):
    rows=fetch_all('''SELECT delivery_warehouse_id warehouse_id FROM purchase_orders WHERE id=? AND delivery_warehouse_id IS NOT NULL
      UNION SELECT r.delivery_warehouse_id FROM purchase_orders po JOIN rfqs r ON r.id=po.rfq_id WHERE po.id=? AND r.delivery_warehouse_id IS NOT NULL
      UNION SELECT gi.warehouse_id FROM grns g JOIN grn_items gi ON gi.grn_id=g.id WHERE g.po_id=?''',(po_id,po_id,po_id))
    return {int(row['warehouse_id']) for row in rows}
def require_po_access(user,po_id):
    po=fetch_one('SELECT id,status FROM purchase_orders WHERE id=?',(po_id,))
    if not po:raise HTTPException(404,'Purchase Order not found')
    if user['role'] in WAREHOUSE_ROLES:
        allowed={int(value)for value in user.get('warehouse_ids',[])}
        if po['status']not in('Approved','Printed','Partially Received','Closed')or not(po_warehouse_ids(po_id)&allowed):raise HTTPException(404,'Purchase Order not found')
    return po
def detail(kind,row_id,user=None):
    table,idcol,itemtable,fk={'PR':('purchase_requisitions','pr_number','pr_items','pr_id'),'PO':('purchase_orders','po_number','po_items','po_id')}[kind];row=fetch_one(f'''SELECT d.*,u.full_name created_by_name,e.signature_url created_by_signature_url
        FROM {table} d LEFT JOIN users u ON u.id=d.{'requestor_id' if kind=='PR' else 'created_by'}
        LEFT JOIN employees e ON e.id=u.employee_id WHERE d.id=?''',(row_id,));
    if not row:raise HTTPException(404,'Not found')
    if kind=='PO':
        if user:require_po_access(user,row_id)
        warehouse=fetch_one('''SELECT w.warehouse_code delivery_warehouse_code,w.name delivery_warehouse_name
          FROM purchase_orders po LEFT JOIN rfqs r ON r.id=po.rfq_id
          LEFT JOIN warehouses w ON w.id=COALESCE(po.delivery_warehouse_id,r.delivery_warehouse_id)
          WHERE po.id=?''',(row_id,)) or {}
        row.update(warehouse)
        row.update(supplier_document_fields(row.get('supplier_id')))
        row['items']=fetch_all('''SELECT x.*,i.item_code,i.description,i.uom,i.purchase_uom,i.issue_uom,
          COALESCE((SELECT SUM(gi.accepted_qty) FROM grn_items gi JOIN grns g ON g.id=gi.grn_id WHERE g.po_id=x.po_id AND gi.item_id=x.item_id),0) received_qty,
          MAX(0,x.quantity-COALESCE((SELECT SUM(gi.accepted_qty) FROM grn_items gi JOIN grns g ON g.id=gi.grn_id WHERE g.po_id=x.po_id AND gi.item_id=x.item_id),0)) outstanding_qty,
          (SELECT sl.location_id FROM stock_ledger sl WHERE sl.item_id=x.item_id AND sl.location_id IS NOT NULL ORDER BY sl.id DESC LIMIT 1) last_location_id,
          (SELECT l.code FROM stock_ledger sl JOIN locations l ON l.id=sl.location_id WHERE sl.item_id=x.item_id ORDER BY sl.id DESC LIMIT 1) last_location_code
          FROM po_items x JOIN items i ON i.id=x.item_id WHERE x.po_id=?''',(row_id,))
        progress=receipt_progress(row_id);row.update(progress)
        lookup={x['item_id']:x for x in progress['receipt_lines']}
        for line in row['items']:
            receipt=lookup[line['item_id']];line.update(received_qty=receipt['accepted_usable_quantity'],outstanding_qty=receipt['receivable_quantity'],receiving_outstanding_qty=receipt['outstanding_quantity'])
        if progress['has_receipts'] and row['status'] in ('Approved','Printed','Partially Received','Closed'):row['status']='Closed' if progress['fully_received'] else 'Partially Received'
    else:
        if user:require_pr_access(row,user)
        with transaction() as c:
            row['items']=pr_lines(c,row_id)
            row.update(pr_summary(c,row))
        for line in row['items']:
            line['order_status']='Fully Ordered' if line['remaining_quantity']<=1e-8 else 'Partially Ordered' if line['ordered_quantity']>1e-8 else 'Open'
    return row
def validate_lines(items,priced=False):
    if not isinstance(items,list) or not items:raise HTTPException(400,'At least one item required')
    if any(not isinstance(x.get('item_id'),int) or not isinstance(x.get('quantity'),(int,float)) or x['quantity']<=0 or(priced and(not isinstance(x.get('price'),(int,float))or x['price']<0)) for x in items):raise HTTPException(400,'Every line requires a valid item and positive quantity')

RFQ_TERMINAL={'Cancelled','Closed'}
def require_rfq(rfq_id,allowed=None):
    row=fetch_one('SELECT * FROM rfqs WHERE id=?',(rfq_id,))
    if not row:raise HTTPException(404,'RFQ not found')
    if allowed and row.get('workflow_status')not in allowed:raise HTTPException(409,f"RFQ is {row.get('workflow_status')} and this action is not permitted")
    return row
def nonnegative(body,key,required=False):
    value=body.get(key)
    if value in(None,'')and not required:return 0.0
    try:value=float(value)
    except(TypeError,ValueError):raise HTTPException(400,f'{key.replace("_"," ").title()} must be numeric')
    if value<0 or(required and value<=0):raise HTTPException(400,f'{key.replace("_"," ").title()} must be {"greater than zero"if required else"zero or greater"}')
    return value

@router.get('/prs')
def prs(user:User):
    base="SELECT pr.*,d.name department_name,w.warehouse_code,w.name warehouse_name,CASE WHEN pr.auto_generated=1 THEN 'Procuraflo' ELSE COALESCE(be.name,u.full_name) END requestor_name,be.employee_code requestor_employee_code,(SELECT al.decision FROM approval_log al WHERE al.document_type='PR' AND al.document_id=pr.id ORDER BY al.id DESC LIMIT 1)approval_decision,COALESCE((SELECT po_id FROM po_pr_links WHERE pr_id=pr.id LIMIT 1),(SELECT id FROM purchase_orders WHERE pr_id=pr.id LIMIT 1))converted_po_id FROM purchase_requisitions pr LEFT JOIN departments d ON d.id=pr.department_id LEFT JOIN warehouses w ON w.id=pr.trigger_warehouse_id LEFT JOIN users u ON u.id=pr.requestor_id LEFT JOIN employees be ON be.id=pr.business_requestor_employee_id"
    rows=fetch_all(base+' WHERE '+visibility_sql(user)+' ORDER BY pr.id DESC')
    with transaction() as c:
        for row in rows:
            row['warehouse_scope_ids']=([int(row['trigger_warehouse_id'])] if row.get('trigger_warehouse_id') is not None else
                [int(line['source_warehouse_id']) for line in c.execute('SELECT DISTINCT source_warehouse_id FROM pr_items WHERE pr_id=? AND source_warehouse_id IS NOT NULL',(row['id'],))])
            row.update(pr_summary(c,row));row['can_manage_draft']=can_manage_pr_draft(row,user);row['can_submit_draft']=row['can_manage_draft'] and (warehouse_owned(row) or row['requestor_id']==user['id'])
    return rows
@router.get('/eligible-prs')
def eligible_prs(user:dict=Depends(roles(*PROC))):return [row for row in prs(user) if row['eligible_for_po']]
@router.get('/prs/{pr_id}/rfq-items')
def rfq_source_items(pr_id:int,user:dict=Depends(roles(*PROC))):
    with transaction() as c:return source_items(c,pr_id,user)

@router.get('/rfq-defaults')
def rfq_defaults(user:dict=Depends(roles(*PROC))):return {'payment_terms':default_payment_terms()}
@router.get('/prs/{pr_id}')
def get_pr(pr_id:int,user:User):
    row=detail('PR',pr_id,user);business=fetch_one('SELECT e.name,e.employee_code,e.signature_url,d.name department_name FROM employees e LEFT JOIN departments d ON d.id=e.department_id WHERE e.id=?',(row.get('business_requestor_employee_id'),))or{};row['requestor_name']=business.get('name')or row.get('created_by_name');row['requestor_employee_code']=business.get('employee_code');row['requestor_signature_url']=business.get('signature_url')or row.get('created_by_signature_url');row.update(fetch_one('SELECT warehouse_code,name warehouse_name FROM warehouses WHERE id=?',(row.get('trigger_warehouse_id'),))or{});row['company']=fetch_one('SELECT * FROM company WHERE deleted_at IS NULL ORDER BY id LIMIT 1')or{};row['approvals']=approval_history('PR',pr_id);return row
def _pr_warehouse(body,user):
    wid=body.get('warehouse_id') or body.get('trigger_warehouse_id')
    if not wid:
        available=user.get('warehouse_ids',[]) if user['role'] in WAREHOUSE_ROLES else [r['id'] for r in fetch_all('SELECT id FROM warehouses WHERE deleted_at IS NULL')]
        if len(available)==1:wid=available[0]
    if not isinstance(wid,int) or not fetch_one('SELECT id FROM warehouses WHERE id=? AND deleted_at IS NULL',(wid,)):raise HTTPException(400,'Select an originating/delivery warehouse')
    if user['role'] in WAREHOUSE_ROLES and wid not in user.get('warehouse_ids',[]):raise HTTPException(403,'Warehouse is outside your authorized scope')
    return wid


def _queue_pr(c,row,user):
    value=float(c.execute('SELECT COALESCE(SUM(COALESCE(x.base_quantity,x.quantity)*COALESCE(i.standard_cost,0)),0) v FROM pr_items x JOIN items i ON i.id=x.item_id WHERE x.pr_id=?',(row['id'],)).fetchone()['v'])
    requester_id=user['id'] if row['auto_generated'] else row['requestor_id']
    approver=None;current=employee_for_user(user);visited=set()
    while current and current['id'] not in visited:
        visited.add(current['id']);current=active_manager(current['id'])
        if current and current['user_role'] in PROC and current['user_id']!=requester_id:
            limit,_=_active_limit(current,'PR')
            if float(limit)>=value:approver=current;break
    if not approver:
        candidates=fetch_all("SELECT e.*,u.id user_id,u.role user_role FROM employees e JOIN users u ON u.employee_id=e.id WHERE u.role IN('PurchaseManager','SupplyChainManager') AND u.is_active=1 AND u.deleted_at IS NULL AND e.status='Active' AND e.deleted_at IS NULL AND e.system_access_yn=1 AND u.id<>? ORDER BY CASE u.role WHEN 'PurchaseManager' THEN 0 ELSE 1 END,e.id",(requester_id,))
        approver=next((e for e in candidates if e['user_role']=='SupplyChainManager' or float(_active_limit(e,'PR')[0])>=value),None)
    currency=(fetch_one("SELECT COALESCE(base_currency,currency,'SAR') currency FROM company WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 1") or {}).get('currency') or 'SAR'
    c.execute("""INSERT INTO approval_log(document_type,document_id,document_number,required_role,requested_by,decision,approval_value,approval_currency,approver_employee_id,approval_method,event_type)
      VALUES('PR',?,?,?,?,'Pending',?,?,?,'PROCUREMENT_REVIEW_REQUIRED',?)""",(row['id'],row['pr_number'],approver['user_role'] if approver else 'SupplyChainManager',user['id'],value,currency,approver['id'] if approver else None,'WAREHOUSE_SUBMISSION' if warehouse_owned(row) else 'PROCUREMENT_SUBMISSION'))


@router.post('/prs',status_code=201)
def create_pr(body:dict,user:User):
    validate_lines(body.get('items'));wid=_pr_warehouse(body,user)
    employee=fetch_one("SELECT id,department_id FROM employees WHERE id=? AND status='Active' AND deleted_at IS NULL",(body.get('requestor_employee_id'),))
    if not employee:raise HTTPException(400,'Select a valid active requesting employee')
    dept=body.get('department_id') or employee['department_id']
    if not isinstance(dept,int):raise HTTPException(400,'A valid department is required')
    source='WAREHOUSE_MANUAL' if user['role'] in WAREHOUSE_ROLES else 'PROCUREMENT_MANUAL' if user['role'] in PROC else 'EMPLOYEE_MANUAL'
    with transaction(immediate=True) as c:
        num=number(c,'PR');pid=c.execute("INSERT INTO purchase_requisitions(pr_number,requestor_id,business_requestor_employee_id,department_id,status,pr_source,trigger_warehouse_id)VALUES(?,?,?,?,'Draft',?,?)",(num,user['id'],employee['id'],dept,source,wid)).lastrowid
        for line in body['items']:
            item=c.execute('SELECT * FROM items WHERE id=? AND deleted_at IS NULL AND active_yn=1',(line['item_id'],)).fetchone()
            if not item:raise HTTPException(400,'Every PR line requires an active item')
            snap=uom_snapshot(dict(item),line['quantity'],line.get('transaction_uom'),purpose='purchase')
            c.execute("""INSERT INTO pr_items(pr_id,item_id,quantity,warehouse_requested_quantity,required_date,reason,transaction_quantity,transaction_uom,conversion_factor_used,base_quantity,base_uom,source_warehouse_id)VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",(pid,line['item_id'],line['quantity'],line['quantity'],line.get('required_date'),line.get('reason'),float(snap['transaction_quantity']),snap['transaction_uom'],float(snap['conversion_factor_used']),float(snap['base_quantity']),snap['base_uom'],wid))
        log_audit(c,'purchase_requisitions',pid,'CREATE',user['id'],after={**body,'status':'Draft','pr_source':source,'warehouse_id':wid,'approval_method':'PROCUREMENT_REVIEW_REQUIRED'})
    return {'id':pid,'pr_number':num,'status':'Draft','approval_method':'PROCUREMENT_REVIEW_REQUIRED'}


@router.put('/prs/{pr_id}')
def edit_pr(pr_id:int,body:dict,user:User):
    items=body.get('items')
    with transaction(immediate=True) as c:
        raw=c.execute('SELECT * FROM purchase_requisitions WHERE id=?',(pr_id,)).fetchone();row=require_pr_access(dict(raw) if raw else None,user)
        if not isinstance(items,list) or not items:raise HTTPException(400,'At least one item required')
        if row['status']!='Draft':raise HTTPException(409,'Submitted quantities are locked; Procurement must use the quantity review operation')
        require_pr_draft_management(row,user)
        originals={x['id']:dict(x) for x in c.execute('SELECT * FROM pr_items WHERE pr_id=?',(pr_id,))}
        if any(not isinstance(x.get('item_id'),int) or not isinstance(x.get('quantity'),(int,float)) or x['quantity']<=0 for x in items):raise HTTPException(400,'Every line requires a valid item and positive quantity')
        employee_id=body.get('requestor_employee_id') or row['business_requestor_employee_id']
        if not c.execute("SELECT id FROM employees WHERE id=? AND status='Active' AND deleted_at IS NULL",(employee_id,)).fetchone():raise HTTPException(400,'Select a valid active requesting employee')
        c.execute('UPDATE purchase_requisitions SET department_id=?,business_requestor_employee_id=? WHERE id=?',(body.get('department_id') or row['department_id'],employee_id,pr_id))
        c.execute('DELETE FROM pr_items WHERE pr_id=?',(pr_id,))
        for line in items:
            item=c.execute('SELECT * FROM items WHERE id=? AND deleted_at IS NULL AND active_yn=1',(line['item_id'],)).fetchone()
            if not item:raise HTTPException(400,'Every PR line requires an active item')
            snap=uom_snapshot(dict(item),line['quantity'],line.get('transaction_uom'),purpose='purchase')
            previous=originals.get(line.get('id')) or next((x for x in originals.values() if x['item_id']==line['item_id']),{})
            recommended=previous.get('recommended_base_quantity')
            if recommended is None:recommended=previous.get('base_quantity') or float(snap['base_quantity'])
            variance=float(snap['base_quantity'])-float(recommended);reason=str(line.get('adjustment_reason') or '').strip()
            if previous.get('recommended_base_quantity') is not None and abs(variance)>1e-8 and not reason:raise HTTPException(400,'Adjustment reason is required when changing a system recommendation')
            if reason=='Other' and not str(line.get('adjustment_note') or '').strip():raise HTTPException(400,'Enter a note for Other adjustment reason')
            values={'pr_id':pr_id,'item_id':line['item_id'],'quantity':line['quantity'],'warehouse_requested_quantity':line['quantity'],'required_date':line.get('required_date'),'reason':line.get('reason'),'source_warehouse_id':row['trigger_warehouse_id'],**{k:float(v) if k in ('transaction_quantity','conversion_factor_used','base_quantity') else v for k,v in snap.items()},'auto_replenishment':0,'recommended_base_quantity':previous.get('recommended_base_quantity'),'quantity_variance':variance if previous.get('recommended_base_quantity') is not None else 0,'adjustment_reason':reason or None,'adjustment_note':line.get('adjustment_note'),'adjusted_by':user['id'],'adjusted_at':datetime.now().isoformat()}
            for key in ('stock_quantity_snapshot','min_stock_snapshot','target_stock_snapshot','replenishment_cycle_id'):values[key]=previous.get(key)
            keys=','.join(values);c.execute(f'INSERT INTO pr_items({keys})VALUES({",".join("?" for _ in values)})',tuple(values.values()))
        log_audit(c,'purchase_requisitions',pr_id,'UPDATE',user['id'],before={**row,'items':list(originals.values())},after=body)
    return {'success':True}


@router.post('/prs/{pr_id}/submit-to-procurement')
def submit_pr_to_procurement(pr_id:int,user:User):
    with transaction(immediate=True) as c:
        raw=c.execute('SELECT * FROM purchase_requisitions WHERE id=?',(pr_id,)).fetchone();row=require_pr_access(dict(raw) if raw else None,user)
        if row['status']!='Draft':raise HTTPException(409,'Only a draft can be submitted for Procurement review')
        require_pr_draft_management(row,user)
        if not warehouse_owned(row) and user['id']!=row['requestor_id']:raise HTTPException(403,'Only the creator may submit this draft')
        if not c.execute('SELECT 1 FROM pr_items WHERE pr_id=?',(pr_id,)).fetchone():raise HTTPException(409,'A PR requires at least one line')
        zero_without_reason=c.execute("SELECT 1 FROM pr_items WHERE pr_id=? AND COALESCE(quantity,0)<=0 AND trim(COALESCE(adjustment_reason,'')||COALESCE(adjustment_note,''))='' LIMIT 1",(pr_id,)).fetchone()
        if zero_without_reason:raise HTTPException(400,'A warehouse explanation is required for every zero-quantity PR line')
        c.execute("UPDATE purchase_requisitions SET status='Submitted',warehouse_submitted_by=?,warehouse_submitted_at=datetime('now') WHERE id=?",(user['id'],pr_id))
        _queue_pr(c,row,user)
        log_audit(c,'purchase_requisitions',pr_id,'UPDATE',user['id'],before={'status':'Draft'},after={'status':'Submitted','workflow_status':'SUBMITTED_TO_PROCUREMENT','submitted_by':user['id']})
    return {'success':True,'status':'Submitted','pr_number':row['pr_number']}


@router.put('/prs/{pr_id}/review')
def review_pr(pr_id:int,body:dict,user:dict=Depends(roles(*PROC))):
    with transaction(immediate=True) as c:
        raw=c.execute('SELECT * FROM purchase_requisitions WHERE id=?',(pr_id,)).fetchone();row=require_pr_access(dict(raw) if raw else None,user)
        if row['status']!='Submitted':raise HTTPException(409,'Only submitted PRs may be reviewed')
        lines=pr_lines(c,pr_id);changes=body.get('items')
        if not isinstance(changes,list) or {x.get('id') for x in changes}!={x['id'] for x in lines} or len(changes)!=len(lines):raise HTTPException(400,'Review every PR line exactly once')
        proposed={x['id']:x for x in changes};value=0;positive=False
        for line in lines:
            change=proposed[line['id']];qty=decimal_value(change.get('approved_quantity'))
            if not qty.is_finite() or qty<0:raise HTTPException(400,'Approved quantity must be a finite nonnegative number')
            requested=decimal_value(line['requested_quantity']);variance=qty-requested;reason=str(change.get('adjustment_reason') or '').strip()
            if variance and not reason:raise HTTPException(400,'An adjustment reason is required when approved and requested quantities differ')
            factor=decimal_value(line.get('conversion_factor_used') or 1) if decimal_value(line['quantity'])==0 else decimal_value(line.get('base_quantity') or line['quantity'])/decimal_value(line['quantity']);base=qty*factor;positive=positive or qty>0
            item=c.execute('SELECT standard_cost FROM items WHERE id=?',(line['item_id'],)).fetchone();value+=float(base)*float(item['standard_cost'] or 0)
            c.execute("UPDATE pr_items SET approved_quantity=?,approved_base_quantity=?,procurement_quantity_variance=?,procurement_adjustment_reason=?,procurement_adjusted_by=?,procurement_adjusted_at=datetime('now') WHERE id=?",(float(qty),float(base),float(variance),reason or None,user['id'],line['id']))
            log_audit(c,'pr_items',line['id'],'UPDATE',user['id'],before=line,after={'approved_quantity':float(qty),'requested_quantity':float(requested),'variance':float(variance),'adjustment_reason':reason,'workflow_action':'PROCUREMENT_REVIEW'})
        if not positive:raise HTTPException(400,'At least one approved quantity must be positive; reject the PR if nothing is required')
        c.execute("UPDATE purchase_requisitions SET reviewed_by=?,reviewed_at=datetime('now') WHERE id=?",(user['id'],pr_id))
        c.execute("UPDATE approval_log SET approval_value=? WHERE document_type='PR' AND document_id=? AND decision='Pending'",(round(value,2),pr_id))
        log_audit(c,'purchase_requisitions',pr_id,'UPDATE',user['id'],after={'workflow_action':'PROCUREMENT_REVIEW','approval_value':round(value,2)})
    return {'success':True}


@router.put('/prs/{pr_id}/status')
def pr_status(pr_id:int,body:dict,user:dict=Depends(roles(*ALL))):
    decision=body.get('status')
    with transaction(immediate=True) as c:
        raw=c.execute('SELECT * FROM purchase_requisitions WHERE id=?',(pr_id,)).fetchone();row=require_pr_access(dict(raw) if raw else None,user)
        if decision not in ('Approved','Rejected','Closed'):raise HTTPException(400,'Invalid status')
        if warehouse_draft(row) and decision in ('Rejected','Closed'):
            require_pr_draft_management(row,user)
            reason=str(body.get('reason') or 'No purchase required').strip()
            c.execute("UPDATE purchase_requisitions SET status=?,warehouse_closed_by=?,warehouse_closed_at=datetime('now'),warehouse_closure_reason=? WHERE id=?",(decision,user['id'],reason,pr_id))
            log_audit(c,'purchase_requisitions',pr_id,'REJECT',user['id'],row,{'status':decision,'reason':reason});return {'success':True,'status':decision}
        if decision=='Closed':
            if not pr_summary(c,row)['approval_valid'] or any(x['remaining_quantity']>1e-8 for x in pr_lines(c,pr_id)):raise HTTPException(409,'A PR closes only after every approved quantity is converted to valid POs')
            refresh_pr_order_status(c,pr_id,user['id']);return {'success':True,'status':'Closed'}
        delegation=active_delegation(user,'PROC_PR_PROCESS','PR',pr_id)
        if user['role'] not in PROC and not delegation:raise HTTPException(403,'Procurement approval authority is required')
        if row['status']!='Submitted':raise HTTPException(409,'Only a submitted PR may be approved or rejected')
        pending=c.execute("SELECT * FROM approval_log WHERE document_type='PR' AND document_id=? AND decision='Pending' ORDER BY id DESC LIMIT 1",(pr_id,)).fetchone()
        if not pending:raise HTTPException(409,'This PR has no pending approval decision')
        if decision=='Approved' and not row.get('reviewed_at'):raise HTTPException(409,'Complete Procurement quantity review before approval')
        requester_id=row['warehouse_submitted_by'] if row['auto_generated'] else row['requestor_id']
        if requester_id==user['id'] and not allows_self_approval(user) and not delegation:raise HTTPException(403,'PR self-approval requires explicit delegated authority')
        limit=None;authority='Delegated Authority'
        if not delegation:
            employee,limit,authority=approval_authorized(user,requester_id,float(pending['approval_value'] or 0),'PR',pending=dict(pending))
            limit=float(_active_limit(employee,'PR')[0])
            if user['role']!='SupplyChainManager' and limit<float(pending['approval_value'] or 0):raise HTTPException(403,'Reviewed PR value exceeds your current approval authority')
        c.execute("UPDATE purchase_requisitions SET status=?,approved_by=?,approved_at=CASE WHEN ?='Approved' THEN datetime('now') ELSE NULL END WHERE id=?",(decision,user['id'] if decision=='Approved' else None,decision,pr_id))
        c.execute("UPDATE approval_log SET decision=?,decision_by=?,decision_date=datetime('now'),approval_limit_used=?,approval_limit_source=? WHERE id=?",(decision,user['id'],limit,authority,pending['id']))
        delegated=record_delegated_use(c,delegation,user,'purchase_requisitions',pr_id,decision.upper()) if delegation else {}
        log_audit(c,'purchase_requisitions',pr_id,'APPROVE' if decision=='Approved' else 'REJECT',user['id'],row,{'status':decision,'authority':authority,'self_approved':requester_id==user['id'] and decision=='Approved',**delegated})
    return {'success':True,'status':decision}

@router.get('/prs/{pr_id}/approval-history')
def pr_history(pr_id:int,user:User):
    row=fetch_one('SELECT * FROM purchase_requisitions WHERE id=?',(pr_id,))
    if not row:raise HTTPException(404,'Purchase Requisition not found')
    require_pr_access(row,user)
    return approval_history('PR',pr_id)

@router.get('/rfqs')
def rfqs(_u:dict=Depends(roles(*PROC))):return fetch_all("""SELECT r.*,pr.pr_number,(SELECT COUNT(*)FROM rfq_suppliers rs WHERE rs.rfq_id=r.id)suppliers_invited,(SELECT COUNT(*)FROM supplier_quotations q WHERE q.rfq_id=r.id)quotations_received FROM rfqs r LEFT JOIN purchase_requisitions pr ON pr.id=r.pr_id ORDER BY r.id DESC""")
@router.get('/quotations')
def quotation_register(_u:dict=Depends(roles(*PROC))):return fetch_all("""SELECT q.*,r.rfq_number,s.name supplier_name,i.item_code,i.description,(q.price*q.quoted_quantity-q.discount+q.freight+q.other_charges+(q.price*q.quoted_quantity*q.tax/100.0))evaluated_cost FROM supplier_quotations q JOIN rfqs r ON r.id=q.rfq_id JOIN suppliers s ON s.id=q.supplier_id JOIN items i ON i.id=q.item_id ORDER BY q.id DESC""")
@router.get('/rfq-awards')
def award_register(_u:dict=Depends(roles(*PROC))):return fetch_all("""SELECT a.*,r.rfq_number,s.name supplier_name,i.item_code,i.description,q.quotation_number,q.price,q.currency,po.po_number FROM rfq_awards a JOIN rfqs r ON r.id=a.rfq_id JOIN suppliers s ON s.id=a.supplier_id JOIN items i ON i.id=a.item_id JOIN supplier_quotations q ON q.id=a.quotation_id LEFT JOIN purchase_orders po ON po.id=a.po_id ORDER BY a.id DESC""")
@router.get('/rfqs/{rfq_id}')
def rfq_detail(rfq_id:int,_u:dict=Depends(roles(*PROC))):
    row=fetch_one('SELECT r.*,pr.pr_number FROM rfqs r LEFT JOIN purchase_requisitions pr ON pr.id=r.pr_id WHERE r.id=?',(rfq_id,))
    if not row:raise HTTPException(404,'RFQ not found')
    row['company']=fetch_one('SELECT * FROM company WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 1') or {}
    row['delivery_warehouse_name']=(fetch_one('SELECT name FROM warehouses WHERE id=?',(row.get('delivery_warehouse_id'),)) or {}).get('name')
    row['items']=fetch_all('SELECT s.pr_item_id,s.quantity,s.transaction_uom,s.base_uom,s.conversion_factor_used,p.*,i.item_code,i.description,i.uom,i.purchase_uom,i.issue_uom FROM rfq_items s JOIN pr_items p ON p.id=s.pr_item_id JOIN items i ON i.id=s.item_id WHERE s.rfq_id=? ORDER BY s.id',(rfq_id,))
    row['suppliers']=fetch_all('SELECT rs.*,s.supplier_code,s.name,s.rating,s.contact_person,s.email,s.phone,s.address,s.country_code FROM rfq_suppliers rs JOIN suppliers s ON s.id=rs.supplier_id WHERE rs.rfq_id=?',(rfq_id,));return row
@router.post('/rfqs',status_code=201)
def create_rfq(body:dict,user:dict=Depends(roles('PurchaseOfficer','PurchaseManager','SupplyChainManager'))):
    suppliers=body.get('supplier_ids');
    if not isinstance(suppliers,list)or not suppliers:raise HTTPException(400,'Select at least one supplier')
    pr_id=body.get('pr_id');supplier_ids=list(dict.fromkeys(int(value)for value in suppliers if value))
    with transaction(immediate=True)as c:
        pr=require_eligible(c,pr_id,user)
        delivery=body.get('delivery_warehouse_id') or pr['trigger_warehouse_id']
        if pr.get('trigger_warehouse_id') and delivery!=pr['trigger_warehouse_id']:raise HTTPException(409,'RFQ delivery warehouse must match its PR')
        body={**body,'delivery_warehouse_id':delivery,'payment_terms':body['payment_terms'] if body.get('payment_terms') is not None else default_payment_terms()}
        if c.execute("SELECT 1 FROM rfqs WHERE pr_id=? AND workflow_status NOT IN('Cancelled','Closed')",(pr_id,)).fetchone():raise HTTPException(409,'An active RFQ already exists for this PR')
        valid={row['id']for row in c.execute("SELECT id FROM suppliers WHERE id IN(%s) AND deleted_at IS NULL AND active_yn=1 AND blocked_yn=0"%','.join('?'for _ in supplier_ids),supplier_ids).fetchall()}
        if valid!=set(supplier_ids):raise HTTPException(409,'Inactive, blocked, or unknown suppliers cannot be invited')
        num=number(c,'RFQ');cur=c.execute("""INSERT INTO rfqs(rfq_number,pr_id,workflow_status,issue_date,closing_date,required_delivery_date,delivery_warehouse_id,delivery_location_id,currency,payment_terms,incoterms,contact_person,notes,commercial_terms,technical_requirements,created_by)VALUES(?,?,'Draft',?,?,?,?,?,?,?,?,?,?,?,?,?)""",(num,pr_id,body.get('issue_date'),body.get('closing_date'),body.get('required_delivery_date'),body.get('delivery_warehouse_id'),None,body.get('currency'),body.get('payment_terms'),body.get('incoterms'),body.get('contact_person'),body.get('notes'),body.get('commercial_terms'),body.get('technical_requirements'),user['id']));[c.execute('INSERT INTO rfq_suppliers(rfq_id,supplier_id,contact_person,email)SELECT ?,id,contact_person,email FROM suppliers WHERE id=?',(cur.lastrowid,s))for s in supplier_ids];log_audit(c,'rfqs',cur.lastrowid,'CREATE',user['id'],after={**body,'supplier_ids':supplier_ids});rid=cur.lastrowid
        save_items(c,rid,pr_id,user,body.get('items'))
    return {'id':rid,'rfq_number':num}
@router.post('/rfqs/{rfq_id}/quotations',status_code=201)
def quote(rfq_id:int,body:dict,_u:dict=Depends(roles('PurchaseOfficer','PurchaseManager','SupplyChainManager'))):
    rfq=require_rfq(rfq_id,{'Issued','Quotations Pending','Quotations Received'})
    if rfq.get('closing_date') and str(rfq['closing_date'])<datetime.now().date().isoformat():raise HTTPException(409,'The RFQ quotation closing date has passed')
    if not fetch_one('SELECT id FROM rfq_suppliers WHERE rfq_id=? AND supplier_id=?',(rfq_id,body.get('supplier_id'))):raise HTTPException(400,'Supplier was not invited to this RFQ')
    lines=body.get('items') if isinstance(body.get('items'),list) else [body]
    if not lines:raise HTTPException(400,'Select at least one RFQ item')
    if len({line.get('item_id')for line in lines})!=len(lines):raise HTTPException(400,'Each RFQ item may appear only once in a quotation')
    if body.get('validity_date')and body.get('quotation_date')and body['validity_date']<body['quotation_date']:raise HTTPException(400,'Quotation validity date cannot precede quotation date')
    prepared=[]
    for line in lines:
        item_id=line.get('item_id')
        if not fetch_one('SELECT 1 ok FROM rfqs r JOIN pr_items pi ON pi.pr_id=r.pr_id WHERE r.id=?AND pi.item_id=?',(rfq_id,item_id)):raise HTTPException(400,'A quoted item is not included in the linked PR')
        price=nonnegative(line,'price',True);quantity=nonnegative(line,'quoted_quantity',True);freight=nonnegative(line,'freight');tax=nonnegative(line,'tax');discount=nonnegative(line,'discount');other=nonnegative(line,'other_charges')
        requested=float((fetch_one('SELECT SUM(quantity)quantity FROM rfq_items WHERE rfq_id=? AND item_id=?',(rfq_id,item_id))or{})['quantity']or 0)
        if quantity>requested+.0001:raise HTTPException(409,'Quoted quantity exceeds the RFQ requested quantity')
        if tax>100:raise HTTPException(400,'Tax percentage cannot exceed 100')
        prepared.append((line,item_id,price,quantity,freight,tax,discount,other))
    with transaction(immediate=True)as c:
        ids=[]
        for line,item_id,price,quantity,freight,tax,discount,other in prepared:
            if c.execute('SELECT 1 FROM supplier_quotations WHERE rfq_id=?AND supplier_id=?AND item_id=?',(rfq_id,body.get('supplier_id'),item_id)).fetchone():raise HTTPException(409,'A quotation already exists for this supplier and one or more selected RFQ items; record a controlled revision instead')
            values={**body,**line};values.pop('items',None)
            cur=c.execute("""INSERT INTO supplier_quotations(rfq_id,supplier_id,item_id,price,freight,tax,currency,delivery_time_days,payment_terms,quality_rating,warranty,quotation_number,quotation_date,validity_date,quoted_quantity,discount,other_charges,delivery_date,technical_compliance,commercial_compliance,country_of_origin,remarks,created_by,created_at)VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",(rfq_id,body.get('supplier_id'),item_id,price,freight,tax,body.get('currency')or(fetch_one('SELECT currency FROM company ORDER BY id DESC LIMIT 1')or{}).get('currency','SAR'),values.get('delivery_time_days'),body.get('payment_terms'),body.get('quality_rating'),body.get('warranty'),body.get('quotation_number'),body.get('quotation_date'),body.get('validity_date'),quantity,discount,other,values.get('delivery_date'),values.get('technical_compliance'),values.get('commercial_compliance'),body.get('country_of_origin'),body.get('remarks'),_u['id']));ids.append(cur.lastrowid);log_audit(c,'supplier_quotations',cur.lastrowid,'CREATE',_u['id'],after=values)
        c.execute("UPDATE rfqs SET workflow_status='Quotations Received',updated_at=datetime('now') WHERE id=?",(rfq_id,));c.execute("UPDATE rfq_suppliers SET response_status='Quotation Received',quotation_received_at=datetime('now') WHERE rfq_id=?AND supplier_id=?",(rfq_id,body.get('supplier_id')))
    return {'id':ids[0],'ids':ids,'lines_created':len(ids)}
@router.get('/rfqs/{rfq_id}/comparison')
def comparison(rfq_id:int,_u:dict=Depends(roles(*PROC))):return fetch_all("""SELECT sq.*,s.name supplier_name,s.rating supplier_score,i.item_code,i.description,pi.quantity requested_quantity,(sq.price*COALESCE(sq.quoted_quantity,pi.quantity)-sq.discount+sq.freight+sq.other_charges+(sq.price*COALESCE(sq.quoted_quantity,pi.quantity)*sq.tax/100.0))total_landed_cost,CASE WHEN sq.id=(SELECT candidate.id FROM supplier_quotations candidate JOIN rfqs cr ON cr.id=candidate.rfq_id LEFT JOIN (SELECT rfq_id,item_id,SUM(quantity) quantity FROM rfq_items GROUP BY rfq_id,item_id) cp ON cp.rfq_id=cr.id AND cp.item_id=candidate.item_id WHERE candidate.rfq_id=sq.rfq_id AND candidate.item_id=sq.item_id AND candidate.active_yn=1 ORDER BY(candidate.price*COALESCE(candidate.quoted_quantity,cp.quantity)-candidate.discount+candidate.freight+candidate.other_charges+(candidate.price*COALESCE(candidate.quoted_quantity,cp.quantity)*candidate.tax/100.0)),candidate.id LIMIT 1)THEN 1 ELSE 0 END lowest_evaluated FROM supplier_quotations sq JOIN suppliers s ON s.id=sq.supplier_id JOIN items i ON i.id=sq.item_id JOIN rfqs r ON r.id=sq.rfq_id LEFT JOIN (SELECT rfq_id,item_id,SUM(quantity) quantity FROM rfq_items GROUP BY rfq_id,item_id) pi ON pi.rfq_id=r.id AND pi.item_id=sq.item_id WHERE sq.rfq_id=?AND sq.active_yn=1 ORDER BY sq.item_id,total_landed_cost""",(rfq_id,))
@router.put('/quotations/{quote_id}/select')
def select(quote_id:int,_u:dict=Depends(roles('PurchaseOfficer','PurchaseManager','SupplyChainManager'))):
    q=fetch_one('SELECT * FROM supplier_quotations WHERE id=?',(quote_id,));
    if not q:raise HTTPException(404,'Quotation not found')
    with transaction(immediate=True)as c:c.execute('UPDATE supplier_quotations SET selected=0 WHERE rfq_id=? AND item_id=?',(q['rfq_id'],q['item_id']));c.execute('UPDATE supplier_quotations SET selected=1 WHERE id=?',(quote_id,))
    return {'success':True}

@router.put('/rfqs/{rfq_id}/issue')
def issue_rfq(rfq_id:int,body:dict,user:dict=Depends(roles('PurchaseOfficer','PurchaseManager','SupplyChainManager'))):
    row=require_rfq(rfq_id,{'Draft'})
    if not row.get('closing_date')or row['closing_date']<=datetime.now().date().isoformat():raise HTTPException(409,'Set a future quotation closing date before issue')
    if not fetch_one('SELECT 1 ok FROM rfq_suppliers WHERE rfq_id=?',(rfq_id,)):raise HTTPException(409,'Invite at least one approved supplier before issuing the RFQ')
    with transaction(immediate=True) as c:
        current=c.execute('SELECT * FROM rfqs WHERE id=?',(rfq_id,)).fetchone()
        if current['workflow_status']!='Draft':raise HTTPException(409,'Only a draft RFQ can be issued')
        require_eligible(c,row['pr_id'],user)
        balances={line['id']:line for line in pr_lines(c,row['pr_id'])}
        selected=c.execute('SELECT * FROM rfq_items WHERE rfq_id=?',(rfq_id,)).fetchall()
        if not selected:raise HTTPException(409,'Select at least one PR item before issuing the RFQ')
        for item in selected:
            source=balances.get(item['pr_item_id'])
            available=source['remaining_quantity']*float(source.get('base_quantity') or source['quantity'])/float(source['quantity']) if source else 0
            if item['quantity']*float(item['conversion_factor_used'] or 1)>available+1e-8:raise HTTPException(409,'PR remaining quantities changed; review the draft RFQ items before issue')
        c.execute("UPDATE rfqs SET workflow_status='Issued',issue_date=COALESCE(issue_date,date('now')),updated_at=datetime('now')WHERE id=?",(rfq_id,));c.execute("UPDATE rfq_suppliers SET issued_at=datetime('now'),sent_method=COALESCE(?,sent_method,'Controlled RFQ Document'),response_status='Awaiting Response' WHERE rfq_id=?",(body.get('sent_method'),rfq_id));log_audit(c,'rfqs',rfq_id,'UPDATE',user['id'],row,{**body,'workflow_action':'ISSUE'})
    return {'success':True,'status':'Issued'}

@router.put('/rfqs/{rfq_id}')
def edit_rfq(rfq_id:int,body:dict,user:dict=Depends(roles('PurchaseOfficer','PurchaseManager','SupplyChainManager'))):
    row=require_rfq(rfq_id,{'Draft'})
    allowed=['issue_date','closing_date','required_delivery_date','delivery_warehouse_id','currency','payment_terms','incoterms','contact_person','notes','commercial_terms','technical_requirements'];values={key:body.get(key)for key in allowed if key in body}
    if values.get('closing_date')and values['closing_date']<=datetime.now().date().isoformat():raise HTTPException(400,'Quotation closing date must be in the future')
    if 'delivery_warehouse_id' in values:
        origin=fetch_one('SELECT trigger_warehouse_id FROM purchase_requisitions WHERE id=?',(row['pr_id'],)) or {}
        if origin.get('trigger_warehouse_id') and values['delivery_warehouse_id']!=origin['trigger_warehouse_id']:raise HTTPException(409,'RFQ delivery warehouse must match its PR')
    if body.get('pr_id',row['pr_id'])!=row['pr_id']:raise HTTPException(409,'The source PR cannot be changed on an existing RFQ')
    if not values and 'items' not in body and 'supplier_ids' not in body:raise HTTPException(400,'No editable RFQ fields were provided')
    with transaction(immediate=True) as c:
        current=c.execute('SELECT workflow_status FROM rfqs WHERE id=?',(rfq_id,)).fetchone()
        if current['workflow_status']!='Draft':raise HTTPException(409,'Only draft RFQs may be edited')
        if 'items' in body:save_items(c,rfq_id,row['pr_id'],user,body['items'])
        if 'supplier_ids' in body:save_suppliers(c,rfq_id,body['supplier_ids'])
        if values:c.execute(f"UPDATE rfqs SET {','.join(key+'=?'for key in values)},updated_at=datetime('now')WHERE id=?",(*values.values(),rfq_id))
        log_audit(c,'rfqs',rfq_id,'UPDATE',user['id'],row,{**body,'workflow_action':'UPDATE_DRAFT'})
    return rfq_detail(rfq_id,user)

@router.put('/rfqs/{rfq_id}/cancel')
def cancel_rfq(rfq_id:int,body:dict,user:dict=Depends(roles('PurchaseManager','SupplyChainManager'))):
    row=require_rfq(rfq_id,{'Draft','Issued','Quotations Pending','Quotations Received','Under Evaluation','Awaiting Approval'})
    reason=str(body.get('reason')or'').strip()
    if not reason:raise HTTPException(400,'Cancellation reason is required')
    if fetch_one('SELECT 1 ok FROM rfq_awards WHERE rfq_id=?AND po_id IS NOT NULL',(rfq_id,)):raise HTTPException(409,'RFQ with converted purchase orders cannot be cancelled')
    with transaction(immediate=True)as c:c.execute("UPDATE rfqs SET workflow_status='Cancelled',status='Closed',notes=trim(COALESCE(notes,'')||'\nCancellation: '||?),updated_at=datetime('now')WHERE id=?",(reason,rfq_id));log_audit(c,'rfqs',rfq_id,'UPDATE',user['id'],row,{'reason':reason,'workflow_action':'CANCEL'})
    return {'success':True,'status':'Cancelled'}

@router.post('/quotations/{quote_id}/revise',status_code=201)
def revise_quote(quote_id:int,body:dict,user:dict=Depends(roles('PurchaseOfficer','PurchaseManager','SupplyChainManager'))):
    previous=fetch_one('SELECT * FROM supplier_quotations WHERE id=?AND active_yn=1',(quote_id,))
    if not previous:raise HTTPException(404,'Active quotation not found')
    require_rfq(previous['rfq_id'],{'Issued','Quotations Pending','Quotations Received','Under Evaluation'})
    if not str(body.get('revision_reason')or'').strip():raise HTTPException(400,'A quotation revision reason is required')
    merged={**previous,**body};columns=['rfq_id','supplier_id','item_id','price','freight','tax','currency','delivery_time_days','payment_terms','quality_rating','warranty','quotation_number','quotation_date','validity_date','quoted_quantity','discount','other_charges','delivery_date','technical_compliance','commercial_compliance','country_of_origin','remarks']
    for key in ('price','quoted_quantity'):merged[key]=nonnegative(merged,key,True)
    for key in ('freight','tax','discount','other_charges'):merged[key]=nonnegative(merged,key)
    if merged['tax']>100:raise HTTPException(400,'Tax percentage cannot exceed 100')
    requested=float((fetch_one('SELECT SUM(quantity)quantity FROM rfq_items WHERE rfq_id=? AND item_id=?',(previous['rfq_id'],previous['item_id']))or{})['quantity']or 0)
    if merged['quoted_quantity']>requested+.0001:raise HTTPException(409,'Quoted quantity exceeds the RFQ requested quantity')
    with transaction(immediate=True)as c:
        c.execute('UPDATE supplier_quotations SET active_yn=0 WHERE id=?',(quote_id,));cursor=c.execute(f"INSERT INTO supplier_quotations({','.join(columns)},revision_number,created_by,created_at)VALUES({','.join('?'for _ in columns)},?,?,datetime('now'))",tuple(merged.get(key)for key in columns)+(int(previous.get('revision_number')or 1)+1,user['id']));c.execute('UPDATE supplier_quotations SET superseded_by_id=? WHERE id=?',(cursor.lastrowid,quote_id));log_audit(c,'supplier_quotations',cursor.lastrowid,'UPDATE',user['id'],previous,{**body,'supersedes_id':quote_id,'workflow_action':'REVISION'});new_id=cursor.lastrowid
    return {'id':new_id,'revision_number':int(previous.get('revision_number')or 1)+1}

@router.get('/rfqs/{rfq_id}/awards')
def awards(rfq_id:int,_u:dict=Depends(roles(*PROC))):return fetch_all('SELECT a.*,s.name supplier_name,i.item_code,i.description,sq.price,sq.currency,sq.quotation_number,po.po_number FROM rfq_awards a JOIN suppliers s ON s.id=a.supplier_id JOIN items i ON i.id=a.item_id JOIN supplier_quotations sq ON sq.id=a.quotation_id LEFT JOIN purchase_orders po ON po.id=a.po_id WHERE a.rfq_id=? ORDER BY i.item_code,s.name',(rfq_id,))

@router.post('/rfqs/{rfq_id}/awards',status_code=201)
def recommend_award(rfq_id:int,body:dict,user:dict=Depends(roles('PurchaseOfficer','PurchaseManager','SupplyChainManager'))):
    require_rfq(rfq_id,{'Quotations Received','Under Evaluation','Awaiting Approval','Awarded','Partially Awarded'})
    quote=fetch_one('SELECT sq.*,r.pr_id FROM supplier_quotations sq JOIN rfqs r ON r.id=sq.rfq_id WHERE sq.id=?AND sq.rfq_id=?AND sq.active_yn=1',(body.get('quotation_id'),rfq_id))
    if not quote:raise HTTPException(404,'Active quotation not found')
    try:quantity=float(body.get('awarded_quantity'))
    except(TypeError,ValueError):raise HTTPException(400,'Awarded quantity must be numeric')
    if quantity<=0:raise HTTPException(400,'Awarded quantity must be greater than zero')
    if quantity>float(quote.get('quoted_quantity')or 0)+.0001:raise HTTPException(409,'Award quantity exceeds the supplier quoted quantity')
    reason=str(body.get('recommendation_reason')or'').strip()
    if not reason:raise HTTPException(400,'Recommendation reason is required')
    lowest=fetch_one("""SELECT sq.id FROM supplier_quotations sq JOIN rfqs r ON r.id=sq.rfq_id LEFT JOIN (SELECT rfq_id,item_id,SUM(quantity) quantity FROM rfq_items GROUP BY rfq_id,item_id) pi ON pi.rfq_id=r.id AND pi.item_id=sq.item_id WHERE sq.rfq_id=?AND sq.item_id=?AND sq.active_yn=1 ORDER BY(sq.price*COALESCE(sq.quoted_quantity,pi.quantity)-sq.discount+sq.freight+sq.other_charges+(sq.price*COALESCE(sq.quoted_quantity,pi.quantity)*sq.tax/100.0)),sq.id LIMIT 1""",(rfq_id,quote['item_id']))
    justification=str(body.get('non_lowest_justification')or'').strip()
    if lowest and lowest['id']!=quote['id']and not justification:raise HTTPException(400,'A justification is required when the recommended supplier is not the lowest evaluated bidder')
    with transaction(immediate=True)as c:
        approved_qty=float(c.execute('SELECT COALESCE(SUM(quantity),0)quantity FROM rfq_items WHERE rfq_id=?AND item_id=?',(rfq_id,quote['item_id'])).fetchone()['quantity']);already=float(c.execute("SELECT COALESCE(SUM(awarded_quantity),0)quantity FROM rfq_awards WHERE rfq_id=?AND item_id=?AND status<>'Rejected'",(rfq_id,quote['item_id'])).fetchone()['quantity'])
        if already+quantity>approved_qty+.0001:raise HTTPException(409,'Award quantity exceeds the approved PR quantity')
        quote_awarded=c.execute("SELECT COALESCE(SUM(awarded_quantity),0) qty FROM rfq_awards WHERE quotation_id=? AND status<>'Rejected'",(quote['id'],)).fetchone()['qty']
        if quote_awarded+quantity>float(quote['quoted_quantity'])+1e-8:raise HTTPException(409,'Total awards exceed the supplier quoted quantity')
        cursor=c.execute("INSERT INTO rfq_awards(rfq_id,quotation_id,supplier_id,item_id,awarded_quantity,recommendation_reason,non_lowest_justification,recommended_by)VALUES(?,?,?,?,?,?,?,?)",(rfq_id,quote['id'],quote['supplier_id'],quote['item_id'],quantity,reason,justification or None,user['id']));c.execute("UPDATE rfqs SET workflow_status='Awaiting Approval',updated_at=datetime('now')WHERE id=?",(rfq_id,));log_audit(c,'rfq_awards',cursor.lastrowid,'CREATE',user['id'],after={**body,'workflow_action':'RECOMMEND'});award_id=cursor.lastrowid
    return {'id':award_id,'status':'Awaiting Approval'}

@router.put('/rfq-awards/{award_id}/decision')
def award_decision(award_id:int,body:dict,user:dict=Depends(roles('PurchaseManager','SupplyChainManager'))):
    decision=body.get('decision');award=fetch_one('SELECT * FROM rfq_awards WHERE id=?',(award_id,))
    if not award:raise HTTPException(404,'Award recommendation not found')
    if award['status']!='Awaiting Approval':raise HTTPException(409,f"Award is already {award['status']}")
    if decision not in('Approved','Rejected'):raise HTTPException(400,'Decision must be Approved or Rejected')
    self_decision=award['recommended_by']==user['id']
    if decision=='Rejected'and not str(body.get('reason')or'').strip():raise HTTPException(400,'Rejection reason is required')
    value=float((fetch_one('SELECT a.awarded_quantity*(q.price*(1+q.tax/100.0))-q.discount+q.freight+q.other_charges value FROM rfq_awards a JOIN supplier_quotations q ON q.id=a.quotation_id WHERE a.id=?',(award_id,))or{})['value']or 0);limit=float(user.get('approval_limit')or 0)
    if decision=='Approved'and user['role']!='SupplyChainManager'and value>limit:raise HTTPException(403,f'Award value exceeds your approval limit of {limit:.2f}')
    external=bool(body.get('external_approval_reference'))
    if decision=='Approved'and self_decision:
        if not allows_self_approval(user):raise HTTPException(403,'Only the Supply Chain Manager may approve their own award recommendation')

    if decision=='Approved' and self_decision and value>limit:
        if not external or not str(body.get('external_approved_by')or'').strip() or not body.get('external_approval_date'):raise HTTPException(409,'External management approval details are required above the assigned approval limit')
        if not fetch_one("SELECT id FROM document_attachments WHERE document_type='AWARD' AND document_id=? LIMIT 1",(award_id,)):raise HTTPException(409,'Upload the external management approval against this over-limit award')
    if decision=='Approved'and value>limit and user['role']=='SupplyChainManager'and not external:raise HTTPException(409,'External management approval reference is required above the assigned approval limit')
    with transaction(immediate=True)as c:
        c.execute("UPDATE rfq_awards SET status=?,approved_by=?,approved_at=datetime('now'),rejection_reason=?,approval_limit_snapshot=?,effective_limit_source='Employee approval limit',external_approval_required=?,external_approved_by=?,external_approval_reference=?,external_approval_date=?,external_approval_notes=? WHERE id=?",(decision,user['id'],body.get('reason'),limit,int(external),body.get('external_approved_by'),body.get('external_approval_reference'),body.get('external_approval_date'),body.get('external_approval_notes'),award_id));pending=c.execute("SELECT 1 FROM rfq_awards WHERE rfq_id=?AND status='Awaiting Approval'LIMIT 1",(award['rfq_id'],)).fetchone();approved=c.execute("SELECT 1 FROM rfq_awards WHERE rfq_id=?AND status='Approved'LIMIT 1",(award['rfq_id'],)).fetchone();new_status='Awaiting Approval'if pending else('Awarded'if approved else'Under Evaluation');c.execute('UPDATE rfqs SET workflow_status=?,updated_at=datetime(\'now\')WHERE id=?',(new_status,award['rfq_id']));log_audit(c,'rfq_awards',award_id,'APPROVE' if decision=='Approved' else 'REJECT',user['id'],award,{**body,'approval_limit_snapshot':limit,'award_value':value,'self_approved':self_decision and decision=='Approved'})
    return {'success':True,'status':decision}

@router.post('/rfqs/{rfq_id}/create-purchase-orders',status_code=201)
def create_award_pos(rfq_id:int,user:dict=Depends(roles('PurchaseManager','SupplyChainManager'))):
    rfq=require_rfq(rfq_id,{'Awarded','Partially Awarded'});rows=fetch_all("SELECT a.*,sq.price,sq.tax,sq.currency,sq.discount,sq.freight,sq.other_charges,sq.delivery_date,sq.warranty,sq.payment_terms,sq.quotation_number FROM rfq_awards a JOIN supplier_quotations sq ON sq.id=a.quotation_id WHERE a.rfq_id=?AND a.status='Approved'AND a.po_id IS NULL",(rfq_id,))
    if not rfq or not rows:raise HTTPException(409,'No approved, unconverted award lines are available')
    created=[]
    with transaction(immediate=True)as c:
        require_eligible(c,rfq['pr_id'],user)
        rows=[row for row in rows if c.execute("SELECT 1 FROM rfq_awards WHERE id=? AND status='Approved' AND po_id IS NULL",(row['id'],)).fetchone()]
        if not rows:raise HTTPException(409,'These awards have already been converted')
        for supplier_id in sorted({row['supplier_id']for row in rows}):
            lines=[row for row in rows if row['supplier_id']==supplier_id];calculation=calculate_po([{**row,'quantity':row['awarded_quantity']}for row in lines]);total=float(calculation['grand_total'])
            currencies={str(line['currency'] or rfq.get('currency') or '').upper() for line in lines}
            if len(currencies)>1:raise HTTPException(409,'Award lines for one supplier must use the same currency')
            base_currency,currency,rate_row,exchange_rate,base_total=po_currency_context(total,next(iter(currencies)))
            evaluation=evaluate_authority(user,base_total,'PO')
            if not evaluation:raise HTTPException(409,'No active approval authority is available')
            external_required=evaluation.outcome=='PENDING_EXTERNAL_APPROVAL'
            approval_method='PENDING_EXTERNAL_APPROVAL' if external_required else 'PENDING_APPROVAL'
            management_ref=number(c,'MAR') if external_required else None
            num=number(c,'PO');cursor=c.execute("INSERT INTO purchase_orders(po_number,supplier_id,pr_id,rfq_id,committed_delivery_date,total_amount,status,created_by,transaction_currency,delivery_warehouse_id,exchange_rate,base_currency,base_currency_amount,external_approval_required,management_approval_request_number)VALUES(?,?,?,?,?,?,'PendingApproval',?,?,?,?,?,?,?,?)",(num,supplier_id,rfq['pr_id'],rfq_id,rfq.get('required_delivery_date'),total,user['id'],currency,rfq.get('delivery_warehouse_id'),exchange_rate,base_currency,base_total,int(external_required),management_ref));po_id=cursor.lastrowid;c.execute('INSERT OR IGNORE INTO po_pr_links(po_id,pr_id)VALUES(?,?)',(po_id,rfq['pr_id']))
            for line,financial in zip(lines,calculation['lines']):
                unit=dict(c.execute('SELECT transaction_uom,base_uom,conversion_factor_used FROM rfq_items WHERE rfq_id=? AND item_id=? ORDER BY id LIMIT 1',(rfq_id,line['item_id'])).fetchone());snapshot={**unit,'transaction_quantity':line['awarded_quantity'],'base_quantity':line['awarded_quantity']*float(unit['conversion_factor_used'] or 1)}
                c.execute('''INSERT INTO po_items(po_id,item_id,quantity,price,tax,quotation_id,discount,freight,other_charges,delivery_date,warranty,technical_specifications,
                  transaction_quantity,transaction_uom,conversion_factor_used,base_quantity,base_uom,line_amount,tax_amount,line_total)VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(po_id,line['item_id'],line['awarded_quantity'],line['price'],line['tax'],line['quotation_id'],float(financial['discount']),float(financial['freight']),float(financial['other_charges']),line['delivery_date'],line['warranty'],rfq.get('technical_requirements'),float(snapshot['transaction_quantity']),snapshot['transaction_uom'],float(snapshot['conversion_factor_used']),float(snapshot['base_quantity']),snapshot['base_uom'],float(financial['line_amount']),float(financial['tax_amount']),float(financial['line_total'])))
                for pr_id,pr_item_id,item_id,quantity in plan_allocations(c,[rfq['pr_id']],line['item_id'],float(snapshot['base_quantity']),{}):
                    c.execute('INSERT INTO po_pr_item_allocations(po_id,pr_id,pr_item_id,item_id,quantity)VALUES(?,?,?,?,?) ON CONFLICT(po_id,pr_item_id)DO UPDATE SET quantity=quantity+excluded.quantity',(po_id,pr_id,pr_item_id,item_id,quantity))
                c.execute('UPDATE rfq_awards SET po_id=?WHERE id=?',(po_id,line['id']))
            c.execute("""INSERT INTO approval_log(document_type,document_id,document_number,required_role,requested_by,decision,approval_value,approval_currency,approval_limit_used,approval_limit_source,approver_employee_id,approver_role,workflow_level,escalation_rule,approval_method,authority_reference,event_type)
              VALUES('PO',?,?,?,?,'Pending',?,?,?,?,?,?,?,?,?,?,?)""",(po_id,num,evaluation.role,user['id'],base_total,base_currency,float(evaluation.limit),'ACTIVE_EMPLOYEE_AUTHORITY',evaluation.employee_id,evaluation.role,str(evaluation.level),evaluation.rule,approval_method,evaluation.authority_reference,approval_method))
            log_audit(c,'purchase_orders',po_id,'CREATE',user['id'],after={'rfq_id':rfq_id,'supplier_id':supplier_id,'workflow_action':'CREATE_FROM_RFQ_AWARD','approval_method':approval_method,'external_approval_required':external_required,'base_currency_amount':base_total,'management_approval_request_number':management_ref})
            created.append({'id':po_id,'po_number':num,'supplier_id':supplier_id,'status':'PendingApproval','external_approval_required':external_required,'approval_method':approval_method,'management_approval_request_number':management_ref})
        refresh_pr_order_status(c,rfq['pr_id'],user['id'],created[-1]['id']);remaining=c.execute("SELECT 1 FROM (SELECT item_id,SUM(quantity) quantity FROM rfq_items WHERE rfq_id=? GROUP BY item_id) pi WHERE pi.quantity>COALESCE((SELECT SUM(a.awarded_quantity)FROM rfq_awards a WHERE a.rfq_id=?AND a.item_id=pi.item_id AND a.status='Approved'),0)+.0001 LIMIT 1",(rfq_id,rfq_id)).fetchone();new_status='Partially Awarded'if remaining else'Closed';c.execute("UPDATE rfqs SET workflow_status=?,status=CASE WHEN ?='Closed'THEN'Closed'ELSE status END,updated_at=datetime('now')WHERE id=?",(new_status,new_status,rfq_id));log_audit(c,'rfqs',rfq_id,'UPDATE',user['id'],after={'purchase_orders':created,'workflow_status':new_status,'workflow_action':'CONVERT_TO_PO'})
    return {'purchase_orders':created}

@router.get('/rfqs/{rfq_id}/traceability')
def rfq_traceability(rfq_id:int,_u:dict=Depends(roles(*PROC))):
    rfq=fetch_one('SELECT r.id,r.rfq_number,r.workflow_status,pr.id pr_id,pr.pr_number FROM rfqs r LEFT JOIN purchase_requisitions pr ON pr.id=r.pr_id WHERE r.id=?',(rfq_id,))
    if not rfq:raise HTTPException(404,'RFQ not found')
    rfq['purchase_orders']=fetch_all('SELECT id,po_number,status FROM purchase_orders WHERE rfq_id=?',(rfq_id,));rfq['grns']=fetch_all('SELECT g.id,g.grn_number,g.po_id FROM grns g JOIN purchase_orders po ON po.id=g.po_id WHERE po.rfq_id=?',(rfq_id,));rfq['invoices']=fetch_all('SELECT inv.id,inv.invoice_number,inv.po_id,inv.match_status FROM invoices inv JOIN purchase_orders po ON po.id=inv.po_id WHERE po.rfq_id=?',(rfq_id,));return rfq

@router.get('/rfqs/{rfq_id}/audit')
def rfq_audit(rfq_id:int,_u:dict=Depends(roles(*PROC))):
    quote_ids=[row['id']for row in fetch_all('SELECT id FROM supplier_quotations WHERE rfq_id=?',(rfq_id,))];award_ids=[row['id']for row in fetch_all('SELECT id FROM rfq_awards WHERE rfq_id=?',(rfq_id,))];clauses=['(a.table_name=\'rfqs\'AND a.record_id=?)'];params=[rfq_id]
    if quote_ids:clauses.append("(a.table_name='supplier_quotations'AND a.record_id IN(%s))"%','.join('?'for _ in quote_ids));params.extend(quote_ids)
    if award_ids:clauses.append("(a.table_name='rfq_awards'AND a.record_id IN(%s))"%','.join('?'for _ in award_ids));params.extend(award_ids)
    return fetch_all(f"SELECT a.*,a.changed_at created_at,u.full_name changed_by_name FROM audit_log a LEFT JOIN users u ON u.id=a.changed_by WHERE {' OR '.join(clauses)} ORDER BY a.id DESC",params)

@router.get('/pos')
def pos(user:dict=Depends(roles(*ALL))):
    sql="SELECT po.*,s.name supplier_name,w.warehouse_code delivery_warehouse_code,w.name delivery_warehouse_name,COALESCE(po.delivery_warehouse_id,r.delivery_warehouse_id) intended_delivery_warehouse_id,(SELECT COUNT(*) FROM grns g WHERE g.po_id=po.id)grn_count FROM purchase_orders po JOIN suppliers s ON s.id=po.supplier_id LEFT JOIN rfqs r ON r.id=po.rfq_id LEFT JOIN warehouses w ON w.id=COALESCE(po.delivery_warehouse_id,r.delivery_warehouse_id)"
    params=[]
    if user['role'] in WAREHOUSE_ROLES:
        ids=[int(value)for value in user.get('warehouse_ids',[])]
        marks=','.join('?'for _ in ids)or'NULL'
        sql+=f" WHERE po.status IN('Approved','Printed','Partially Received','Closed') AND (po.delivery_warehouse_id IN({marks}) OR EXISTS(SELECT 1 FROM rfqs r WHERE r.id=po.rfq_id AND r.delivery_warehouse_id IN({marks})) OR EXISTS(SELECT 1 FROM grns g JOIN grn_items gi ON gi.grn_id=g.id WHERE g.po_id=po.id AND gi.warehouse_id IN({marks})))"
        params=ids+ids+ids
    rows=fetch_all(sql+' ORDER BY po.id DESC',params)
    for row in rows:
        progress=receipt_progress(row['id']);row.update({k:progress[k] for k in ('receiving_status','fully_received','has_receipts')})
        if progress['has_receipts'] and row['status'] in ('Approved','Printed','Partially Received','Closed'):row['status']='Closed' if progress['fully_received'] else 'Partially Received'
    return rows
@router.get('/pos/{po_id}')
def get_po(po_id:int,user:dict=Depends(roles(*ALL))):return detail('PO',po_id,user)
def po_currency_context(total,currency=None):
    company=fetch_one("SELECT COALESCE(base_currency,currency,'SAR') base_currency FROM company WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 1")or{'base_currency':'SAR'};base_currency=company['base_currency'];transaction_currency=str(currency or base_currency).upper()
    rate_row={'rate':1,'source':'System parity rate'}if transaction_currency==base_currency else fetch_one("SELECT rate,source,effective_date,expiry_date FROM exchange_rates WHERE from_currency=? AND to_currency=? AND active_yn=1 AND effective_date<=date('now') AND(expiry_date IS NULL OR expiry_date>=date('now')) ORDER BY effective_date DESC,id DESC LIMIT 1",(transaction_currency,base_currency))
    if not rate_row:raise HTTPException(409,f'Synchronize an authenticated {transaction_currency} to {base_currency} exchange rate before creating this purchase order')
    exchange_rate=float(rate_row['rate']);base_total=float(money(decimal_value(total)*decimal_value(exchange_rate)))
    return base_currency,transaction_currency,rate_row,exchange_rate,base_total

@router.post('/pos',status_code=201)
def create_po(body:dict,user:dict=Depends(roles(*PROC))):
    items=body.get('items');validate_lines(items,True);calculation=calculate_po(items);total=float(calculation['grand_total']);prepared=[]
    for line,financial in zip(items,calculation['lines']):
        item=fetch_one('SELECT * FROM items WHERE id=? AND deleted_at IS NULL',(line['item_id'],))
        if not item:raise HTTPException(400,'Every PO line requires an active item')
        prepared.append((line,financial,uom_snapshot(item,line['quantity'],line.get('transaction_uom'),purpose='purchase')))
    delivery_warehouse_id=body.get('delivery_warehouse_id')
    if delivery_warehouse_id is None:
        active_warehouses=fetch_all('SELECT id FROM warehouses WHERE deleted_at IS NULL ORDER BY id LIMIT 2')
        if len(active_warehouses)==1:delivery_warehouse_id=active_warehouses[0]['id']
    if not isinstance(delivery_warehouse_id,int)or not fetch_one('SELECT id FROM warehouses WHERE id=? AND deleted_at IS NULL',(delivery_warehouse_id,)):raise HTTPException(400,'Select a valid delivery warehouse')
    pr_ids=list(dict.fromkeys(int(value) for value in(body.get('pr_ids')or([body['pr_id']] if body.get('pr_id') else []))if value))
    base_currency,transaction_currency,rate_row,exchange_rate,base_total=po_currency_context(total,body.get('transaction_currency'));requester=employee_for_user(user)
    if not requester:raise HTTPException(403,'An active Procurement employee record is required')
    evaluation=evaluate_authority(user,base_total,'PO')
    if not evaluation:raise HTTPException(409,'No active approval authority is available')
    with transaction(immediate=True)as c:
        for pr_id in pr_ids:
            pr=require_eligible(c,pr_id,user)
            if pr.get('trigger_warehouse_id') and pr['trigger_warehouse_id']!=delivery_warehouse_id:raise HTTPException(409,'PO delivery warehouse must match every linked PR')
        allocations=[];reserved={}
        for line,financial,snapshot in prepared:
            if pr_ids:allocations.extend(plan_allocations(c,pr_ids,line['item_id'],float(snapshot['base_quantity']),reserved))
        auto=evaluation.outcome=='AUTO_APPROVED_WITHIN_AUTHORITY';external_required=evaluation.outcome=='PENDING_EXTERNAL_APPROVAL';management_ref=number(c,'MAR')if external_required else None
        num=number(c,'PO');cur=c.execute("INSERT INTO purchase_orders(po_number,supplier_id,rfq_id,committed_delivery_date,total_amount,transaction_currency,exchange_rate,base_currency,base_currency_amount,status,created_by,external_approval_required,management_approval_request_number,delivery_warehouse_id)VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(num,body.get('supplier_id'),body.get('rfq_id'),body.get('committed_delivery_date'),total,transaction_currency,exchange_rate,base_currency,base_total,'Approved'if auto else'PendingApproval',user['id'],int(external_required),management_ref,delivery_warehouse_id));pid=cur.lastrowid
        for line,financial,snapshot in prepared:c.execute('''INSERT INTO po_items(po_id,item_id,quantity,price,tax,discount,freight,other_charges,transaction_quantity,transaction_uom,conversion_factor_used,base_quantity,base_uom,line_amount,tax_amount,line_total)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(pid,line['item_id'],line['quantity'],line['price'],line.get('tax',0),float(financial['discount']),float(financial['freight']),float(financial['other_charges']),float(snapshot['transaction_quantity']),snapshot['transaction_uom'],float(snapshot['conversion_factor_used']),float(snapshot['base_quantity']),snapshot['base_uom'],float(financial['line_amount']),float(financial['tax_amount']),float(financial['line_total'])))
        for pr_id in pr_ids:c.execute('INSERT INTO po_pr_links(po_id,pr_id)VALUES(?,?)',(pid,pr_id))
        for pr_id,pr_item_id,item_id,quantity in allocations:c.execute('INSERT INTO po_pr_item_allocations(po_id,pr_id,pr_item_id,item_id,quantity)VALUES(?,?,?,?,?) ON CONFLICT(po_id,pr_item_id)DO UPDATE SET quantity=quantity+excluded.quantity',(pid,pr_id,pr_item_id,item_id,quantity))
        for pr_id in pr_ids:refresh_pr_order_status(c,pr_id,user['id'],pid)
        c.execute("""INSERT INTO approval_log(document_type,document_id,document_number,required_role,requested_by,decision,decision_by,decision_date,approval_value,approval_currency,approval_limit_used,approval_limit_source,approver_employee_id,approver_role,workflow_level,escalation_rule,approval_method,authority_reference,event_type)
          VALUES('PO',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(pid,num,evaluation.role,user['id'],'Approved'if auto else'Pending',user['id']if auto else None,datetime.now().isoformat()if auto else None,base_total,base_currency,float(evaluation.limit),'ACTIVE_EMPLOYEE_AUTHORITY',evaluation.employee_id,evaluation.role,str(evaluation.level),evaluation.rule,evaluation.outcome,evaluation.authority_reference,evaluation.outcome));log_audit(c,'purchase_orders',pid,'CREATE',user['id'],after={**body,'transaction_currency':transaction_currency,'exchange_rate':exchange_rate,'base_currency':base_currency,'base_currency_amount':base_total,'exchange_rate_source':rate_row.get('source'),'approval_method':evaluation.outcome,'routed_approver_employee_id':evaluation.employee_id,'external_approval_required':external_required})
    return {'id':pid,'po_number':num,'status':'Approved'if auto else'PendingApproval','approval_method':evaluation.outcome,'total_amount':total,'transaction_currency':transaction_currency,'exchange_rate':exchange_rate,'base_currency':base_currency,'base_currency_amount':base_total,'exchange_rate_source':rate_row.get('source')}
def revise_po(po_id,body,user,amend=False):
    po=fetch_one('SELECT * FROM purchase_orders WHERE id=?',(po_id,));
    if not po:raise HTTPException(404,'PO not found')
    if amend and(not str(body.get('revision_reason')or'').strip()or po['status']not in['Approved','Printed']):raise HTTPException(409,'Only an approved, unreceived PO can enter controlled amendment with a revision reason')
    if not amend and po['status']!='PendingApproval':raise HTTPException(409,f"PO is {po['status']} and cannot be edited")
    items=body.get('items');validate_lines(items,True);calculation=calculate_po(items);total=float(calculation['grand_total']);prepared=[]
    for line,financial in zip(items,calculation['lines']):
        item=fetch_one('SELECT * FROM items WHERE id=? AND deleted_at IS NULL',(line['item_id'],))
        if not item:raise HTTPException(400,'Every PO line requires an active item')
        prepared.append((line,financial,uom_snapshot(item,line['quantity'],line.get('transaction_uom'),purpose='purchase')))
    delivery_warehouse_id=body.get('delivery_warehouse_id',po.get('delivery_warehouse_id'))
    if delivery_warehouse_id is None:
        active_warehouses=fetch_all('SELECT id FROM warehouses WHERE deleted_at IS NULL ORDER BY id LIMIT 2')
        if len(active_warehouses)==1:delivery_warehouse_id=active_warehouses[0]['id']
    if not isinstance(delivery_warehouse_id,int)or not fetch_one('SELECT id FROM warehouses WHERE id=? AND deleted_at IS NULL',(delivery_warehouse_id,)):raise HTTPException(400,'Select a valid delivery warehouse')
    base_currency=po.get('base_currency')or(fetch_one("SELECT COALESCE(base_currency,currency,'SAR') value FROM company WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 1")or{'value':'SAR'})['value']
    transaction_currency=str(body.get('transaction_currency')or po.get('transaction_currency')or base_currency).upper()
    exchange_rate=decimal_value(body.get('exchange_rate')if body.get('exchange_rate')is not None else po.get('exchange_rate')or 1)
    if exchange_rate<=0:raise HTTPException(400,'Exchange rate must be greater than zero')
    base_total=float(money(calculation['grand_total']*exchange_rate));evaluation=evaluate_authority(user,base_total,'PO')
    if not evaluation:raise HTTPException(409,'No active approval authority is available')
    auto=evaluation.outcome=='AUTO_APPROVED_WITHIN_AUTHORITY';new_status='Approved'if auto else'PendingApproval'
    pr_ids=[row['pr_id']for row in fetch_all('SELECT pr_id FROM po_pr_links WHERE po_id=?',(po_id,))]
    with transaction(immediate=True)as c:
        prior=c.execute("SELECT id FROM approval_log WHERE document_type='PO' AND document_id=? AND decision='Approved' ORDER BY id DESC LIMIT 1",(po_id,)).fetchone()
        if amend:
            c.execute("INSERT INTO document_revisions(document_type,document_id,revision_number,changed_by,change_reason,previous_values,new_values)VALUES('PO',?,COALESCE((SELECT MAX(revision_number)+1 FROM document_revisions WHERE document_type='PO'AND document_id=?),1),?,?,?,?)",(po_id,po_id,user['id'],body['revision_reason'],str(po),str(body)))
            c.execute("""INSERT INTO approval_log(document_type,document_id,document_number,required_role,requested_by,decision,approval_value,approval_currency,approval_method,event_type,supersedes_approval_id,comments)
              VALUES('PO',?,?,?,?,'Approved',?,?,?,?,?,?)""",(po_id,po['po_number'],evaluation.role,user['id'],float(po.get('base_currency_amount')or po.get('total_amount')or 0),base_currency,'APPROVAL_INVALIDATED_BY_AMENDMENT','APPROVAL_INVALIDATED_BY_AMENDMENT',prior['id']if prior else None,body['revision_reason']))
        c.execute("UPDATE purchase_orders SET supplier_id=?,committed_delivery_date=?,total_amount=?,transaction_currency=?,exchange_rate=?,base_currency=?,base_currency_amount=?,delivery_warehouse_id=?,status=?,external_approval_required=? WHERE id=?",(body.get('supplier_id'),body.get('committed_delivery_date'),total,transaction_currency,float(exchange_rate),base_currency,base_total,delivery_warehouse_id,new_status,int(evaluation.outcome=='PENDING_EXTERNAL_APPROVAL'),po_id));c.execute('DELETE FROM po_items WHERE po_id=?',(po_id,));c.execute('DELETE FROM po_pr_item_allocations WHERE po_id=?',(po_id,))
        for x,financial,snapshot in prepared:c.execute('''INSERT INTO po_items(po_id,item_id,quantity,price,tax,discount,freight,other_charges,transaction_quantity,transaction_uom,conversion_factor_used,base_quantity,base_uom,line_amount,tax_amount,line_total)VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(po_id,x['item_id'],x['quantity'],x['price'],x.get('tax',0),float(financial['discount']),float(financial['freight']),float(financial['other_charges']),float(snapshot['transaction_quantity']),snapshot['transaction_uom'],float(snapshot['conversion_factor_used']),float(snapshot['base_quantity']),snapshot['base_uom'],float(financial['line_amount']),float(financial['tax_amount']),float(financial['line_total'])))
        reserved={}
        for pr_id in pr_ids:
            pr=require_eligible(c,pr_id,user)
            if pr.get('trigger_warehouse_id') and pr['trigger_warehouse_id']!=delivery_warehouse_id:raise HTTPException(409,'PO delivery warehouse must match every linked PR')
        for line,financial,snapshot in prepared:
            if pr_ids:
                for pr_id,pr_item_id,item_id,quantity in plan_allocations(c,pr_ids,line['item_id'],float(snapshot['base_quantity']),{}):
                    c.execute('INSERT INTO po_pr_item_allocations(po_id,pr_id,pr_item_id,item_id,quantity)VALUES(?,?,?,?,?) ON CONFLICT(po_id,pr_item_id)DO UPDATE SET quantity=quantity+excluded.quantity',(po_id,pr_id,pr_item_id,item_id,quantity))
        for pr_id in pr_ids:refresh_pr_order_status(c,pr_id,user['id'],po_id)
        c.execute("""INSERT INTO approval_log(document_type,document_id,document_number,required_role,requested_by,decision,decision_by,decision_date,approval_value,approval_currency,approval_limit_used,approval_limit_source,approver_employee_id,approver_role,workflow_level,escalation_rule,approval_method,authority_reference,event_type,supersedes_approval_id)
          VALUES('PO',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(po_id,po['po_number'],evaluation.role,user['id'],'Approved'if auto else'Pending',user['id']if auto else None,datetime.now().isoformat()if auto else None,base_total,base_currency,float(evaluation.limit),'ACTIVE_EMPLOYEE_AUTHORITY',evaluation.employee_id,evaluation.role,str(evaluation.level),evaluation.rule,'REAPPROVED_AFTER_AMENDMENT'if amend and auto else evaluation.outcome,evaluation.authority_reference,'REAPPROVED_AFTER_AMENDMENT'if amend and auto else evaluation.outcome,prior['id']if prior else None))
        log_audit(c,'purchase_orders',po_id,'UPDATE',user['id'],po,{**body,'approval_method':evaluation.outcome,'base_currency_amount':base_total})
    return {'success':True,'status':new_status,'approval_method':evaluation.outcome,'total_amount':total,'base_currency_amount':base_total}
@router.put('/pos/{po_id}')
def edit_po(po_id:int,body:dict,user:dict=Depends(roles('SupplyChainManager'))):return revise_po(po_id,body,user)
@router.put('/pos/{po_id}/amend')
def amend_po(po_id:int,body:dict,user:dict=Depends(roles('SupplyChainManager'))):return revise_po(po_id,body,user,True)
@router.put('/pos/{po_id}/approve')
def approve_po(po_id:int,body:dict,user:dict=Depends(roles(*PROC))):
    po=fetch_one('SELECT * FROM purchase_orders WHERE id=?',(po_id,));
    if not po:raise HTTPException(404,'PO not found')
    if po['status']!='PendingApproval':raise HTTPException(409,f"PO is {po['status']} and cannot be approved")
    pending=fetch_one("SELECT * FROM approval_log WHERE document_type='PO' AND document_id=? AND decision='Pending' ORDER BY sequence,id LIMIT 1",(po_id,))
    if not pending:raise HTTPException(409,'This PO has no pending approval decision')
    value=float(po.get('base_currency_amount')or po.get('total_amount')or 0);delegation=active_delegation(user,'PROC_PO_APPROVE','PO',po_id)
    try:employee,approval_limit,authority=approval_authorized(user,po['created_by'],value,'PO',pending=pending)
    except HTTPException:
        if not delegation:raise
        employee,approval_limit,authority=None,None,'Delegated Authority'
    if po.get('external_approval_required'):
        if user['role']!='SupplyChainManager':raise HTTPException(403,'Only the Supply Chain Manager may approve a PO above the SCM limit')
        if not fetch_one("SELECT id FROM document_attachments WHERE document_type='MANUAL_APPROVAL' AND document_id=? LIMIT 1",(po_id,)):raise HTTPException(409,'Upload the signed higher-management approval before approving this PO')
        if not str(body.get('approval_ref_number')or'').strip():raise HTTPException(400,'Higher-management approval reference is required')
    with transaction(immediate=True)as c:c.execute("UPDATE purchase_orders SET status='Approved',approval_ref_number=?,approval_person_name=? WHERE id=?",(body.get('approval_ref_number'),body.get('approval_person_name'),po_id));c.execute("UPDATE approval_log SET decision='Approved',decision_by=?,decision_date=datetime('now'),approval_limit_used=?,approval_limit_source=? WHERE id=?",(user['id'],approval_limit,authority,pending['id']));delegated=record_delegated_use(c,delegation,user,'purchase_orders',po_id,'APPROVE')if delegation else{};log_audit(c,'purchase_orders',po_id,'APPROVE',user['id'],po,{**body,'authority':authority,'approval_limit':approval_limit,**delegated})
    return {'success':True,'status':'Approved'}
@router.put('/pos/{po_id}/reject')
def reject_po(po_id:int,user:dict=Depends(roles('PurchaseManager','SupplyChainManager'))):
    po=fetch_one('SELECT * FROM purchase_orders WHERE id=?',(po_id,))
    if not po:raise HTTPException(404,'PO not found')
    if po['status']!='PendingApproval':raise HTTPException(409,f"PO is {po['status']} and cannot be rejected")
    pending=fetch_one("SELECT * FROM approval_log WHERE document_type='PO' AND document_id=? AND decision='Pending' ORDER BY sequence,id LIMIT 1",(po_id,))
    if not pending:raise HTTPException(409,'This PO has no pending approval decision')
    approval_authorized(user,po['created_by'],float(po.get('base_currency_amount')or po.get('total_amount')or 0),'PO',pending=pending)
    with transaction(immediate=True)as c:
        c.execute("UPDATE purchase_orders SET status='Rejected' WHERE id=?",(po_id,));c.execute("UPDATE approval_log SET decision='Rejected',decision_by=?,decision_date=datetime('now') WHERE document_type='PO' AND document_id=? AND decision='Pending'",(user['id'],po_id));[refresh_pr_order_status(c,row['pr_id'],user['id'],po_id)for row in c.execute('SELECT pr_id FROM po_pr_links WHERE po_id=?',(po_id,)).fetchall()];log_audit(c,'purchase_orders',po_id,'REJECT',user['id'])
    return {'success':True}
@router.put('/pos/{po_id}/cancel')
def cancel_po(po_id:int,body:dict,user:dict=Depends(roles('PurchaseManager','SupplyChainManager'))):
    reason=str(body.get('reason') or '').strip()
    if not reason:raise HTTPException(400,'A cancellation reason is required')
    with transaction(immediate=True) as c:
        row=c.execute('SELECT * FROM purchase_orders WHERE id=?',(po_id,)).fetchone()
        if not row:raise HTTPException(404,'Purchase Order not found')
        if row['status'] not in ('Draft','PendingApproval','Approved','Printed','Partially Received'):raise HTTPException(409,'This PO is not active')
        if c.execute('SELECT 1 FROM grns WHERE po_id=?',(po_id,)).fetchone() or c.execute('SELECT 1 FROM invoices WHERE po_id=?',(po_id,)).fetchone():raise HTTPException(409,'Received or invoiced POs require controlled receipt/finance reversal before cancellation')
        c.execute("UPDATE purchase_orders SET status='Cancelled' WHERE id=?",(po_id,))
        for link in c.execute('SELECT DISTINCT pr_id FROM po_pr_item_allocations WHERE po_id=?',(po_id,)).fetchall():refresh_pr_order_status(c,link['pr_id'],user['id'],po_id)
        log_audit(c,'purchase_orders',po_id,'UPDATE',user['id'],dict(row),{'status':'Cancelled','reason':reason,'workflow_action':'CANCEL_PO'})
    return {'success':True,'status':'Cancelled'}

@router.get('/pos/{po_id}/approval-history')
def po_history(po_id:int,_u:User):return approval_history('PO',po_id)
@router.post('/pos/{po_id}/print')
def print_po(po_id:int,user:dict=Depends(roles(*PROC))):
    po=fetch_one('SELECT * FROM purchase_orders WHERE id=?',(po_id,))
    if not po:raise HTTPException(404,'PO not found')
    if po['status']not in('Approved','Printed','Partially Received','Closed'):raise HTTPException(409,'Purchase Order must be approved before printing or downloading')
    with transaction(immediate=True)as c:c.execute("UPDATE purchase_orders SET status=CASE WHEN status='Approved' THEN 'Printed' ELSE status END,print_count=COALESCE(print_count,0)+1 WHERE id=?",(po_id,));log_audit(c,'purchase_orders',po_id,'UPDATE',user['id'],after={'workflow_action':'PRINT'})
    return {'success':True}
@router.get('/pos/{po_id}/document')
def document(po_id:int,user:User):
    row=detail('PO',po_id,user)
    items=row.pop('items',[])
    return {
        'po':row,
        'items':items,
        'company':fetch_one('SELECT * FROM company WHERE deleted_at IS NULL ORDER BY id LIMIT 1')or{},
        'approvals':approval_history('PO',po_id),
    }
@router.post('/pos/pricing')
def pricing(body:dict,_u:dict=Depends(roles(*PROC))):
    supplier=int(body['supplier_id']) if body.get('supplier_id') else None;target_currency=str(body.get('transaction_currency')or(fetch_one("SELECT COALESCE(base_currency,currency,'SAR') value FROM company WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 1")or{'value':'SAR'})['value']).upper()
    base_currency,transaction_currency,_,target_rate,_=po_currency_context(0,target_currency);out=[]
    for item_id in set(body.get('item_ids')or[]):
        item=fetch_one('SELECT id,item_code,description,uom,purchase_uom,conversion_factor,standard_cost,last_purchase_price FROM items WHERE id=? AND deleted_at IS NULL',(item_id,))
        if not item:continue
        purchase_uom=str(item.get('purchase_uom')or item.get('uom')or'').upper()
        base_uom=str(item.get('uom')or purchase_uom).upper()
        target_factor=1.0 if purchase_uom==base_uom else float(item.get('conversion_factor')or 1)
        histories=fetch_all('''SELECT poi.price,poi.tax,po.po_number,po.po_date,po.created_at,po.supplier_id,s.name supplier_name,
          COALESCE(po.transaction_currency,po.base_currency,?) transaction_currency,COALESCE(po.exchange_rate,1) exchange_rate,
          COALESCE(poi.transaction_uom,i.purchase_uom,i.uom) transaction_uom,
          COALESCE(NULLIF(poi.conversion_factor_used,0),CASE WHEN COALESCE(i.purchase_uom,i.uom)=i.uom THEN 1 ELSE COALESCE(NULLIF(i.conversion_factor,0),1) END) conversion_factor_used
          FROM po_items poi JOIN purchase_orders po ON po.id=poi.po_id JOIN suppliers s ON s.id=po.supplier_id JOIN items i ON i.id=poi.item_id
          WHERE poi.item_id=? AND po.status='Closed' ORDER BY COALESCE(po.po_date,po.created_at) DESC,po.id DESC''',(base_currency,item_id))
        def comparable(row):
            factor=float(row.get('conversion_factor_used')or 1)
            base_unit=float(row.get('price')or 0)*float(row.get('exchange_rate')or 1)/factor
            return float(money(base_unit*target_factor/float(target_rate)))
        enriched=[{**row,'comparable_price':comparable(row)} for row in histories]
        supplier_rows=[row for row in enriched if supplier and row.get('supplier_id')==supplier]
        latest_known=enriched[0] if enriched else None
        latest_supplier=supplier_rows[0] if supplier_rows else None
        supplier_low=min(supplier_rows,key=lambda row:row['comparable_price']) if supplier_rows else None
        global_low=min(enriched,key=lambda row:row['comparable_price']) if enriched else None
        average=sum(row['comparable_price']for row in enriched)/len(enriched) if enriched else None
        out.append({'item_id':item['id'],'item_code':item.get('item_code'),'description':item.get('description'),'purchase_uom':purchase_uom,'base_uom':base_uom,'transaction_currency':transaction_currency,'base_currency':base_currency,'exchange_rate':target_rate,'standard_cost':item.get('standard_cost'),'last_purchase_price':latest_known.get('comparable_price')if latest_known else None,'last_purchase_supplier_name':latest_known.get('supplier_name')if latest_known else None,'last_purchase_po_number':latest_known.get('po_number')if latest_known else None,'latest_supplier_price':latest_supplier.get('comparable_price')if latest_supplier else None,'latest_supplier_tax':latest_supplier.get('tax')if latest_supplier else None,'latest_supplier_po_number':latest_supplier.get('po_number')if latest_supplier else None,'supplier_lowest_price':supplier_low.get('comparable_price')if supplier_low else None,'supplier_lowest_po_number':supplier_low.get('po_number')if supplier_low else None,'all_supplier_average_price':float(money(average))if average is not None else None,'received_history_count':len(enriched),'global_lowest_price':global_low.get('comparable_price')if global_low else None,'global_lowest_supplier_name':global_low.get('supplier_name')if global_low else None,'global_lowest_po_number':global_low.get('po_number')if global_low else None,'global_lowest_po_date':global_low.get('po_date')or(global_low.get('created_at')[:10]if global_low and global_low.get('created_at')else None),'pricing_basis':f'{transaction_currency} per {purchase_uom}','normalized':True})
    return out
@router.get('/pos/{po_id}/invoice-context')
def invoice_context(po_id:int,_u:dict=Depends(roles(*PROC))):
    po=fetch_one('SELECT * FROM purchase_orders WHERE id=?',(po_id,));
    if not po:raise HTTPException(404,'PO not found')
    return {'po':po,'supplier':fetch_one('SELECT * FROM suppliers WHERE id=?',(po['supplier_id'],)),'items':fetch_all('''SELECT pi.*,i.item_code,i.description,pi.quantity ordered_qty,
      COALESCE((SELECT SUM(gi.accepted_qty) FROM grn_items gi JOIN grns g ON g.id=gi.grn_id WHERE g.po_id=pi.po_id AND gi.item_id=pi.item_id),0)accepted_qty,
      COALESCE((SELECT SUM(gi.rejected_qty) FROM grn_items gi JOIN grns g ON g.id=gi.grn_id WHERE g.po_id=pi.po_id AND gi.item_id=pi.item_id),0)rejected_qty
      FROM po_items pi JOIN items i ON i.id=pi.item_id WHERE pi.po_id=?''',(po_id,)),'receipts':fetch_all('''SELECT g.*,
      COALESCE(SUM(gi.accepted_qty),0)accepted_qty,
      ROUND(COALESCE(SUM(gi.accepted_qty*gi.unit_cost*(1+COALESCE(pi.tax,0)/100.0)),0),2)accepted_value
      FROM grns g LEFT JOIN grn_items gi ON gi.grn_id=g.id LEFT JOIN po_items pi ON pi.po_id=g.po_id AND pi.item_id=gi.item_id
      WHERE g.po_id=? GROUP BY g.id ORDER BY g.id''',(po_id,)),'grn_value':invoice_grn_value(po_id)}
@router.get('/invoices')
def invoices(_u:dict=Depends(roles(*PROC))):return fetch_all('SELECT inv.*,s.name supplier_name,po.po_number,g.grn_number FROM invoices inv JOIN suppliers s ON s.id=inv.supplier_id JOIN purchase_orders po ON po.id=inv.po_id LEFT JOIN grns g ON g.id=inv.grn_id ORDER BY inv.id DESC')
RECONCILIATION_REASONS={'SUPPLIER_CREDIT_NOTE','APPROVED_DISCOUNT','TAX_CORRECTION','FREIGHT_ADJUSTMENT','ROUNDING_DIFFERENCE','PRICE_CORRECTION','QUANTITY_DISCREPANCY','REJECTED_GOODS','CORRECTED_INVOICE','OTHER'}
def invoice_grn_value(po_id):
    row=fetch_one('''SELECT COALESCE(SUM(gi.accepted_qty*gi.unit_cost*(1+COALESCE(pi.tax,0)/100.0)),0)value
      FROM grn_items gi JOIN grns g ON g.id=gi.grn_id
      JOIN po_items pi ON pi.po_id=g.po_id AND pi.item_id=gi.item_id WHERE g.po_id=?''',(po_id,))or{}
    return round(float(row.get('value')or 0),2)
def match_rules():
    company=fetch_one('SELECT id FROM company WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 1')or{}
    rows=fetch_all("""SELECT component,percentage_tolerance,absolute_tolerance FROM three_way_match_tolerances
      WHERE company_id=? AND active_yn=1 AND date(effective_from)<=date('now')
      AND(effective_until IS NULL OR date(effective_until)>=date('now')) ORDER BY effective_from DESC,id DESC""",(company.get('id'),))
    result={}
    for row in rows:result.setdefault(row['component'],row)
    return result
def match_evaluation(expected_total,actual_total,expected_tax=0,actual_tax=0,components=None):
    rules=match_rules();comparisons=list(components or[])
    comparisons.append(compare_component('tax',expected_tax,actual_tax,rules.get('tax')))
    comparisons.append(compare_component('total_value',expected_total,actual_total,rules.get('total_value')))
    result=classify(comparisons)
    return {'result_code':result,'matched':result in('MATCHED','MATCHED_WITHIN_TOLERANCE'),'comparisons':comparisons}
def within_match_tolerance(left,right,component='total_value'):
    return compare_component(component,left,right,match_rules().get(component))['passed']

@router.get('/match-tolerances')
def get_match_tolerances(_u:dict=Depends(roles(*PROC))):return match_rules()
@router.put('/match-tolerances')
def put_match_tolerances(body:dict,user:dict=Depends(roles('SupplyChainManager'))):
    company=fetch_one('SELECT id FROM company WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 1')
    if not company:raise HTTPException(409,'Company configuration is required')
    rules=body.get('rules')
    if not isinstance(rules,list):raise HTTPException(400,'Rules must be a list')
    allowed={'quantity','unit_price','line_value','total_value','tax','freight','other_charges','rounding'}
    with transaction(immediate=True)as c:
        for rule in rules:
            component=rule.get('component');pct=rule.get('percentage_tolerance');absolute=rule.get('absolute_tolerance')
            if component not in allowed or(pct is None and absolute is None):raise HTTPException(400,'Each tolerance needs a valid component and percentage or absolute limit')
            if(pct is not None and decimal_value(pct)<0)or(absolute is not None and decimal_value(absolute)<0):raise HTTPException(400,'Tolerance values cannot be negative')
            c.execute('UPDATE three_way_match_tolerances SET active_yn=0 WHERE company_id=? AND component=? AND active_yn=1',(company['id'],component))
            c.execute('INSERT INTO three_way_match_tolerances(company_id,component,percentage_tolerance,absolute_tolerance,currency,created_by)VALUES(?,?,?,?,?,?)',(company['id'],component,float(pct)if pct is not None else None,float(absolute)if absolute is not None else None,body.get('currency')or'SAR',user['id']))
        log_audit(c,'three_way_match_tolerances',company['id'],'UPDATE',user['id'],after=body)
    return match_rules()
def finance_handoff_authority(user,invoice_id):
    if user['role']=='SupplyChainManager':return {'can_approve':True,'effective_role':'SupplyChainManager','delegation':None}
    delegation=active_delegation(user,'FINANCE_EXTERNAL_HANDOFF','INVOICE',invoice_id)
    return {'can_approve':bool(delegation),'effective_role':user['role'] if delegation else'SupplyChainManager','delegation':delegation}
def require_handoff_authority(user,invoice_id):
    authority=finance_handoff_authority(user,invoice_id)
    if not authority['can_approve']:raise HTTPException(403,'Only the Supply Chain Manager or an active, specifically authorized delegate may perform this action')
    return authority
def match_data(invoice_id):
    inv=fetch_one('SELECT * FROM invoices WHERE id=?',(invoice_id,));
    if not inv:raise HTTPException(404,'Invoice not found')
    po=fetch_one('SELECT * FROM purchase_orders WHERE id=?',(inv['po_id'],));grns=fetch_all('SELECT * FROM grns WHERE po_id=? ORDER BY id',(inv['po_id'],));grn_value=invoice_grn_value(inv['po_id']);adjusted=inv.get('adjusted_invoice_total')if inv.get('adjusted_invoice_total')is not None else inv['invoice_total'];return inv,po,grns,grn_value,float(adjusted)
@router.post('/invoices',status_code=201)
def create_invoice(body:dict,user:dict=Depends(roles(*PROC))):
    po=fetch_one('SELECT * FROM purchase_orders WHERE id=?',(body.get('po_id'),));
    if not po or po['status']not in('Approved','Printed','Partially Received','Closed'):raise HTTPException(409,'Invoice requires an approved Purchase Order')
    if body.get('supplier_id')!=po['supplier_id']:raise HTTPException(400,'Invoice supplier must match the Purchase Order supplier')
    number_text=str(body.get('invoice_number')or'').strip();invoice_date=str(body.get('invoice_date')or datetime.now().date().isoformat())
    if not number_text:raise HTTPException(400,'Supplier invoice number is required')
    if fetch_one('SELECT id FROM invoices WHERE supplier_id=? AND lower(trim(invoice_number))=lower(?)',(po['supplier_id'],number_text)):raise HTTPException(409,'This supplier invoice number is already registered')
    try:total=float(body.get('invoice_total'));tax=float(body.get('tax')or 0);parsed_date=datetime.fromisoformat(invoice_date).date()
    except (TypeError,ValueError):raise HTTPException(400,'Enter a valid invoice date and amount')
    if total<=0 or tax<0:raise HTTPException(400,'Invoice total must be positive and tax cannot be negative')
    if parsed_date>datetime.now().date():raise HTTPException(400,'Invoice date cannot be in the future')
    selected_grn=body.get('grn_id')
    if selected_grn and not fetch_one('SELECT id FROM grns WHERE id=? AND po_id=?',(selected_grn,po['id'])):raise HTTPException(400,'Selected GRN does not belong to the Purchase Order')
    grns=fetch_all('SELECT id FROM grns WHERE po_id=?',(po['id'],))
    if not grns:raise HTTPException(409,'Invoice requires at least one posted GRN')
    grn_value=invoice_grn_value(po['id']);evaluation=match_evaluation(grn_value,total,0,tax);source_match=True;status='Matched'if evaluation['matched']else'Variance'
    classification=evaluation['result_code']
    invoice_currency=body.get('transaction_currency')or po.get('transaction_currency')or'SAR';invoice_rate=float(po.get('exchange_rate')or 1)if invoice_currency==po.get('transaction_currency')else 1;base_total=round(total*invoice_rate,2)
    with transaction(immediate=True)as c:
        if c.execute('SELECT id FROM invoices WHERE supplier_id=? AND lower(trim(invoice_number))=lower(?)',(po['supplier_id'],number_text)).fetchone():raise HTTPException(409,'This supplier invoice number is already registered')
        cur=c.execute('INSERT INTO invoices(invoice_number,supplier_id,po_id,grn_id,invoice_date,invoice_total,tax,match_status,created_by,transaction_currency,exchange_rate,base_currency,base_currency_amount,variance_reason,adjusted_invoice_total,reconciliation_classification,recommended_adjustment,source_documents_match,match_result_code,match_details_json)VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(number_text,po['supplier_id'],po['id'],selected_grn,invoice_date,total,tax,status,user['id'],invoice_currency,invoice_rate,po.get('base_currency')or'SAR',base_total,body.get('variance_reason'),total,classification,round(grn_value-total,2),int(source_match),evaluation['result_code'],json.dumps(evaluation['comparisons'])));iid=cur.lastrowid
        for line in body.get('items')or[]:
            q=decimal_value(line.get('quantity'));price=decimal_value(line.get('unit_price'));line_value=money(line.get('line_value')if line.get('line_value')is not None else q*price)
            if q<=0 or price<0:raise HTTPException(400,'Invoice line quantity and price are invalid')
            c.execute('INSERT INTO invoice_items(invoice_id,item_id,quantity,unit_price,line_value,tax,freight,other_charges)VALUES(?,?,?,?,?,?,?,?)',(iid,line.get('item_id'),float(q),float(price),float(line_value),float(decimal_value(line.get('tax')or 0)),float(decimal_value(line.get('freight')or 0)),float(decimal_value(line.get('other_charges')or 0))))
        log_audit(c,'invoices',iid,'CREATE',user['id'],after={**body,'match_status':status,'match_result_code':evaluation['result_code'],'grn_value':grn_value});
    return {'id':iid,'match_status':status}
@router.put('/invoices/{invoice_id}/reconcile')
def reconcile(invoice_id:int,body:dict,user:User):
    authority=require_handoff_authority(user,invoice_id);inv,po,_,grn_value,_=match_data(invoice_id)
    if inv['finance_pack_status']!='Not Submitted':raise HTTPException(409,'A handed-off invoice is locked and cannot be reconciled')
    if inv.get('created_by')==user['id'] and not allows_self_approval(user):raise HTTPException(409,'The invoice creator cannot accept or reconcile its variance')
    if not within_match_tolerance(po['total_amount'],grn_value):raise HTTPException(409,'PO and accepted GRN values differ; correct the source documents before reconciling the invoice')
    try:adjust=float(body.get('reconciliation_adjustment',0))
    except (TypeError,ValueError):raise HTTPException(400,'Enter a valid reconciliation adjustment')
    note=str(body.get('variance_acceptance_note')or'').strip();reason=str(body.get('reconciliation_reason_code')or'').strip()
    adjusted=round(float(inv['invoice_total'])+adjust,2)
    if not within_match_tolerance(adjusted,po['total_amount']) or not within_match_tolerance(adjusted,grn_value):raise HTTPException(409,'The reconciliation must resolve both PO and GRN differences within tolerance')
    if abs(adjust)>.001 and (reason not in RECONCILIATION_REASONS or len(note)<10):raise HTTPException(400,'A valid reason category and detailed acceptance note are required')
    classification='Exact Match'if abs(adjust)<=.001 else'Reconciled';status='Matched'
    with transaction(immediate=True)as c:
        c.execute("UPDATE invoices SET reconciliation_adjustment=?,adjusted_invoice_total=?,variance_acceptance_note=?,reconciliation_reason_code=?,reconciliation_classification=?,match_status=?,variance_accepted_by=?,variance_accepted_at=datetime('now'),source_documents_match=1 WHERE id=?",(adjust,adjusted,note or None,reason or None,classification,status,user['id'],invoice_id));delegated=record_delegated_use(c,authority['delegation'],user,'invoices',invoice_id,'RECONCILE')if authority['delegation']else{};log_audit(c,'invoices',invoice_id,'RECONCILE',user['id'],inv,{**body,**delegated})
    return {'success':True,'match_status':status,'remaining_variance':round(adjusted-po['total_amount'],2)}
@router.get('/invoices/{invoice_id}/three-way-match')
def three_way(invoice_id:int,_u:dict=Depends(roles(*PROC))):
    inv,po,grns,grn_value,adjusted=match_data(invoice_id);inv.update(supplier_document_fields(inv.get('supplier_id')));po.update(supplier_document_fields(po.get('supplier_id')));evaluation=match_evaluation(grn_value,adjusted,0,inv.get('tax')or 0);return {'invoice':inv,'po':po,'grns':grns,'po_total':po['total_amount'],'grn_total':grn_value,'invoice_total':adjusted,'po_invoice_variance':float(money(decimal_value(adjusted)-decimal_value(po['total_amount']))),'grn_invoice_variance':float(money(decimal_value(adjusted)-decimal_value(grn_value))),'source_documents_match':True,'matched':evaluation['matched'],'result_code':evaluation['result_code'],'comparisons':evaluation['comparisons']}
@router.get('/invoices/{invoice_id}/payment-pack')
def payment_pack(invoice_id:int,user:dict=Depends(roles(*PROC))):
    inv,po,grns,grn_value,adjusted=match_data(invoice_id);supplier=fetch_one('SELECT * FROM suppliers WHERE id=?',(inv['supplier_id'],));attachments=fetch_all("SELECT * FROM document_attachments WHERE(document_type='INVOICE'AND document_id=?)OR(document_type='PO'AND document_id=?)",(invoice_id,po['id']))
    creator=fetch_one('SELECT u.full_name,e.signature_url FROM users u LEFT JOIN employees e ON e.id=u.employee_id WHERE u.id=?',(inv.get('created_by'),))or{};acceptor=fetch_one('SELECT u.full_name,e.signature_url FROM users u LEFT JOIN employees e ON e.id=u.employee_id WHERE u.id=?',(inv.get('variance_accepted_by'),))or{};confirmer=fetch_one('SELECT u.full_name,e.signature_url FROM users u LEFT JOIN employees e ON e.id=u.employee_id WHERE u.id=?',(inv.get('verified_by'),))or{}
    enriched={**inv,'supplier_name':supplier.get('name'),'supplier_code':supplier.get('supplier_code'),'payment_terms':supplier.get('payment_terms'),'po_number':po.get('po_number'),'po_date':po.get('po_date'),'po_total':po.get('total_amount'),'created_by_name':creator.get('full_name'),'created_by_signature_url':creator.get('signature_url'),'variance_accepted_by_name':acceptor.get('full_name'),'variance_accepted_by_signature_url':acceptor.get('signature_url'),'confirmed_by_name':confirmer.get('full_name'),'confirmed_by_signature_url':confirmer.get('signature_url')}
    enriched.update(supplier_document_fields(inv.get('supplier_id')))
    duplicate=fetch_one('SELECT COUNT(*) count FROM invoices WHERE supplier_id=? AND lower(trim(invoice_number))=lower(trim(?))',(inv['supplier_id'],inv['invoice_number']))
    return {'invoice':enriched,'po':po,'supplier':supplier,'grns':grns,'grn_value':grn_value,'adjusted_invoice_total':adjusted,'company':fetch_one('SELECT * FROM company WHERE deleted_at IS NULL ORDER BY id LIMIT 1')or{},'attachments':attachments,'attachment_count':len(attachments),'duplicate_check_passed':int((duplicate or{}).get('count')or 0)==1,'analysis':{'classification':inv.get('reconciliation_classification'),'po_invoice_variance':round(adjusted-po['total_amount'],2),'grn_invoice_variance':round(adjusted-grn_value,2)},'approval_authority':finance_handoff_authority(user,invoice_id)}
@router.put('/invoices/{invoice_id}/ready-for-finance')
def finance(invoice_id:int,body:dict,user:User):
    inv=fetch_one('SELECT * FROM invoices WHERE id=?',(invoice_id,));
    if not inv:raise HTTPException(404,'Invoice not found')
    authority=require_handoff_authority(user,invoice_id)
    if inv['finance_pack_status']!='Not Submitted':raise HTTPException(409,'This invoice has already been handed off to Finance')
    if inv.get('created_by')==user['id'] and not allows_self_approval(user):raise HTTPException(409,'The invoice creator cannot authorize its Finance handoff')
    current,po,_,grn_value,adjusted=match_data(invoice_id)
    if current['match_status']!='Matched' or not within_match_tolerance(adjusted,po['total_amount']) or not within_match_tolerance(adjusted,grn_value):raise HTTPException(409,'Resolve all PO, GRN and invoice differences before Finance handoff')
    if not fetch_one("SELECT id FROM document_attachments WHERE document_type='INVOICE' AND document_id=? LIMIT 1",(invoice_id,)):raise HTTPException(409,'Attach the supplier invoice before Finance handoff')
    with transaction(immediate=True)as c:
        ref=number(c,'FINPACK');c.execute("UPDATE invoices SET finance_pack_reference=?,finance_pack_status='Ready for Finance - External Process',verified_by=?,verified_date=datetime('now'),finance_review_comments=? WHERE id=?",(ref,user['id'],str(body.get('comments')or'').strip()or None,invoice_id));delegated=record_delegated_use(c,authority['delegation'],user,'invoices',invoice_id,'FINANCE_HANDOFF')if authority['delegation']else{};log_audit(c,'invoices',invoice_id,'FINANCE_HANDOFF',user['id'],inv,{'finance_pack_status':'Ready for Finance - External Process','self_approved':inv.get('created_by')==user['id'],**delegated})
    return {'success':True,'finance_pack_reference':ref}
@router.put('/invoices/{invoice_id}/submit-finance')
def retired_submit(invoice_id:int,_u:User):raise HTTPException(410,'Use the Ready for Finance - External Process handoff action')
@router.put('/invoices/{invoice_id}/verify')
def verify(invoice_id:int,user:dict=Depends(roles('SupplyChainManager'))):
    raise HTTPException(410,'Use the controlled Ready for Finance handoff action')
