import json
import os
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .database import fetch_all, fetch_one
from .permissions import defaults_for_role

bearer = HTTPBearer(auto_error=False)
JWT_SECRET = os.getenv('JWT_SECRET', 'dev-secret-change-me').strip() or 'dev-secret-change-me'
JWT_ALGORITHM = 'HS256'
REQUIRED_TOKEN_CLAIMS = ['exp', 'iat', 'id', 'tenant_key', 'session_epoch']

def authorized_warehouse_ids(user_id: int):
    role = fetch_one('SELECT role FROM users WHERE id=?', (user_id,))
    if role and role.get('role') == 'SupplyChainManager':
        return [int(row['id']) for row in fetch_all('SELECT id FROM warehouses WHERE deleted_at IS NULL ORDER BY id')]
    rows = fetch_all('''SELECT uwa.warehouse_id FROM user_warehouse_assignments uwa JOIN warehouses w ON w.id=uwa.warehouse_id
        WHERE uwa.user_id=? AND uwa.is_active=1 AND uwa.warehouse_id IS NOT NULL AND w.deleted_at IS NULL ORDER BY uwa.warehouse_id''', (user_id,))
    if rows:
        return [int(row['warehouse_id']) for row in rows]
    user = fetch_one('SELECT u.warehouse_id FROM users u JOIN warehouses w ON w.id=u.warehouse_id WHERE u.id=? AND w.deleted_at IS NULL', (user_id,))
    return [int(user['warehouse_id'])] if user and user.get('warehouse_id') is not None else []

def sign_token(payload: dict):
    data = dict(payload)
    data.setdefault('tenant_key','default')
    maintenance=fetch_one('SELECT session_epoch FROM system_maintenance WHERE id=1')or{'session_epoch':1}
    data['session_epoch']=int(maintenance['session_epoch']);data['iat']=datetime.now(timezone.utc)
    data['exp'] = datetime.now(timezone.utc) + timedelta(hours=8)
    return jwt.encode(data, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_token(token: str) -> dict:
    """Verify a Procuraflo token before any claim is used for tenant selection."""
    decoded = jwt.decode(
        token,
        JWT_SECRET,
        algorithms=[JWT_ALGORITHM],
        options={'require': REQUIRED_TOKEN_CLAIMS},
    )
    if not isinstance(decoded.get('id'), int) or not str(decoded.get('tenant_key') or '').strip():
        raise jwt.InvalidTokenError('Invalid authentication context')
    return decoded

def permission_keys(user: dict):
    if user['role'] == 'SupplyChainManager':
        return defaults_for_role(user['role'])
    row = fetch_one('SELECT e.permission_keys FROM users u LEFT JOIN employees e ON e.id=u.employee_id WHERE u.id=?', (user['id'],))
    try:
        return json.loads(row['permission_keys']) if row and row.get('permission_keys') else defaults_for_role(user['role'])
    except (ValueError, TypeError):
        return defaults_for_role(user['role'])

def current_user(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if not credentials:
        raise HTTPException(401, 'Missing or invalid Authorization header')
    try:
        decoded = decode_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(401, 'Invalid or expired token')
    maintenance=fetch_one('SELECT active_yn,session_epoch FROM system_maintenance WHERE id=1')or{'active_yn':0,'session_epoch':1}
    if maintenance['active_yn']:raise HTTPException(503,'Procuraflo is temporarily unavailable while the scheduled month-end backup is being completed')
    if int(decoded.get('session_epoch')or 0)!=int(maintenance['session_epoch']):raise HTTPException(401,'Your session ended for controlled system maintenance. Sign in again.')
    account = fetch_one('''SELECT u.id,u.username,u.role,u.full_name,u.is_active,u.locked_reason,u.deleted_at,
        u.password_expires_at,e.id employee_id,e.approval_limit,e.status employee_status,e.system_access_yn,e.signature_url,d.name department_name
        FROM users u LEFT JOIN employees e ON e.id=u.employee_id LEFT JOIN departments d ON d.id=e.department_id WHERE u.id=?''', (decoded.get('id'),))
    if not account or account['deleted_at'] or not account['is_active']:
        raise HTTPException(401, 'Account is inactive or no longer available')
    if account['role'].lower() == 'finance' or str(account.get('department_name') or '').strip().lower() == 'finance' or account.get('system_access_yn') == 0 or account.get('employee_status') == 'Inactive':
        raise HTTPException(403, 'This employee has no Procuraflo system access')
    if account.get('locked_reason'):
        raise HTTPException(423, f"Account temporarily locked: {account['locked_reason']}")
    account['permission_keys'] = permission_keys(account)
    account['warehouse_ids'] = authorized_warehouse_ids(account['id'])
    account['tenant_key']=decoded['tenant_key']
    return account

User = Annotated[dict, Depends(current_user)]

def roles(*allowed):
    def dependency(user: User):
        if user['role'] not in allowed:
            raise HTTPException(403, f"Role '{user['role']}' is not permitted to perform this action")
        return user
    return dependency
