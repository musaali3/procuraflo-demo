from dataclasses import dataclass
from decimal import Decimal

from .calculations import decimal_value, money
from .database import fetch_one
from .approval_routing import active_manager, employee_for_user, final_scm, warehouse_authorized


@dataclass(frozen=True)
class ApprovalDecision:
    outcome: str
    employee_id: int
    user_id: int
    role: str
    limit: Decimal
    authority_reference: str
    level: int = 0
    rule: str = 'EMPLOYEE_SPECIFIC_AUTHORITY'


def _active_limit(employee, document_type, warehouse_id=None):
    approval_type = 'PO' if document_type in ('PO', 'PR', 'ADJUSTMENT') else document_type
    row = fetch_one("""SELECT id,new_limit FROM approval_limit_history
        WHERE employee_id=? AND approval_type=? AND status='ACTIVE'
        AND (effective_from IS NULL OR date(effective_from)<=date('now'))
        AND (expiry_date IS NULL OR date(expiry_date)>=date('now'))
        ORDER BY COALESCE(effective_from,'' ) DESC,id DESC LIMIT 1""",
        (employee['id'], approval_type))
    if row:
        return decimal_value(row['new_limit']), f'APPROVAL_LIMIT_HISTORY:{row["id"]}'
    configured=fetch_one('SELECT id FROM approval_limit_history WHERE employee_id=? AND approval_type=? LIMIT 1',(employee['id'],approval_type))
    if configured:
        return Decimal('0'), f'NO_ACTIVE_{approval_type}_AUTHORITY'
    return decimal_value(employee.get('approval_limit') or 0), f'EMPLOYEE:{employee["id"]}:LEGACY_LIMIT'


def evaluate_authority(user, value, document_type, warehouse_id=None):
    """Single source of truth for creator auto-approval and escalation routing."""
    requester = employee_for_user(user)
    if not requester:
        return None
    amount = money(value)
    limit, reference = _active_limit(requester, document_type, warehouse_id)
    warehouse_ok = document_type != 'ISSUE' or warehouse_authorized(requester, warehouse_id)
    if warehouse_ok and amount <= limit:
        return ApprovalDecision('AUTO_APPROVED_WITHIN_AUTHORITY', requester['id'], requester['user_id'], requester['user_role'], limit, reference)

    current_id, visited, level = requester['id'], set(), 1
    while current_id and current_id not in visited:
        visited.add(current_id)
        manager = active_manager(current_id)
        if not manager:
            break
        manager_limit, manager_ref = _active_limit(manager, document_type, warehouse_id)
        if (document_type != 'ISSUE' or warehouse_authorized(manager, warehouse_id)) and amount <= manager_limit:
            return ApprovalDecision('PENDING_APPROVAL', manager['id'], manager['user_id'], manager['user_role'], manager_limit, manager_ref, level, 'REPORTING_LINE_ESCALATION')
        current_id, level = manager['id'], level + 1

    scm = final_scm()
    if not scm:
        return None
    scm_limit, scm_ref = _active_limit(scm, document_type, warehouse_id)
    outcome = 'PENDING_EXTERNAL_APPROVAL' if amount > scm_limit else 'PENDING_APPROVAL'
    return ApprovalDecision(outcome, scm['id'], scm['user_id'], scm['user_role'], scm_limit, scm_ref, level, 'ESCALATED_ABOVE_AUTHORITY')
