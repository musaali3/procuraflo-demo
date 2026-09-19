import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from ..audit import log_audit
from ..database import company_base_currency, fetch_all, fetch_one, transaction
from ..security import roles

router = APIRouter(prefix='/api/employee-clearance', tags=['employee-clearance'])
Manager = Depends(roles('SupplyChainManager'))
ACTIVE = ('Clearance Requested', 'Under Clearance', 'Not Clear', 'Partially Clear', 'Clear for HR Processing')
RESOLVED = ('Resolved', 'Liability Waived', 'Recovery / Charge Approved')
REASONS = ('Resignation', 'Termination', 'Contract Completion', 'Retirement', 'Transfer / Permanent Release', 'End of Project Assignment', 'Other')


def clearance_number(connection):
    year = str(date.today().year)
    row = connection.execute("SELECT last_number FROM numbering_counters WHERE doc_type='CLR' AND year=?", (year,)).fetchone()
    sequence = int(row['last_number'] if row else 0) + 1
    connection.execute("INSERT INTO numbering_counters(doc_type,year,last_number) VALUES('CLR',?,?) ON CONFLICT(doc_type,year) DO UPDATE SET last_number=excluded.last_number", (year, sequence))
    return f'CLR-{year}-{sequence:05d}'


def employee_snapshot(connection, employee_id):
    row = connection.execute("""SELECT e.id,e.employee_code,e.name employee_name,e.position,e.employment_start_date joining_date,e.status employment_status,
        d.name department,w.name default_warehouse FROM employees e LEFT JOIN departments d ON d.id=e.department_id
        LEFT JOIN warehouses w ON w.id=e.warehouse_id WHERE e.id=? AND e.deleted_at IS NULL""", (employee_id,)).fetchone()
    return dict(row) if row else None


def _ensure_condition_liabilities(connection, clearance_id, employee_id):
    returns = connection.execute("""SELECT r.id,r.item_id,r.warehouse_id,r.condition,r.quantity,r.return_value,
        COALESCE((SELECT mii.value/NULLIF(mii.quantity,0) FROM material_issue_items mii JOIN material_issues mi ON mi.id=mii.issue_id
          WHERE mi.employee_id=r.employee_id AND mii.item_id=r.item_id AND mi.status='Posted' ORDER BY mi.id DESC,mii.id DESC LIMIT 1),i.standard_cost,0) unit_value
        FROM returns r JOIN items i ON i.id=r.item_id WHERE r.employee_id=? AND lower(COALESCE(r.condition,'good')) NOT IN('good','serviceable')""", (employee_id,)).fetchall()
    for row in returns:
        connection.execute("""INSERT OR IGNORE INTO employee_clearance_liabilities(clearance_id,employee_id,item_id,warehouse_id,source_type,source_id,condition,liability_status,liability_value)
            VALUES(?,?,?,?, 'Material Return',?,?, 'Pending Review',?)""", (clearance_id, employee_id, row['item_id'], row['warehouse_id'], row['id'], row['condition'], float(row['return_value']) if row['return_value'] is not None else float(row['quantity'] or 0) * float(row['unit_value'] or 0)))
    tools = connection.execute("""SELECT t.id,t.item_id,t.warehouse_id,h.return_condition condition,COALESCE(i.standard_cost,0) unit_value
        FROM tool_custody_history h JOIN tools t ON t.id=h.tool_id JOIN items i ON i.id=t.item_id
        WHERE h.employee_id=? AND h.status='RETURNED' AND lower(COALESCE(h.return_condition,'good')) NOT IN('good','serviceable')
        UNION SELECT t.id,t.item_id,t.warehouse_id,t.condition,COALESCE(i.standard_cost,0) FROM tools t JOIN items i ON i.id=t.item_id
        WHERE t.employee_id=? AND t.return_date IS NOT NULL AND lower(COALESCE(t.condition,'good')) NOT IN('good','serviceable')""", (employee_id,employee_id)).fetchall()
    for row in tools:
        connection.execute("""INSERT OR IGNORE INTO employee_clearance_liabilities(clearance_id,employee_id,item_id,warehouse_id,source_type,source_id,condition,liability_status,liability_value)
            VALUES(?,?,?,?, 'Tool',?,?, 'Pending Review',?)""", (clearance_id, employee_id, row['item_id'], row['warehouse_id'], row['id'], row['condition'], float(row['unit_value'] or 0)))


def calculate(connection, clearance_id, persist=True):
    clearance = connection.execute('SELECT * FROM employee_clearances WHERE id=?', (clearance_id,)).fetchone()
    if not clearance:
        raise HTTPException(404, 'Employee clearance not found')
    employee_id = clearance['employee_id']
    _ensure_condition_liabilities(connection, clearance_id, employee_id)
    issues = [dict(row) for row in connection.execute("""SELECT mii.id issue_line_id,mi.id issue_id,mi.issue_number,mi.issue_date,mii.item_id,mii.warehouse_id,
        w.name warehouse_name,i.item_code,i.description,i.category,mii.quantity qty_issued,COALESCE(mii.value/NULLIF(mii.quantity,0),i.standard_cost,0) unit_value
        FROM material_issue_items mii JOIN material_issues mi ON mi.id=mii.issue_id JOIN items i ON i.id=mii.item_id
        JOIN warehouses w ON w.id=mii.warehouse_id WHERE mi.employee_id=? AND mi.status='Posted' AND i.consumable_returnable='Returnable'
        ORDER BY mi.issue_date,mi.id,mii.id""", (employee_id,)).fetchall()]
    allocated_by_line = {row['issue_item_id']: float(row['quantity'] or 0) for row in connection.execute("""SELECT a.issue_item_id,SUM(a.transaction_quantity) quantity
        FROM employee_return_allocations a JOIN returns r ON r.id=a.return_id WHERE r.employee_id=? GROUP BY a.issue_item_id""", (employee_id,)).fetchall()}
    returned_by_item = {row['item_id']: float(row['quantity'] or 0) for row in connection.execute("""SELECT r.item_id,SUM(r.quantity) quantity FROM returns r
        WHERE r.employee_id=? AND NOT EXISTS(SELECT 1 FROM employee_return_allocations a WHERE a.return_id=r.id) GROUP BY r.item_id""", (employee_id,)).fetchall()}
    details = []
    for issue in issues:
        allocated = allocated_by_line.get(issue['issue_line_id'], 0.0)
        available = returned_by_item.get(issue['item_id'], 0.0)
        legacy_applied = min(max(0.0,float(issue['qty_issued'])-allocated), available)
        returned_by_item[issue['item_id']] = max(0.0, available - legacy_applied)
        applied = min(float(issue['qty_issued']),allocated+legacy_applied)
        outstanding = max(0.0, float(issue['qty_issued']) - applied)
        if outstanding > .000001:
            details.append({**issue, 'source_type': 'Material Issue', 'serial_asset_no': None, 'qty_returned': applied,
                'outstanding_qty': outstanding, 'return_condition': None, 'liability_status': 'Return Required',
                'outstanding_value': round(outstanding * float(issue['unit_value'] or 0), 2)})
    for row in connection.execute("""SELECT t.id tool_id,t.tool_code,t.serial_number,t.issue_date,t.item_id,t.warehouse_id,w.name warehouse_name,
        i.item_code,i.description,i.category,COALESCE(i.standard_cost,0) unit_value FROM tools t JOIN items i ON i.id=t.item_id
        JOIN warehouses w ON w.id=t.warehouse_id WHERE t.employee_id=? AND t.return_date IS NULL""", (employee_id,)).fetchall():
        tool = dict(row)
        details.append({**tool, 'source_type': 'Tool', 'issue_id': tool['tool_id'], 'issue_number': tool['tool_code'],
            'serial_asset_no': tool['serial_number'], 'qty_issued': 1, 'qty_returned': 0, 'outstanding_qty': 1,
            'return_condition': None, 'liability_status': 'Return Required', 'outstanding_value': round(float(tool['unit_value'] or 0), 2)})
    liabilities = [dict(row) for row in connection.execute("""SELECT l.*,i.item_code,i.description,w.name warehouse_name,u.full_name resolved_by_name
        FROM employee_clearance_liabilities l JOIN items i ON i.id=l.item_id LEFT JOIN warehouses w ON w.id=l.warehouse_id
        LEFT JOIN users u ON u.id=l.resolved_by WHERE l.clearance_id=? ORDER BY l.id""", (clearance_id,)).fetchall()]
    unresolved = [row for row in liabilities if row['liability_status'] not in RESOLVED]
    outstanding_value = round(sum(float(row['outstanding_value']) for row in details) + sum(float(row['liability_value'] or 0) for row in unresolved), 2)
    if not details and not unresolved:
        status = 'Clear for HR Processing'
    elif (int(clearance['initial_outstanding_item_count'] or 0) > len(details)) or any(row['liability_status'] in RESOLVED for row in liabilities):
        status = 'Partially Clear'
    else:
        status = 'Not Clear'
    if clearance['current_status'] == 'Cancelled':
        status = 'Cancelled'
    warehouse_count = connection.execute('SELECT COUNT(*) count FROM warehouses').fetchone()['count']
    if persist and status != 'Cancelled':
        cleared_at = "datetime('now')" if status == 'Clear for HR Processing' else 'NULL'
        connection.execute(f"""UPDATE employee_clearances SET current_status=?,current_outstanding_item_count=?,current_outstanding_value=?,
            unresolved_liability_count=?,unresolved_liability_value=?,warehouses_checked_count=?,clearance_date={cleared_at},updated_at=datetime('now') WHERE id=?""",
            (status, len(details), outstanding_value, len(unresolved), round(sum(float(x['liability_value'] or 0) for x in unresolved), 2), warehouse_count, clearance_id))
    warehouse_summary = {}
    for row in details:
        key = row['warehouse_id']; summary = warehouse_summary.setdefault(key, {'warehouse_id': key, 'warehouse_name': row['warehouse_name'], 'outstanding_item_lines': 0, 'outstanding_qty': 0, 'unresolved_liabilities': 0, 'outstanding_value': 0})
        summary['outstanding_item_lines'] += 1; summary['outstanding_qty'] += row['outstanding_qty']; summary['outstanding_value'] += row['outstanding_value']
    for row in unresolved:
        key = row['warehouse_id']; summary = warehouse_summary.setdefault(key, {'warehouse_id': key, 'warehouse_name': row.get('warehouse_name') or 'Unassigned', 'outstanding_item_lines': 0, 'outstanding_qty': 0, 'unresolved_liabilities': 0, 'outstanding_value': 0})
        summary['unresolved_liabilities'] += 1; summary['outstanding_value'] += float(row['liability_value'] or 0)
    return {'status': status, 'items': details, 'liabilities': liabilities, 'unresolved_liabilities': unresolved,
        'outstanding_item_count': len(details), 'unresolved_liability_count': len(unresolved), 'outstanding_value': outstanding_value,
        'warehouses_checked_count': warehouse_count, 'warehouse_summary': list(warehouse_summary.values())}


def refresh_active_for_employee(connection, employee_id):
    rows = connection.execute("SELECT id FROM employee_clearances WHERE employee_id=? AND current_status NOT IN('Cancelled','Completed') AND letter_status<>'Clearance Certificate Issued'", (employee_id,)).fetchall()
    for row in rows:
        calculate(connection, row['id'])


def detail_payload(connection, clearance_id):
    result = calculate(connection, clearance_id)
    clearance = connection.execute("""SELECT c.*,e.employee_code,e.name employee_name,e.position,d.name department,u.full_name initiated_by_name,
        CAST(julianday('now')-julianday(c.request_date) AS INTEGER) clearance_age FROM employee_clearances c JOIN employees e ON e.id=c.employee_id
        LEFT JOIN departments d ON d.id=e.department_id LEFT JOIN users u ON u.id=c.created_by WHERE c.id=?""", (clearance_id,)).fetchone()
    documents = [dict(row) for row in connection.execute("SELECT d.*,u.full_name generated_by_name FROM employee_clearance_documents d LEFT JOIN users u ON u.id=d.generated_by WHERE d.clearance_id=? ORDER BY d.id DESC", (clearance_id,)).fetchall()]
    history = [dict(row) for row in connection.execute("""SELECT a.*,u.full_name performed_by_name FROM audit_log a LEFT JOIN users u ON u.id=a.changed_by
        WHERE (a.table_name='employee_clearances' AND a.record_id=?) OR (a.table_name IN('employee_clearance_liabilities','employee_clearance_documents') AND json_extract(a.new_values,'$.clearance_id')=?) ORDER BY a.id DESC""", (clearance_id, clearance_id)).fetchall()]
    return {**dict(clearance), **result, 'documents': documents, 'audit_history': history, 'currency': company_base_currency()}


@router.get('/employees')
def employees(_user=Manager):
    return fetch_all("""SELECT e.id,e.employee_code,e.name,e.position,e.employment_start_date joining_date,e.status,d.name department,w.name default_warehouse
        FROM employees e LEFT JOIN departments d ON d.id=e.department_id LEFT JOIN warehouses w ON w.id=e.warehouse_id
        WHERE e.deleted_at IS NULL ORDER BY e.name""")


@router.get('')
def register(_user=Manager):
    with transaction() as connection:
        for row in connection.execute("SELECT id FROM employee_clearances WHERE current_status NOT IN('Cancelled','Completed') AND letter_status<>'Clearance Certificate Issued'").fetchall():
            calculate(connection, row['id'])
        return [dict(row) for row in connection.execute("""SELECT c.*,e.employee_code,e.name employee_name,e.position,d.name department,
            CAST(julianday('now')-julianday(c.request_date) AS INTEGER) clearance_age,
            (SELECT COUNT(DISTINCT warehouse_id) FROM employee_clearance_liabilities l WHERE l.clearance_id=c.id) warehouses_with_issues
            FROM employee_clearances c JOIN employees e ON e.id=c.employee_id LEFT JOIN departments d ON d.id=e.department_id ORDER BY c.id DESC""").fetchall()]


@router.post('', status_code=201)
def start_clearance(body: dict, user=Manager):
    employee_id = body.get('employee_id'); reason = str(body.get('clearance_reason') or '').strip(); comments = str(body.get('reason_comments') or '').strip()
    if not isinstance(employee_id, int): raise HTTPException(400, 'Select an employee from Employee Master')
    if reason not in REASONS: raise HTTPException(400, 'Select a valid clearance reason')
    if reason == 'Other' and not comments: raise HTTPException(400, 'Comments are required when the clearance reason is Other')
    with transaction(immediate=True) as connection:
        if not employee_snapshot(connection, employee_id): raise HTTPException(404, 'Employee not found')
        active = connection.execute("SELECT id,clearance_number FROM employee_clearances WHERE employee_id=? AND current_status NOT IN('Cancelled','Completed') AND letter_status<>'Clearance Certificate Issued'", (employee_id,)).fetchone()
        if active: raise HTTPException(409, f"An active Employee Clearance already exists for this employee. Open {active['clearance_number']}.")
        number = clearance_number(connection)
        cursor = connection.execute("""INSERT INTO employee_clearances(clearance_number,employee_id,clearance_reason,reason_comments,initial_status,current_status,created_by)
            VALUES(?,?,?,?, 'Clearance Requested','Clearance Requested',?)""", (number, employee_id, reason, comments or None, user['id']))
        result = calculate(connection, cursor.lastrowid)
        connection.execute("""UPDATE employee_clearances SET initial_status=?,initial_outstanding_item_count=?,initial_outstanding_value=? WHERE id=?""",
            (result['status'], result['outstanding_item_count'], result['outstanding_value'], cursor.lastrowid))
        log_audit(connection, 'employee_clearances', cursor.lastrowid, 'CREATE', user['id'], after={'clearance_id': cursor.lastrowid, 'event': 'Clearance Initiated / Company-wide Scan Executed', 'warehouses_checked': result['warehouses_checked_count'], 'status': result['status']})
        return {'id': cursor.lastrowid, 'clearance_number': number, **result}


@router.get('/audit-report')
def audit_report(_user=Manager):
    rows = register(_user)
    return {'rows': rows, 'summary': {'total_clearance_requests': len(rows), 'clear': sum(x['current_status']=='Clear for HR Processing' for x in rows),
        'not_clear': sum(x['current_status']=='Not Clear' for x in rows), 'partially_clear': sum(x['current_status']=='Partially Clear' for x in rows),
        'cancelled': sum(x['current_status']=='Cancelled' for x in rows), 'outstanding_company_property_value': round(sum(float(x['current_outstanding_value'] or 0) for x in rows),2),
        'over_30_days': sum(int(x['clearance_age'] or 0)>30 for x in rows)}}


@router.get('/documents/{document_id}')
def document(document_id: int, _user=Manager):
    row = fetch_one("SELECT d.*,u.full_name generated_by_name FROM employee_clearance_documents d LEFT JOIN users u ON u.id=d.generated_by WHERE d.id=?", (document_id,))
    if not row: raise HTTPException(404, 'Employee clearance document not found')
    row['snapshot'] = json.loads(row.pop('snapshot_json'))
    return row


@router.get('/{clearance_id}')
def clearance_detail(clearance_id: int, _user=Manager):
    with transaction(immediate=True) as connection:
        return detail_payload(connection, clearance_id)


@router.post('/{clearance_id}/liabilities/{liability_id}/resolve')
def resolve_liability(clearance_id: int, liability_id: int, body: dict, user=Manager):
    status = str(body.get('resolution_status') or '').strip(); reason = str(body.get('resolution_reason') or '').strip(); reference = str(body.get('resolution_reference') or '').strip()
    if status not in RESOLVED: raise HTTPException(400, 'Select a valid liability resolution status')
    if not reason: raise HTTPException(400, 'A liability resolution reason is required')
    with transaction(immediate=True) as connection:
        row = connection.execute('SELECT * FROM employee_clearance_liabilities WHERE id=? AND clearance_id=?', (liability_id, clearance_id)).fetchone()
        if not row: raise HTTPException(404, 'Employee property liability not found')
        connection.execute("UPDATE employee_clearance_liabilities SET liability_status=?,resolution_reason=?,resolution_reference=?,resolved_by=?,resolved_at=datetime('now') WHERE id=?", (status, reason, reference or None, user['id'], liability_id))
        result = calculate(connection, clearance_id)
        log_audit(connection, 'employee_clearance_liabilities', liability_id, 'UPDATE', user['id'], dict(row), {'clearance_id': clearance_id, 'event': 'Liability Resolved', 'liability_status': status, 'resolution_reason': reason, 'resolution_reference': reference, 'clearance_status': result['status']})
        return result


@router.post('/{clearance_id}/cancel')
def cancel(clearance_id: int, body: dict, user=Manager):
    reason = str(body.get('cancellation_reason') or '').strip()
    if not reason: raise HTTPException(400, 'A cancellation reason is required')
    with transaction(immediate=True) as connection:
        row = connection.execute('SELECT * FROM employee_clearances WHERE id=?', (clearance_id,)).fetchone()
        if not row: raise HTTPException(404, 'Employee clearance not found')
        if row['current_status'] == 'Cancelled': raise HTTPException(409, 'Employee clearance is already cancelled')
        connection.execute("UPDATE employee_clearances SET current_status='Cancelled',cancellation_reason=?,cancelled_by=?,cancelled_at=datetime('now'),updated_at=datetime('now') WHERE id=?", (reason, user['id'], clearance_id))
        log_audit(connection, 'employee_clearances', clearance_id, 'UPDATE', user['id'], dict(row), {'clearance_id': clearance_id, 'event': 'Clearance Cancelled', 'cancellation_reason': reason})
    return {'success': True, 'status': 'Cancelled'}


@router.post('/{clearance_id}/documents', status_code=201)
def generate_document(clearance_id: int, body: dict, user=Manager):
    requested = str(body.get('document_type') or '').strip()
    if requested not in ('Clearance Certificate', 'Clearance Status'): raise HTTPException(400, 'Select a valid document type')
    with transaction(immediate=True) as connection:
        result = calculate(connection, clearance_id)
        clearance = connection.execute('SELECT * FROM employee_clearances WHERE id=?', (clearance_id,)).fetchone()
        if clearance['current_status'] == 'Cancelled': raise HTTPException(409, 'Cancelled clearances cannot issue new documents')
        if requested == 'Clearance Certificate' and result['status'] != 'Clear for HR Processing':
            log_audit(connection, 'employee_clearances', clearance_id, 'UPDATE', user['id'], after={'clearance_id': clearance_id, 'event': 'Final Verification Failed', 'status': result['status']})
            connection.commit()
            raise HTTPException(409, 'Clearance status has changed. An outstanding returnable item or liability was identified during final verification. Review the employee clearance before generating the certificate.')
        if requested == 'Clearance Certificate' and connection.execute("SELECT 1 FROM employee_clearance_documents WHERE clearance_id=? AND document_type='Clearance Certificate'", (clearance_id,)).fetchone():
            raise HTTPException(409, 'The final Clearance Certificate has already been issued for this clearance cycle')
        if requested == 'Clearance Status' and result['status'] == 'Clear for HR Processing': raise HTTPException(409, 'Generate the final Clearance Certificate for an employee who is clear')
        number = clearance_number(connection); company = connection.execute('SELECT * FROM company WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 1').fetchone()
        employee = employee_snapshot(connection, clearance['employee_id']); signer = connection.execute("SELECT u.full_name,e.position,e.signature_url FROM users u LEFT JOIN employees e ON e.id=u.employee_id WHERE u.id=?", (user['id'],)).fetchone()
        snapshot = {'company': dict(company) if company else {}, 'employee': employee, 'clearance': dict(clearance), 'verification': result,
            'generated_by': dict(signer) if signer else {'full_name': user['full_name']}, 'currency': company_base_currency()}
        cursor = connection.execute("INSERT INTO employee_clearance_documents(clearance_id,document_number,document_type,status_snapshot,snapshot_json,total_outstanding_value_snapshot,generated_by) VALUES(?,?,?,?,?,?,?)",
            (clearance_id, number, requested, result['status'], json.dumps(snapshot, default=str), result['outstanding_value'], user['id']))
        letter_status = 'Clearance Certificate Issued' if requested == 'Clearance Certificate' else 'Status Letter Issued'
        connection.execute("UPDATE employee_clearances SET letter_status=?,final_verification_at=CASE WHEN ?='Clearance Certificate' THEN datetime('now') ELSE final_verification_at END,updated_at=datetime('now') WHERE id=?", (letter_status, requested, clearance_id))
        log_audit(connection, 'employee_clearance_documents', cursor.lastrowid, 'CREATE', user['id'], after={'clearance_id': clearance_id, 'event': f'{requested} Generated', 'document_number': number})
        return {'id': cursor.lastrowid, 'document_number': number, 'document_type': requested, 'snapshot': snapshot}
