from fastapi import HTTPException

from .database import fetch_one


def allows_self_approval(user):
    """SCM may approve their own work; other workflow controls still apply."""
    return user.get('role') == 'SupplyChainManager'


def employee_for_user(user):
    return fetch_one("""SELECT e.*,u.id user_id,u.role user_role FROM users u JOIN employees e ON e.id=u.employee_id
        WHERE u.id=? AND u.is_active=1 AND u.deleted_at IS NULL AND e.status='Active'
        AND e.deleted_at IS NULL AND e.system_access_yn=1""", (user['id'],))


def material_issue_limit(employee_id, warehouse_id):
    row=fetch_one("""SELECT value_limit FROM material_issue_authorization_limits
        WHERE employee_id=? AND active_yn=1 AND date(effective_from)<=date('now')
        AND (expiry_date IS NULL OR date(expiry_date)>=date('now'))
        AND (warehouse_id=? OR warehouse_id IS NULL)
        ORDER BY CASE WHEN warehouse_id=? THEN 0 ELSE 1 END, effective_from DESC,id DESC LIMIT 1""",
        (employee_id,warehouse_id,warehouse_id))
    return float(row['value_limit'] or 0) if row else None


def employee_limit(employee, document_type, warehouse_id=None):
    if not employee:return 0.0
    if document_type=='ISSUE':
        configured=material_issue_limit(employee['id'],warehouse_id)
        if configured is not None:return configured
    return float(employee.get('approval_limit')or 0)


def active_manager(employee_id):
    return fetch_one("""SELECT manager.*,u.id user_id,u.role user_role FROM employees employee
        JOIN employees manager ON manager.id=employee.reports_to_employee_id
        JOIN users u ON u.employee_id=manager.id AND u.is_active=1 AND u.deleted_at IS NULL
        WHERE employee.id=? AND manager.status='Active' AND manager.deleted_at IS NULL
        AND manager.system_access_yn=1""",(employee_id,))


def final_scm():
    return fetch_one("""SELECT e.*,u.id user_id,u.role user_role FROM users u JOIN employees e ON e.id=u.employee_id
        WHERE u.role='SupplyChainManager' AND u.is_active=1 AND u.deleted_at IS NULL
        AND e.status='Active' AND e.deleted_at IS NULL AND e.system_access_yn=1 ORDER BY e.id LIMIT 1""")


def warehouse_authorized(employee,warehouse_id):
    if employee.get('user_role')=='SupplyChainManager':return True
    return bool(fetch_one("""SELECT 1 ok FROM users u WHERE u.id=? AND (u.warehouse_id=? OR EXISTS(
        SELECT 1 FROM user_warehouse_assignments uwa WHERE uwa.user_id=u.id AND uwa.warehouse_id=? AND uwa.is_active=1))""",
        (employee['user_id'],warehouse_id,warehouse_id)))


def route_approver(requester_employee_id,value,document_type,warehouse_id=None):
    current_id=requester_employee_id;visited=set();level=1
    while current_id and current_id not in visited:
        visited.add(current_id);manager=active_manager(current_id)
        if not manager:break
        limit=employee_limit(manager,document_type,warehouse_id)
        if (document_type!='ISSUE' or warehouse_authorized(manager,warehouse_id)) and (manager['user_role']=='SupplyChainManager' or limit>=value):
            return manager,limit,level,'REPORTING_LINE'
        current_id=manager['id'];level+=1
    scm=final_scm()
    if not scm:raise HTTPException(409,'No active Supply Chain Manager is available for final approval routing')
    return scm,employee_limit(scm,document_type,warehouse_id),level,'INACTIVE_OR_INSUFFICIENT_MANAGER_ESCALATION'


def approval_authorized(user,requester_user_id,value,document_type,warehouse_id=None,pending=None):
    employee=employee_for_user(user)
    if not employee:raise HTTPException(403,'An active Supply Chain employee record is required')
    own_limit=employee_limit(employee,document_type,warehouse_id)
    if allows_self_approval(user):return employee,own_limit,'SCM_SELF_APPROVAL' if requester_user_id==user['id'] else 'FINAL_AUTHORITY'
    if requester_user_id==user['id'] and value<=own_limit:return employee,own_limit,'SELF_WITHIN_ASSIGNED_LIMIT'
    if pending and pending.get('approver_employee_id')==employee['id'] and value<=own_limit:return employee,own_limit,'ROUTED_APPROVER'
    raise HTTPException(403,'This document is above your assigned limit or routed to another approver')
