from ..pr_workflow import scoped_report
import json,sqlite3
from datetime import datetime,timedelta
from fastapi import APIRouter,Depends,HTTPException
from ..audit import log_audit
from ..database import fetch_all,fetch_one,transaction
from ..delegated_authority import AUTHORITIES,BROAD_SCOPES,ELIGIBLE_ROLES,SCOPE_TABLES,status_for
from ..security import User,roles
router=APIRouter(prefix='/api/delegations',tags=['delegations']);admin=roles('SupplyChainManager')
REASONS={'ANNUAL_LEAVE':'Annual Leave','SICK_LEAVE':'Sick Leave','BUSINESS_TRAVEL':'Business Travel','TEMPORARY_VACANCY':'Temporary Vacancy','EMERGENCY_COVERAGE':'Emergency Coverage','OPERATIONAL_REQUIREMENT':'Operational Requirement','OTHER':'Other'}
SCOPE_LABELS={'ALL_ASSIGNED_PROCUREMENT':'All Assigned Procurement Packages','ALL_AUTHORIZED_PROCUREMENT':'All Authorized Procurement Packages','ALL_ASSIGNED_WAREHOUSES':'All Assigned Warehouses'}
def role_label(v):return ''.join((' '+c if c.isupper()and i else c)for i,c in enumerate(str(v))).strip().replace('Purchase ','Procurement ')
def maximum_days():
    row=fetch_one("SELECT value FROM settings WHERE key='delegation_max_days'")
    try:return max(1,min(365,int(row['value'])))if row else 30
    except(ValueError,TypeError):return 30
def parse_period(body):
    try:start=datetime.fromisoformat(str(body.get('effective_from')or'').replace('Z','+00:00')).replace(tzinfo=None);end=datetime.fromisoformat(str(body.get('effective_until')or'').replace('Z','+00:00')).replace(tzinfo=None)
    except ValueError:raise HTTPException(400,'Enter valid Effective From and Effective Until date/time values')
    if end<=start:raise HTTPException(400,'Effective Until must be after Effective From')
    if end-start>timedelta(days=maximum_days()):raise HTTPException(400,f'Delegation cannot exceed the configured maximum of {maximum_days()} days')
    return start.isoformat(timespec='minutes'),end.isoformat(timespec='minutes')
def validate_scope(authority,scope,scope_id,broad_confirmed):
    if scope not in AUTHORITIES[authority][2]:raise HTTPException(400,'Selected scope is not valid for this delegated authority')
    if scope in BROAD_SCOPES:
        if not broad_confirmed:raise HTTPException(400,'Broad delegation requires explicit confirmation')
        return
    if scope not in SCOPE_TABLES or not isinstance(scope_id,int):raise HTTPException(400,'Select the specific record for this delegation scope')
    table,_=SCOPE_TABLES[scope]
    try:record=fetch_one(f'SELECT id FROM {table} WHERE id=?',(scope_id,))
    except sqlite3.OperationalError:record=None
    if not record:raise HTTPException(400,'The selected scope record does not exist')
def scope_label(row):
    if row['scope_type']in SCOPE_LABELS:return SCOPE_LABELS[row['scope_type']]
    table,label=SCOPE_TABLES.get(row['scope_type'],(None,None))
    if not table or not row.get('scope_id'):return row['scope_type'].replace('_',' ').title()
    try:return(fetch_one(f'SELECT {label} label FROM {table} WHERE id=?',(row['scope_id'],))or{}).get('label')or'Archived scope record'
    except sqlite3.OperationalError:return'Archived scope record'
def sync_lifecycle_notifications():
    rows=fetch_all("""SELECT da.*,u.id delegate_user_id FROM delegated_authorities da JOIN users u ON u.employee_id=da.delegate_employee_id AND u.deleted_at IS NULL WHERE upper(da.status)<>'REVOKED'""")
    with transaction(immediate=True)as c:
        for row in rows:
            state=status_for(row);event='activated'if state=='Active'else'expired'if state=='Expired'else None
            if event:c.execute("INSERT OR IGNORE INTO notifications(user_id,type,message,event_key,expires_at)VALUES(?,'DelegatedAuthority',?,?,datetime('now','+7 days'))",(row['delegate_user_id'],f'Delegation {row["delegation_number"]} is now {state.lower()}.',f'delegation:{row["id"]}:{event}'))
@router.get('/catalog')
def catalog(_u:dict=Depends(admin)):return {'authorities':[{'code':c,'department':v[0],'label':v[1],'scopes':v[2]}for c,v in AUTHORITIES.items()],'reasons':[{'code':c,'label':v}for c,v in REASONS.items()],'broad_scopes':sorted(BROAD_SCOPES),'maximum_days':maximum_days()}
@router.get('/eligible-employees')
def eligible(_u:dict=Depends(admin)):
    rows=fetch_all("""SELECT e.id,e.employee_code,e.name,e.approval_role,d.name department_name FROM employees e JOIN users u ON u.employee_id=e.id AND u.deleted_at IS NULL JOIN departments d ON d.id=e.department_id WHERE e.status='Active' AND e.deleted_at IS NULL AND e.system_access_yn=1 AND u.is_active=1 AND e.approval_role IN('PurchaseOfficer','PurchaseManager','Storekeeper','WarehouseSupervisor','WarehouseManager') ORDER BY e.name""")
    return [{**r,'department':ELIGIBLE_ROLES[r['approval_role']],'role_label':role_label(r['approval_role'])}for r in rows if r['approval_role']in ELIGIBLE_ROLES]
@router.get('/scope-options')
def scope_options(scope_type:str,_u:dict=Depends(admin)):
    if scope_type not in SCOPE_TABLES:raise HTTPException(400,'This scope does not use a record selector')
    table,label=SCOPE_TABLES[scope_type]
    try:
        if scope_type=='INVOICE':return fetch_all("SELECT inv.id,inv.invoice_number||' - '||s.name||' - '||printf('%.2f',inv.invoice_total) label FROM invoices inv JOIN suppliers s ON s.id=inv.supplier_id ORDER BY inv.id DESC LIMIT 500")
        if scope_type=='WAREHOUSE':return fetch_all("SELECT id,warehouse_code||' - '||name label FROM warehouses WHERE deleted_at IS NULL ORDER BY name")
        return scoped_report(f'SELECT id,{label} label FROM {table} ORDER BY id DESC LIMIT 500',_u)
    except sqlite3.OperationalError:return []
@router.get('/mine')
def mine(user:User):
    sync_lifecycle_notifications()
    if not user.get('employee_id'):return []
    rows=fetch_all("SELECT * FROM delegated_authorities WHERE delegate_employee_id=? AND upper(status)<>'REVOKED' AND datetime('now')<datetime(effective_until) ORDER BY effective_from",(user['employee_id'],))
    return [{**r,'effective_status':status_for(r),'authority_label':AUTHORITIES.get(r['authority_type'],('',r['authority_type'],[]))[1]}for r in rows]
@router.get('')
def list_all(_u:dict=Depends(admin)):
    sync_lifecycle_notifications()
    rows=fetch_all("""SELECT da.*,delegator.name delegator_name,delegate.name delegate_name,delegate.employee_code,creator.full_name created_by_name FROM delegated_authorities da JOIN employees delegator ON delegator.id=da.delegator_employee_id JOIN employees delegate ON delegate.id=da.delegate_employee_id JOIN users creator ON creator.id=da.created_by ORDER BY da.created_at DESC""")
    return [{**r,'effective_status':status_for(r),'authority_label':AUTHORITIES.get(r['authority_type'],('',r['authority_type'],[]))[1],'normal_role_label':role_label(r.get('employee_role_snapshot')or r['delegate_role']),'scope_label':scope_label(r)}for r in rows]
@router.get('/audit')
def audit(_u:dict=Depends(admin)):return {'history':fetch_all("SELECT h.*,d.delegation_number,u.full_name changed_by_name FROM delegated_authority_history h JOIN delegated_authorities d ON d.id=h.delegation_id JOIN users u ON u.id=h.changed_by ORDER BY h.id DESC"),'uses':fetch_all("SELECT x.*,d.delegation_number,u.full_name performed_by_name FROM delegated_authority_uses x JOIN delegated_authorities d ON d.id=x.delegation_id JOIN users u ON u.id=x.performed_by ORDER BY x.id DESC")}
@router.post('',status_code=201)
def create(body:dict,user:dict=Depends(admin)):
    delegator=fetch_one("SELECT e.id,e.name,e.approval_role FROM users u JOIN employees e ON e.id=u.employee_id WHERE u.id=? AND e.status='Active' AND e.deleted_at IS NULL",(user['id'],));delegate=fetch_one("""SELECT e.id,e.employee_code,e.name,e.approval_role,e.status,e.system_access_yn,u.id user_id,u.is_active FROM employees e JOIN users u ON u.employee_id=e.id AND u.deleted_at IS NULL WHERE e.id=? AND e.deleted_at IS NULL""",(body.get('delegate_employee_id'),))
    if not delegator or delegator['approval_role']!='SupplyChainManager':raise HTTPException(403,'Only an active Supply Chain Manager may delegate authority')
    if not delegate or delegate['status']!='Active' or not delegate['is_active'] or delegate['system_access_yn']==0:raise HTTPException(400,'Delegate must have an active employee record and Procuraflo account')
    department=ELIGIBLE_ROLES.get(delegate['approval_role']);authority=str(body.get('authority_code')or'');definition=AUTHORITIES.get(authority)
    if not department:raise HTTPException(403,'This employee role is not eligible for delegated authority')
    if not definition or definition[0]!=department:raise HTTPException(403,f'{department} employees may receive only {department} delegated authorities')
    start,end=parse_period(body);scope=str(body.get('scope_type')or'');scope_id=body.get('scope_id');validate_scope(authority,scope,scope_id,bool(body.get('broad_scope_confirmed')))
    reason=str(body.get('reason_code')or'');other=str(body.get('reason_other')or'').strip();justification=str(body.get('business_justification')or'').strip()
    if reason not in REASONS or(reason=='OTHER'and len(other)<3):raise HTTPException(400,'Select a valid reason and describe Other when selected')
    if len(justification)<10:raise HTTPException(400,'Business justification must contain at least 10 characters')
    if fetch_one("SELECT id FROM delegated_authorities WHERE delegate_employee_id=? AND authority_type=? AND scope_type=? AND COALESCE(scope_id,0)=COALESCE(?,0) AND upper(status)<>'REVOKED' AND datetime(effective_from)<datetime(?) AND datetime(effective_until)>datetime(?)",(delegate['id'],authority,scope,scope_id,end,start)):raise HTTPException(409,'A conflicting active or scheduled delegation already exists')
    year=datetime.now().year;seq=(fetch_one("SELECT COUNT(*) count FROM delegated_authorities WHERE delegation_number LIKE ?",(f'DEL-{year}-%',))or{'count':0})['count']+1;number=f'DEL-{year}-{seq:04d}'
    details={'delegation_number':number,'delegate':delegate['name'],'employee_code':delegate['employee_code'],'normal_role':delegate['approval_role'],'department':department,'authority_code':authority,'scope_type':scope,'scope_id':scope_id,'effective_from':start,'effective_until':end,'reason_code':reason,'business_justification':justification,'created_by':delegator['name']}
    with transaction(immediate=True)as c:
        cur=c.execute("""INSERT INTO delegated_authorities(delegation_number,delegator_employee_id,delegate_employee_id,delegate_role,employee_role_snapshot,department,authority_type,scope_type,scope_id,effective_from,effective_until,reason,reason_code,reason_other,business_justification,status,created_by)VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'ACTIVE',?)""",(number,delegator['id'],delegate['id'],delegate['approval_role'],delegate['approval_role'],department,authority,scope,scope_id,start,end,REASONS[reason],reason,other or None,justification,user['id']));did=cur.lastrowid
        c.execute("INSERT INTO delegated_authority_history(delegation_id,event_type,reason,changed_by,details_json)VALUES(?,'CREATED',?,?,?)",(did,justification,user['id'],json.dumps(details)));c.execute("INSERT INTO notifications(user_id,type,message,event_key,expires_at)VALUES(?,'DelegatedAuthority',?,?,?)",(delegate['user_id'],f'You have been assigned temporary {definition[1]} ({number}) for {scope}, effective {start} through {end}.',f'delegation:{did}:created',end));log_audit(c,'delegated_authorities',did,'CREATE',user['id'],after=details)
    return {'id':did,'delegation_number':number,'status':status_for({'status':'ACTIVE','effective_from':start,'effective_until':end})}
@router.put('/{delegation_id}/revoke')
def revoke(delegation_id:int,body:dict,user:dict=Depends(admin)):
    row=fetch_one("SELECT da.*,u.id delegate_user_id FROM delegated_authorities da JOIN employees e ON e.id=da.delegate_employee_id LEFT JOIN users u ON u.employee_id=e.id WHERE da.id=?",(delegation_id,));reason=str(body.get('reason')or'').strip()
    if not row:raise HTTPException(404,'Delegation not found')
    if status_for(row)not in('Active','Scheduled'):raise HTTPException(409,'Only an active or scheduled delegation may be revoked')
    if len(reason)<5:raise HTTPException(400,'A detailed revocation reason is required')
    with transaction(immediate=True)as c:
        c.execute("UPDATE delegated_authorities SET status='REVOKED',revoked_by=?,revoked_at=datetime('now'),revocation_reason=?,updated_at=datetime('now')WHERE id=?",(user['id'],reason,delegation_id));c.execute("INSERT INTO delegated_authority_history(delegation_id,event_type,reason,changed_by)VALUES(?,'REVOKED',?,?)",(delegation_id,reason,user['id']))
        if row.get('delegate_user_id'):c.execute("INSERT INTO notifications(user_id,type,message,event_key)VALUES(?,'DelegatedAuthority',?,?)",(row['delegate_user_id'],f'Delegation {row["delegation_number"]} was revoked immediately. Reason: {reason}',f'delegation:{delegation_id}:revoked'))
        log_audit(c,'delegated_authorities',delegation_id,'UPDATE',user['id'],row,{'event':'REVOKE','revocation_reason':reason})
    return {'success':True,'status':'Revoked'}
@router.put('/{delegation_id}/extend')
def extend(delegation_id:int,body:dict,user:dict=Depends(admin)):
    row=fetch_one('SELECT * FROM delegated_authorities WHERE id=?',(delegation_id,));reason=str(body.get('reason')or'').strip()
    if not row or status_for(row)not in('Active','Scheduled'):raise HTTPException(409,'Only active or scheduled delegations may be extended')
    try:new=datetime.fromisoformat(str(body.get('effective_until')or'')).replace(tzinfo=None);start=datetime.fromisoformat(row['effective_from']);old=datetime.fromisoformat(row['effective_until'])
    except ValueError:raise HTTPException(400,'Enter a valid new expiry date/time')
    if new<=old or new-start>timedelta(days=maximum_days())or len(reason)<5:raise HTTPException(400,'Extension must increase expiry, remain within the maximum period, and include a reason')
    value=new.isoformat(timespec='minutes')
    with transaction(immediate=True)as c:c.execute("UPDATE delegated_authorities SET effective_until=?,updated_at=datetime('now')WHERE id=?",(value,delegation_id));c.execute("INSERT INTO delegated_authority_history(delegation_id,event_type,previous_expiry,new_expiry,reason,changed_by)VALUES(?,'EXTENDED',?,?,?,?)",(delegation_id,row['effective_until'],value,reason,user['id']));log_audit(c,'delegated_authorities',delegation_id,'UPDATE',user['id'],row,{'event':'EXTEND','effective_until':value,'reason':reason})
    return {'success':True,'effective_until':value}
