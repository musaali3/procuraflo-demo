from ..approval_routing import allows_self_approval
from datetime import date
from fastapi import APIRouter,Depends,HTTPException
from ..audit import log_audit
from ..database import fetch_all,fetch_one,transaction
from ..security import roles
router=APIRouter(prefix='/api/controls',tags=['controls']);admin=roles('SupplyChainManager')
@router.get('/ledger-dispositions')
def ledger(_u:dict=Depends(admin)):return fetch_all('SELECT l.*,i.item_code,i.description,w.name warehouse_name,loc.code bin_code,ru.full_name reviewed_by_name,au.full_name approved_by_name FROM legacy_ledger_reconciliation l JOIN items i ON i.id=l.item_id JOIN warehouses w ON w.id=l.warehouse_id LEFT JOIN locations loc ON loc.id=l.location_id LEFT JOIN users ru ON ru.id=l.reviewed_by LEFT JOIN users au ON au.id=l.approved_by ORDER BY l.id')
@router.put('/ledger-dispositions/{row_id}/review')
def review(row_id:int,b:dict,u:dict=Depends(admin)):
    with transaction(immediate=True)as c:c.execute("UPDATE legacy_ledger_reconciliation SET root_cause_classification=?,supporting_evidence=?,evidence_reference=?,management_decision=?,business_explanation=?,audit_reference=?,reviewed_by=?,reviewed_at=datetime('now'),updated_at=datetime('now') WHERE id=?",(b.get('root_cause_classification'),b.get('supporting_evidence'),b.get('evidence_reference'),b.get('management_decision'),b.get('business_explanation'),b.get('audit_reference'),u['id'],row_id));log_audit(c,'legacy_ledger_reconciliation',row_id,'UPDATE',u['id'],after=b)
    return {'success':True}
@router.put('/ledger-dispositions/{row_id}/approve')
def approve(row_id:int,b:dict,u:dict=Depends(admin)):
    row=fetch_one('SELECT * FROM legacy_ledger_reconciliation WHERE id=?',(row_id,));
    if not row:raise HTTPException(404,'Warning not found')
    if row.get('reviewed_by')==u['id'] and not allows_self_approval(u):raise HTTPException(409,'Reviewer cannot approve the same warning')
    with transaction(immediate=True)as c:c.execute("UPDATE legacy_ledger_reconciliation SET approved_by=?,approved_at=datetime('now'),resolution_status=COALESCE(?,resolution_status),updated_at=datetime('now')WHERE id=?",(u['id'],b.get('resolution_status'),row_id));log_audit(c,'legacy_ledger_reconciliation',row_id,'APPROVE',u['id'],row,{**b,'self_approved':row.get('reviewed_by')==u['id']})
    return {'success':True}
@router.get('/ledger-batches')
def batches(_u:dict=Depends(admin)):return fetch_all('SELECT b.*,COUNT(i.id)warning_count FROM legacy_ledger_disposition_batches b LEFT JOIN legacy_ledger_batch_items i ON i.batch_id=b.id GROUP BY b.id ORDER BY b.id DESC')
@router.get('/sod-reviews')
def sod(_u:dict=Depends(admin)):return fetch_all('SELECT s.*,u.full_name,e.employee_code,e.name employee_name FROM sod_conflict_reviews s JOIN users u ON u.id=s.user_id LEFT JOIN employees e ON e.id=s.employee_id ORDER BY s.risk DESC,s.id')
@router.put('/sod-reviews/{row_id}')
def update_sod(row_id:int,b:dict,u:dict=Depends(admin)):
    before=fetch_one('SELECT * FROM sod_conflict_reviews WHERE id=?',(row_id,));
    if not before:raise HTTPException(404,'SoD conflict not found')
    with transaction(immediate=True)as c:c.execute("UPDATE sod_conflict_reviews SET management_decision=?,business_justification=?,permission_change=?,compensating_control=?,review_date=date('now'),expiry_date=?,status='REQUIRES MANAGEMENT REVIEW',updated_at=datetime('now')WHERE id=?",(b.get('management_decision'),b.get('business_justification'),b.get('permission_change'),b.get('compensating_control'),b.get('expiry_date'),row_id));log_audit(c,'sod_conflict_reviews',row_id,'UPDATE',u['id'],before,b)
    return {'success':True}
@router.put('/sod-reviews/{row_id}/approve')
def approve_sod(row_id:int,u:dict=Depends(admin)):
    row=fetch_one('SELECT * FROM sod_conflict_reviews WHERE id=?',(row_id,));
    if not row or not row.get('management_decision'):raise HTTPException(409,'A documented decision is required first')
    status='APPROVED BUSINESS EXCEPTION'if row['management_decision']=='APPROVED BUSINESS EXCEPTION'else'FALSE POSITIVE'if row['management_decision']=='FALSE POSITIVE'else'TRUE CONFLICT'
    with transaction(immediate=True)as c:c.execute("UPDATE sod_conflict_reviews SET approved_by=?,approval_date=date('now'),status=?,updated_at=datetime('now')WHERE id=?",(u['id'],status,row_id))
    return {'success':True}
@router.get('/accounting-periods')
def periods(_u:dict=Depends(admin)):return fetch_all('SELECT * FROM accounting_periods ORDER BY start_date DESC')
@router.post('/accounting-periods',status_code=201)
def add_period(b:dict,u:dict=Depends(admin)):
    try:
        start=date.fromisoformat(str(b.get('start_date')));end=date.fromisoformat(str(b.get('end_date')));period=int(b.get('period_number'));year=int(b.get('fiscal_year'))
    except(TypeError,ValueError):raise HTTPException(400,'Fiscal year, period number, start date, and end date are required')
    status=str(b.get('status')or'OPEN').upper().replace('_',' ')
    if start>end or period<1 or period>53:raise HTTPException(400,'Enter a valid non-reversed accounting period')
    if status not in {'OPEN','SOFT CLOSED','CLOSED'}:raise HTTPException(400,'Accounting period status must be OPEN, SOFT CLOSED, or CLOSED')
    if status!='OPEN'and(not str(b.get('reason')or'').strip()or not str(b.get('approval_reference')or'').strip()):raise HTTPException(400,'Closing a period requires a reason and approval reference')
    if fetch_one('SELECT 1 ok FROM accounting_periods WHERE start_date<=?AND end_date>=?',(b.get('end_date'),b.get('start_date'))):raise HTTPException(409,'Accounting periods cannot overlap')
    with transaction(immediate=True)as c:cur=c.execute('INSERT INTO accounting_periods(fiscal_year,period,period_number,start_date,end_date,status,reason,approval_reference)VALUES(?,?,?,?,?,?,?,?)',(year,f'{year}-{period:02d}',period,start.isoformat(),end.isoformat(),status,b.get('reason'),b.get('approval_reference')));log_audit(c,'accounting_periods',cur.lastrowid,'CREATE',u['id'],after={**b,'status':status});rid=cur.lastrowid
    return {'id':rid}
@router.put('/accounting-periods/{row_id}/status')
def period_status(row_id:int,b:dict,u:dict=Depends(admin)):
    before=fetch_one('SELECT * FROM accounting_periods WHERE id=?',(row_id,));status=str(b.get('status')or'').upper().replace('_',' ')
    if not before:raise HTTPException(404,'Accounting period not found')
    if status not in {'OPEN','SOFT CLOSED','CLOSED'}:raise HTTPException(400,'Accounting period status must be OPEN, SOFT CLOSED, or CLOSED')
    if status!='OPEN'and(not str(b.get('reason')or'').strip()or not str(b.get('approval_reference')or'').strip()):raise HTTPException(400,'Closing a period requires a reason and approval reference')
    with transaction(immediate=True)as c:c.execute("UPDATE accounting_periods SET status=?,reason=?,approval_reference=?,closed_by=CASE WHEN ?='OPEN'THEN NULL ELSE ? END,closed_at=CASE WHEN ?='OPEN'THEN NULL ELSE datetime('now')END WHERE id=?",(status,b.get('reason'),b.get('approval_reference'),status,u['id'],status,row_id));log_audit(c,'accounting_periods',row_id,'UPDATE',u['id'],before,{**b,'status':status})
    return {'success':True}
@router.get('/document-revisions')
def revisions(_u:dict=Depends(admin)):return fetch_all('SELECT * FROM document_revisions ORDER BY created_at DESC,id DESC')
@router.get('/authorization-limits')
def auth_limits(_u:dict=Depends(admin)):return {'po':fetch_all("SELECT id employee_id,employee_code,name,approval_role,approval_limit FROM employees WHERE deleted_at IS NULL AND approval_role IN('PurchaseOfficer','PurchaseManager','SupplyChainManager')ORDER BY name"),'material_issue':fetch_all('SELECT l.*,e.employee_code,e.name employee_name,w.name warehouse_name,u.full_name approved_by_name FROM material_issue_authorization_limits l JOIN employees e ON e.id=l.employee_id LEFT JOIN warehouses w ON w.id=l.warehouse_id JOIN users u ON u.id=l.approved_by ORDER BY l.id DESC')}
@router.post('/authorization-limits/po')
def po_limit(b:dict,u:dict=Depends(admin)):
    employee=fetch_one("SELECT * FROM employees WHERE id=? AND deleted_at IS NULL AND status='Active' AND approval_role IN('PurchaseOfficer','PurchaseManager','SupplyChainManager')",(b.get('employee_id'),));
    try:limit=float(b.get('approval_limit'))
    except(TypeError,ValueError):raise HTTPException(400,'Active procurement approver and non-negative limit are required')
    if not employee or limit<0:raise HTTPException(400,'Active procurement approver and non-negative limit are required')
    base=(fetch_one("SELECT COALESCE(base_currency,currency,'SAR')currency FROM company WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 1")or{})['currency']
    with transaction(immediate=True)as c:c.execute('UPDATE employees SET approval_limit=? WHERE id=?',(limit,employee['id']));c.execute("UPDATE approval_limit_history SET status='SUPERSEDED'WHERE employee_id=?AND approval_type='PO'AND status='ACTIVE'",(employee['id'],));c.execute("INSERT INTO approval_limit_history(employee_id,approval_type,old_limit,new_limit,currency,effective_from,expiry_date,approved_by)VALUES(?,'PO',?,?,?,?,?,?)",(employee['id'],employee.get('approval_limit'),limit,base,b.get('effective_from'),b.get('expiry_date'),u['id']));log_audit(c,'employees',employee['id'],'UPDATE',u['id'],{'approval_limit':employee.get('approval_limit')},{'approval_limit':limit})
    return {'success':True}
@router.post('/authorization-limits/material-issue',status_code=201)
def issue_limit(b:dict,u:dict=Depends(admin)):
    employee=fetch_one("SELECT id FROM employees WHERE id=? AND deleted_at IS NULL AND status='Active' AND approval_role IN('Storekeeper','WarehouseSupervisor','WarehouseManager','SupplyChainManager')",(b.get('employee_id'),))
    warehouse=fetch_one('SELECT id FROM warehouses WHERE id=? AND deleted_at IS NULL',(b.get('warehouse_id'),))if b.get('warehouse_id')else None
    try:value=float(b.get('value_limit'));quantity=float(b.get('quantity_limit'))
    except(TypeError,ValueError):raise HTTPException(400,'Active warehouse approver, warehouse, and positive limits are required')
    if not employee or not warehouse or value<=0 or quantity<=0:raise HTTPException(400,'Active warehouse approver, warehouse, and positive limits are required')
    base=(fetch_one("SELECT COALESCE(base_currency,currency,'SAR')currency FROM company WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 1")or{})['currency']
    with transaction(immediate=True)as c:cur=c.execute('INSERT INTO material_issue_authorization_limits(employee_id,warehouse_id,value_limit,currency,quantity_limit,category_scope,effective_from,expiry_date,approved_by)VALUES(?,?,?,?,?,?,?,?,?)',(employee['id'],warehouse['id'],value,base,quantity,b.get('category_scope'),b.get('effective_from'),b.get('expiry_date'),u['id']));log_audit(c,'material_issue_authorization_limits',cur.lastrowid,'CREATE',u['id'],after=b);rid=cur.lastrowid
    return {'id':rid}
@router.post('/ledger-batches',status_code=201)
def create_batch(b:dict,u:dict=Depends(admin)):
    ids=list(dict.fromkeys(b.get('warning_ids')or[]))
    if not ids:raise HTTPException(400,'Complete batch evidence and decision are required')
    with transaction(immediate=True)as c:cur=c.execute('INSERT INTO legacy_ledger_disposition_batches(batch_reference,common_root_cause,common_evidence,evidence_reference,management_decision,business_explanation,audit_reference,reviewed_by)VALUES(?,?,?,?,?,?,?,?)',(b.get('batch_reference'),b.get('common_root_cause'),b.get('common_evidence'),b.get('evidence_reference'),b.get('management_decision'),b.get('business_explanation'),b.get('audit_reference'),u['id']));[c.execute('INSERT INTO legacy_ledger_batch_items(batch_id,warning_id)VALUES(?,?)',(cur.lastrowid,x))for x in ids];rid=cur.lastrowid
    return {'id':rid,'status':'AWAITING APPROVAL','warning_count':len(ids)}
@router.put('/ledger-batches/{batch_id}/approve')
def approve_batch(batch_id:int,u:dict=Depends(admin)):
    batch=fetch_one("SELECT * FROM legacy_ledger_disposition_batches WHERE id=?AND status='AWAITING APPROVAL'",(batch_id,));
    if not batch:raise HTTPException(404,'Pending batch not found')
    if batch['reviewed_by']==u['id'] and not allows_self_approval(u):raise HTTPException(409,'Reviewer cannot approve the same batch')
    ids=[x['warning_id']for x in fetch_all('SELECT warning_id FROM legacy_ledger_batch_items WHERE batch_id=?',(batch_id,))]
    with transaction(immediate=True)as c:
        for wid in ids:c.execute("UPDATE legacy_ledger_reconciliation SET root_cause_classification=?,supporting_evidence=?,evidence_reference=?,management_decision=?,business_explanation=?,audit_reference=?,reviewed_by=?,reviewed_at=?,approved_by=?,approved_at=datetime('now'),resolution_status='RESOLVED',updated_at=datetime('now')WHERE id=?AND approved_by IS NULL",(batch['common_root_cause'],batch['common_evidence'],batch['evidence_reference'],batch['management_decision'],batch['business_explanation'],batch['audit_reference'],batch['reviewed_by'],batch['reviewed_at'],u['id'],wid))
        c.execute("UPDATE legacy_ledger_disposition_batches SET status='APPROVED',approved_by=?,approved_at=datetime('now')WHERE id=?",(u['id'],batch_id))
        log_audit(c,'legacy_ledger_disposition_batches',batch_id,'APPROVE',u['id'],batch,{'self_approved':batch['reviewed_by']==u['id']})
    return {'success':True,'warning_count':len(ids)}
