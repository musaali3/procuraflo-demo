import json
import sqlite3
from datetime import datetime, timezone

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request

from ..audit import log_audit
from ..database import fetch_all, fetch_one, transaction
from ..permissions import defaults_for_role
from ..security import User, authorized_warehouse_ids, permission_keys, roles, sign_token
from ..tenancy import company_registration_status, normalize_tenant_key, provision_tenant, register_tenant, tenant_database, tenant_database_for_registration

router = APIRouter(prefix='/api/auth', tags=['auth'])
VALID_ROLES = ['SupplyChainManager','PurchaseManager','PurchaseOfficer','WarehouseManager','WarehouseSupervisor','Storekeeper']

@router.post('/login')
def login(body: dict, request: Request):
    try:tenant_key=normalize_tenant_key(body.get('company_key')or request.headers.get('x-company-key')or'default')
    except ValueError as error:raise HTTPException(400,str(error))
    try:
        with tenant_database(tenant_key):return _login_in_active_tenant(body,request,tenant_key)
    except LookupError:raise HTTPException(401,'Invalid company login ID, username, or password')

def _login_in_active_tenant(body:dict,request:Request,tenant_key:str):
    maintenance=fetch_one('SELECT active_yn FROM system_maintenance WHERE id=1')or{}
    if maintenance.get('active_yn'):raise HTTPException(503,'SYSTEM MAINTENANCE — Month-End Backup in Progress. Please wait until the backup is complete.')
    username, password = str(body.get('username') or '').strip(), str(body.get('password') or '')
    if not username or not password:
        raise HTTPException(400, 'Username and password required')
    failures = fetch_one("SELECT COUNT(*) count FROM login_history WHERE lower(username_attempted)=lower(?) AND success=0 AND created_at>=datetime('now','-15 minutes')", (username,))['count']
    if failures >= 5:
        raise HTTPException(429, 'Too many failed login attempts. Try again after 15 minutes or contact the Supply Chain Manager.')
    user = fetch_one('SELECT * FROM users WHERE lower(username)=lower(?) AND deleted_at IS NULL', (username,))
    access = fetch_one('SELECT e.status,e.system_access_yn,e.signature_url,d.name department_name FROM employees e LEFT JOIN departments d ON d.id=e.department_id WHERE e.id=? AND e.deleted_at IS NULL', (user['employee_id'],)) if user else None
    finance = bool(user and (user['role'].lower() == 'finance' or str((access or {}).get('department_name') or '').strip().lower() == 'finance'))
    valid = bool(user and user['is_active'] and access and access['status'] == 'Active' and access.get('system_access_yn') != 0 and not finance and bcrypt.checkpw(password.encode(), user['password_hash'].encode()))
    with transaction(immediate=True) as connection:
        connection.execute('INSERT INTO login_history(user_id,username_attempted,success) VALUES(?,?,?)', (user['id'] if user else None, username, int(valid)))
    if not valid:
        if user and (not user['is_active'] or finance or not access or access.get('system_access_yn') == 0 or access.get('status') != 'Active'):
            raise HTTPException(403, 'This employee has no Procuraflo system access')
        raise HTTPException(401, 'Invalid username or password')
    if user.get('locked_reason'):
        raise HTTPException(423, f"Account temporarily locked: {user['locked_reason']}. Contact the Supply Chain Manager.")
    ids = authorized_warehouse_ids(user['id'])
    payload = {'id': user['id'], 'username': user['username'], 'role': user['role'], 'full_name': user['full_name'], 'tenant_key':tenant_key,
               'warehouse_id': ids[0] if len(ids) == 1 else user.get('warehouse_id'), 'warehouse_ids': ids,
               'warehouse_name': (fetch_one('SELECT name FROM warehouses WHERE id=?', (user.get('warehouse_id'),)) or {}).get('name'),
               'permission_keys': permission_keys(user), 'signature_url': access.get('signature_url'), 'must_change_password': bool(user.get('must_change_password')),
               'password_expires_at': user.get('password_expires_at'), 'password_days_remaining': None}
    with transaction(immediate=True) as connection:
        connection.execute("INSERT INTO user_activity_log(user_id,full_name,username,role,event_type,current_action,ip_address) VALUES(?,?,?,?,'Login','Signed in',?)", (user['id'], user['full_name'], user['username'], user['role'], request.client.host if request.client else None))
    return {'token': sign_token(payload), 'user': payload}

@router.post('/register-company',status_code=201)
def register_company(body:dict):
    if not company_registration_status()['registration_enabled']:
        raise HTTPException(403,'Company registration is closed for this installation')
    company_name=str(body.get('company_name')or'').strip();admin_name=str(body.get('admin_name')or'').strip();username=str(body.get('username')or'').strip();password=str(body.get('password')or'')
    if len(company_name)<3 or len(admin_name)<3 or len(username)<3:raise HTTPException(400,'Company name, administrator name, and username must each contain at least 3 characters')
    if len(password)<10:raise HTTPException(400,'Administrator password must contain at least 10 characters')
    try:key=normalize_tenant_key(body.get('company_key')or company_name)
    except ValueError as error:raise HTTPException(400,str(error))
    target=None
    try:
        target=provision_tenant(key,company_name)
        with tenant_database_for_registration(target):
            from ..database import ensure_company_employee_schema
            ensure_company_employee_schema()
            hashed=bcrypt.hashpw(password.encode(),bcrypt.gensalt(rounds=12)).decode()
            with transaction(immediate=True)as connection:
                selected_currency=str(body.get('base_currency')or'SAR').strip().upper()
                connection.execute("INSERT INTO company(name,email,phone,country_code,currency,base_currency,time_zone,financial_year)VALUES(?,?,?,?,?,?,?,?)",(company_name,str(body.get('company_email')or'').strip()or None,str(body.get('company_phone')or'').strip()or None,str(body.get('country_code')or'SA'),selected_currency,selected_currency,str(body.get('time_zone')or'Asia/Riyadh'),str(body.get('financial_year')or'')))
                department=connection.execute("SELECT id FROM departments WHERE lower(name)='procurement' AND deleted_at IS NULL LIMIT 1").fetchone()
                department_id=department['id']if department else connection.execute("INSERT INTO departments(name)VALUES('Procurement')").lastrowid
                manager_permissions=json.dumps(defaults_for_role('SupplyChainManager'))
                employee_id=connection.execute("""INSERT INTO employees(
                  employee_code,name,department_id,position,status,approval_role,approval_limit,permission_keys,system_access_yn,email
                )VALUES('EMP-0001',?,?,'Supply Chain Manager','Active','SupplyChainManager',0,?,1,?)""",
                  (admin_name,department_id,manager_permissions,str(body.get('admin_email')or'').strip()or None)).lastrowid
                connection.execute("INSERT INTO users(employee_id,username,password_hash,full_name,role,is_active,must_change_password,password_changed_at,password_expires_at)VALUES(?,?,?,?, 'SupplyChainManager',1,0,datetime('now'),datetime('now','+90 days'))",(employee_id,username,hashed,admin_name))
        register_tenant(key,company_name,target)
    except FileExistsError as error:
        if target and target.exists():target.unlink(missing_ok=True)
        status_code=403 if 'registration is closed' in str(error).lower() else 409
        raise HTTPException(status_code,str(error))
    except sqlite3.IntegrityError:
        if target and target.exists():target.unlink(missing_ok=True)
        raise HTTPException(409,'Company login ID, company name, or administrator username is already registered')
    except Exception:
        if target and target.exists():target.unlink(missing_ok=True)
        raise
    return {'company_key':key,'company_name':company_name,'message':'Company registered. Sign in with the company login ID and administrator account.'}

@router.get('/registration-status')
def registration_status():
    return company_registration_status()

@router.get('/me')
def me(user: User):
    result = fetch_one('SELECT u.id,u.username,u.role,u.full_name,u.employee_id,u.warehouse_id,w.name warehouse_name,u.must_change_password,u.password_expires_at,e.signature_url FROM users u LEFT JOIN warehouses w ON w.id=u.warehouse_id LEFT JOIN employees e ON e.id=u.employee_id WHERE u.id=?', (user['id'],)) or user
    result['tenant_key']=user['tenant_key']
    result['permission_keys'] = permission_keys(user)
    result['warehouse_ids'] = authorized_warehouse_ids(user['id'])
    result['must_change_password'] = bool(result.get('must_change_password'))
    return result

@router.put('/change-password')
def change_password(body: dict, user: User):
    current, new = body.get('current_password'), body.get('new_password')
    if not current or not new or len(str(new)) < 8:
        raise HTTPException(400, 'Current password and a new password of at least 8 characters are required')
    row = fetch_one('SELECT * FROM users WHERE id=?', (user['id'],))
    if not bcrypt.checkpw(str(current).encode(), row['password_hash'].encode()):
        raise HTTPException(400, 'Current password is incorrect')
    if bcrypt.checkpw(str(new).encode(), row['password_hash'].encode()):
        raise HTTPException(400, 'New password must be different')
    hashed = bcrypt.hashpw(str(new).encode(), bcrypt.gensalt(rounds=10)).decode()
    with transaction(immediate=True) as connection:
        connection.execute("UPDATE users SET password_hash=?,must_change_password=0,password_changed_at=datetime('now'),password_expires_at=datetime('now','+90 days'),locked_reason=NULL WHERE id=?", (hashed, user['id']))
        log_audit(connection, 'users', user['id'], 'UPDATE', user['id'], after={'action':'password_changed'})
    return {'success': True}

@router.get('/users')
def users(_user: dict = Depends(roles('SupplyChainManager'))):
    return fetch_all('SELECT id,username,full_name,role,is_active,must_change_password,password_expires_at,locked_reason,created_at FROM users WHERE deleted_at IS NULL ORDER BY id')

@router.post('/users', status_code=201)
def create_user(body: dict, user: dict = Depends(roles('SupplyChainManager'))):
    if not all(body.get(k) for k in ('username','password','full_name','role')): raise HTTPException(400, 'All fields required')
    if body['role'] not in VALID_ROLES: raise HTTPException(400, 'Invalid role')
    if len(str(body['password'])) < 8: raise HTTPException(400, 'Password must contain at least 8 characters')
    hashed = bcrypt.hashpw(str(body['password']).encode(), bcrypt.gensalt(rounds=10)).decode()
    with transaction(immediate=True) as connection:
        cursor = connection.execute("INSERT INTO users(username,password_hash,full_name,role,must_change_password,password_changed_at,password_expires_at) VALUES(?,?,?,?,1,datetime('now'),datetime('now','+7 days'))", (str(body['username']).strip(), hashed, str(body['full_name']).strip(), body['role']))
        log_audit(connection, 'users', cursor.lastrowid, 'CREATE', user['id'], after={k: body[k] for k in ('username','full_name','role')})
    return {'id': cursor.lastrowid, 'username': body['username'], 'full_name': body['full_name'], 'role': body['role']}

@router.put('/users/{user_id}/status')
def status(user_id: int, body: dict, user: dict = Depends(roles('SupplyChainManager'))):
    if user_id == user['id'] and not body.get('is_active'): raise HTTPException(409, 'You cannot deactivate your own logged-in account')
    with transaction(immediate=True) as connection: connection.execute('UPDATE users SET is_active=? WHERE id=?', (int(bool(body.get('is_active'))), user_id))
    return {'success': True}

@router.put('/users/{user_id}/unlock')
def unlock(user_id: int, user: dict = Depends(roles('SupplyChainManager'))):
    if not fetch_one('SELECT id FROM users WHERE id=?', (user_id,)): raise HTTPException(404, 'User not found')
    with transaction(immediate=True) as connection: connection.execute("UPDATE users SET locked_reason=NULL,is_active=1,must_change_password=1,password_expires_at=datetime('now','+7 days') WHERE id=?", (user_id,))
    return {'success': True}

@router.get('/login-history')
def history(_user: dict = Depends(roles('SupplyChainManager'))):
    return fetch_all('SELECT * FROM login_history ORDER BY id DESC LIMIT 200')
