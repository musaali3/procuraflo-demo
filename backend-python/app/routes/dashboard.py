from ..pr_workflow import scoped_report
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request

from ..database import fetch_all, fetch_one, transaction
from ..security import User, roles
from ..backup_service import backup_schedule

router = APIRouter(prefix='/api/dashboard', tags=['dashboard'])


def warehouse_filter(user, column):
    if user['role'] == 'SupplyChainManager':
        return '1=1', []
    ids = [int(value) for value in user.get('warehouse_ids', [])]
    return f"{column} IN ({','.join('?' for _ in ids) or 'NULL'})", ids


def dashboard_period(value: str | None):
    period = str(value or 'this_month').strip().lower()
    if period not in {'this_month', 'last_month', 'this_quarter', 'this_year'}:
        raise HTTPException(422, 'Unsupported dashboard period')
    today = date.today()
    month_start = today.replace(day=1)
    if period == 'this_month':
        start = month_start
    elif period == 'last_month':
        start = date(month_start.year - (1 if month_start.month == 1 else 0), 12 if month_start.month == 1 else month_start.month - 1, 1)
    elif period == 'this_quarter':
        start = date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
    else:
        start = date(today.year, 1, 1)
    if period == 'last_month':
        end = month_start
    elif period == 'this_quarter':
        end_month = start.month + 3
        end = date(start.year + (1 if end_month > 12 else 0), end_month - 12 if end_month > 12 else end_month, 1)
    elif period == 'this_year':
        end = date(today.year + 1, 1, 1)
    else:
        end = date(today.year + (1 if today.month == 12 else 0), 1 if today.month == 12 else today.month + 1, 1)
    return period, start.isoformat(), end.isoformat()


def dashboard_warehouse_filter(user, column: str, warehouse_id: str | None):
    value = str(warehouse_id or 'all').strip().lower()
    if value in {'', 'all'}:
        return warehouse_filter(user, column)
    try:
        selected = int(value)
    except ValueError:
        raise HTTPException(422, 'warehouse_id must be "all" or an active warehouse ID')
    warehouse = fetch_one('SELECT id FROM warehouses WHERE id=? AND deleted_at IS NULL', (selected,))
    if not warehouse:
        raise HTTPException(404, 'Warehouse not found')
    if user['role'] != 'SupplyChainManager' and selected not in [int(item) for item in user.get('warehouse_ids', [])]:
        raise HTTPException(403, 'Warehouse access denied')
    return f'{column}=?', [selected]


def filtered_month_series(rows, fields, start_date: str, end_date: str):
    found = {row['month']: row for row in rows}
    year, month = map(int, start_date[:7].split('-'))
    end_key = end_date[:7]
    result = []
    while f'{year:04d}-{month:02d}' < end_key:
        key = f'{year:04d}-{month:02d}'
        result.append({'month': key, 'label': key, **{field: round(float(found.get(key, {}).get(field) or 0), 2) for field in fields}})
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return result


def month_series(rows, fields):
    found = {row['month']: row for row in rows}
    months = fetch_all("""WITH RECURSIVE m(month,n) AS (
        SELECT strftime('%Y-%m','now','start of month','-5 months'),0 UNION ALL
        SELECT strftime('%Y-%m',month||'-01','+1 month'),n+1 FROM m WHERE n<5)
        SELECT month FROM m ORDER BY month""")
    return [{'month': m['month'], 'label': m['month'], **{
        field: round(float(found.get(m['month'], {}).get(field) or 0), 2) for field in fields
    }} for m in months]


@router.post('/activity/heartbeat')
def heartbeat(body: dict, request: Request, user: User):
    path = str(body.get('page_path') or '/').split('?')[0]
    with transaction(immediate=True) as connection:
        prior = connection.execute('SELECT page_path FROM user_activity WHERE user_id=?', (user['id'],)).fetchone()
        connection.execute("""INSERT INTO user_activity(user_id,last_seen,page_path,current_action,ip_address,user_agent)
            VALUES(?,datetime('now'),?,'Working in Procuraflo',?,?) ON CONFLICT(user_id) DO UPDATE SET
            last_seen=datetime('now'),page_path=excluded.page_path,current_action=excluded.current_action,
            ip_address=excluded.ip_address,user_agent=excluded.user_agent""",
            (user['id'], path, request.client.host if request.client else None, str(request.headers.get('user-agent', ''))[:300]))
        if not prior or prior['page_path'] != path:
            connection.execute("""INSERT INTO user_activity_log(user_id,full_name,username,role,event_type,current_action,page_path,ip_address)
                VALUES(?,?,?,?,'Page View','Working in Procuraflo',?,?)""",
                (user['id'], user['full_name'], user['username'], user['role'], path, request.client.host if request.client else None))
    return {'success': True}


@router.post('/activity/logout')
def logout(user: User):
    with transaction(immediate=True) as connection:
        connection.execute("UPDATE user_activity SET last_seen=datetime('now','-1 day'),current_action='Signed out' WHERE user_id=?", (user['id'],))
        connection.execute("INSERT INTO user_activity_log(user_id,full_name,username,role,event_type,current_action) VALUES(?,?,?,?,'Logout','Signed out')", (user['id'], user['full_name'], user['username'], user['role']))
    return {'success': True}


@router.get('/activity/live')
def live(_user: dict = Depends(roles('SupplyChainManager'))):
    return {'generated_at': fetch_one("SELECT datetime('now') value")['value'], 'users': fetch_all("""SELECT u.id,u.full_name,u.username,u.role,u.is_active,u.locked_reason,e.employee_code,d.name department_name,w.name warehouse_name,a.last_seen,a.page_path,a.current_action,CASE WHEN a.last_seen IS NULL OR (julianday('now')-julianday(a.last_seen))*86400>300 THEN 'Offline' WHEN (julianday('now')-julianday(a.last_seen))*86400>60 THEN 'Away' ELSE 'Online' END activity_status,MAX(0,CAST((julianday('now')-julianday(a.last_seen))*86400 AS INTEGER)) seconds_since_activity FROM users u LEFT JOIN employees e ON e.id=u.employee_id LEFT JOIN departments d ON d.id=e.department_id LEFT JOIN warehouses w ON w.id=COALESCE(u.warehouse_id,e.warehouse_id) LEFT JOIN user_activity a ON a.user_id=u.id WHERE u.deleted_at IS NULL ORDER BY a.last_seen DESC,u.full_name""")}


@router.get('/notifications')
def notifications(user: User):
    return scoped_report('SELECT * FROM notifications WHERE user_id=? OR user_id IS NULL ORDER BY id DESC LIMIT 50',user,(user['id'],))


@router.put('/notifications/{notification_id}/read')
def read_notification(notification_id: int, user: User):
    with transaction(immediate=True) as connection:
        cursor = connection.execute('UPDATE notifications SET is_read=1 WHERE id=? AND(user_id=? OR user_id IS NULL)', (notification_id, user['id']))
        if not cursor.rowcount:
            raise HTTPException(404, 'Notification not found')
    return {'success': True}


@router.get('/tasks')
def tasks(user: User):
    fetch_all=lambda sql,parameters=():scoped_report(sql,user,parameters)
    result = []
    if user['role'] in ['PurchaseManager', 'SupplyChainManager']:
        result += [dict(type='PO approval', priority='High', **row) for row in fetch_all("SELECT id,po_number number,total_amount,status,created_at due_date FROM purchase_orders WHERE status='PendingApproval' ORDER BY created_at")]
        result += [dict(type='PR review', priority='High', **row) for row in fetch_all("SELECT pr.id,pr.pr_number number,pr.status,pr.created_at due_date FROM purchase_requisitions pr WHERE pr.status='Submitted' AND EXISTS(SELECT 1 FROM approval_log al WHERE al.document_type='PR' AND al.document_id=pr.id AND al.decision='Pending') ORDER BY pr.created_at")]
    if user['role'] in ['PurchaseManager', 'PurchaseOfficer', 'SupplyChainManager']:
        result += [dict(type='PO delivery overdue', priority='Critical', **row) for row in fetch_all("SELECT id,po_number number,status,committed_delivery_date due_date FROM purchase_orders WHERE status IN('Approved','Printed','Partially Received') AND committed_delivery_date IS NOT NULL AND date(committed_delivery_date)<date('now') ORDER BY committed_delivery_date")]
        result += [dict(type='Three-way match exception', priority='High', **row) for row in fetch_all("SELECT id,invoice_number number,match_status status,invoice_date due_date FROM invoices WHERE match_status='Variance' ORDER BY invoice_date")]
        result += [dict(type='RFQ closing', priority='High', **row) for row in fetch_all("SELECT id,rfq_number number,workflow_status status,closing_date due_date FROM rfqs WHERE workflow_status NOT IN('Awarded','Closed','Cancelled') AND date(closing_date)<=date('now','+2 days') ORDER BY closing_date")]
        result += [dict(type='RFQ award approval', priority='High', **row) for row in fetch_all("SELECT id,rfq_number number,workflow_status status,closing_date due_date FROM rfqs WHERE workflow_status='Awaiting Approval' ORDER BY closing_date")]
    if user['role'] in ['WarehouseManager', 'SupplyChainManager']:
        predicate, params = warehouse_filter(user, 'mii.warehouse_id')
        result += [dict(type='Issue approval', priority='High', **row) for row in fetch_all(f"SELECT mi.id,mi.issue_number number,mi.total_value,mi.status,mi.created_at due_date FROM material_issues mi WHERE mi.status='PendingApproval' AND EXISTS(SELECT 1 FROM material_issue_items mii WHERE mii.issue_id=mi.id AND {predicate}) ORDER BY mi.created_at", params)]
        predicate, params = warehouse_filter(user, 'sa.warehouse_id')
        result += [dict(type='Adjustment approval', priority='High', **row) for row in fetch_all(f"SELECT sa.id,sa.adjustment_number number,sa.status,sa.adjustment_date due_date FROM stock_adjustments sa WHERE sa.status='Pending' AND {predicate} ORDER BY sa.adjustment_date", params)]
    if user['role'] in ['WarehouseManager', 'WarehouseSupervisor', 'Storekeeper', 'SupplyChainManager']:
        if user['role'] in ['WarehouseManager','WarehouseSupervisor','Storekeeper']:
            ids=[int(value)for value in user.get('warehouse_ids',[])]
            result += [dict(type='PR warehouse review',priority='High',**row)for row in fetch_all(f"SELECT id,pr_number number,'Warehouse Review' status,created_at due_date FROM purchase_requisitions WHERE pr_source IN('AUTO_REPLENISHMENT','WAREHOUSE_MANUAL') AND status='Draft' AND warehouse_submitted_at IS NULL AND trigger_warehouse_id IN({','.join('?'for _ in ids)or'NULL'}) ORDER BY created_at",ids)]
        predicate, params = warehouse_filter(user, 'il.warehouse_id')
        result += [dict(type='Low stock', priority='High', **row) for row in fetch_all(f"""SELECT i.id,i.item_code number,'Low Stock' status,date('now') due_date FROM items i
            LEFT JOIN inventory_layers il ON il.item_id=i.id AND {predicate} WHERE i.deleted_at IS NULL AND i.active_yn=1 AND i.reorder_level>0
            GROUP BY i.id HAVING COALESCE(SUM(il.quantity_remaining),0)<=i.reorder_level ORDER BY i.item_code LIMIT 50""", params)]
    if user['role'] == 'SupplyChainManager':
        result += [dict(type='Duplicate items pending review', priority='Normal', **row) for row in fetch_all("SELECT id,printf('Duplicate review #%d',id) number,review_status status,date(detected_at) due_date FROM item_duplicate_reviews WHERE review_status='Pending Review' ORDER BY detected_at LIMIT 50")]
        result += [dict(type='Employee coverage gap', priority='Critical', **row) for row in fetch_all("SELECT id,printf('%s · %s',calendar_date,role_code) number,warning_status status,calendar_date due_date FROM calendar_coverage_warnings WHERE warning_status='OPEN' ORDER BY calendar_date LIMIT 50")]
    return result


@router.get('/kpis')
def kpis(request: Request, user: User, period: str = 'this_month', warehouse_id: str = 'all'):
    fetch_all=lambda sql,parameters=():scoped_report(sql,user,parameters)
    fetch_one=lambda sql,parameters=():next(iter(scoped_report(sql,user,parameters)),None)
    selected_period, period_start, period_end = dashboard_period(period)
    company = fetch_one('SELECT name,logo_url,financial_year FROM company ORDER BY id DESC LIMIT 1') or {}
    if str(company.get('logo_url') or '').startswith('/'):
        company['logo_url'] = f"{str(request.base_url).rstrip('/')}{company['logo_url']}"
    inv_where, inv_args = dashboard_warehouse_filter(user, 'il.warehouse_id', warehouse_id)
    issue_where, issue_args = dashboard_warehouse_filter(user, 'mii.warehouse_id', warehouse_id)
    ledger_where, ledger_args = dashboard_warehouse_filter(user, 'sl.warehouse_id', warehouse_id)
    inventory_value = fetch_one(f'SELECT COALESCE(SUM(il.quantity_remaining*il.unit_cost),0)value FROM inventory_layers il WHERE {inv_where}', inv_args)['value']
    monthly_purchase = fetch_one("SELECT COALESCE(SUM(total_amount),0)value FROM purchase_orders WHERE status IN('Approved','Printed','Partially Received','Closed') AND date(po_date)>=? AND date(po_date)<?", (period_start, period_end))['value']
    monthly_consumption = fetch_one(f"""SELECT COALESCE(SUM(mii.value),0)value FROM material_issue_items mii JOIN material_issues mi ON mi.id=mii.issue_id
        WHERE mi.status IN('Approved','Posted') AND date(mi.issue_date)>=? AND date(mi.issue_date)<? AND {issue_where}""", [period_start, period_end, *issue_args])['value']
    stock = fetch_one(f"""SELECT SUM(CASE WHEN qty<i.min_stock AND i.min_stock>0 THEN 1 ELSE 0 END) low_stock_items,
        SUM(CASE WHEN qty<=0 THEN 1 ELSE 0 END) out_of_stock_items FROM items i JOIN
        (SELECT i2.id,COALESCE(SUM(il.quantity_remaining),0)qty FROM items i2 LEFT JOIN inventory_layers il ON il.item_id=i2.id AND {inv_where}
         WHERE i2.deleted_at IS NULL AND i2.active_yn=1 GROUP BY i2.id)b ON b.id=i.id""", inv_args) or {}
    purchase = fetch_all("SELECT strftime('%Y-%m',po_date)month,SUM(total_amount)value FROM purchase_orders WHERE status IN('Approved','Printed','Partially Received','Closed') AND date(po_date)>=? AND date(po_date)<? GROUP BY month", (period_start, period_end))
    consumption = fetch_all(f"SELECT strftime('%Y-%m',mi.issue_date)month,SUM(mii.value)value FROM material_issue_items mii JOIN material_issues mi ON mi.id=mii.issue_id WHERE mi.status IN('Approved','Posted') AND date(mi.issue_date)>=? AND date(mi.issue_date)<? AND {issue_where} GROUP BY month", [period_start, period_end, *issue_args])
    movement = fetch_all(f"""SELECT strftime('%Y-%m',sl.created_at)month,
        SUM(CASE WHEN sl.quantity_change>0 THEN sl.quantity_change ELSE 0 END)stock_in,
        SUM(CASE WHEN sl.quantity_change<0 THEN -sl.quantity_change ELSE 0 END)stock_out
        FROM stock_ledger sl WHERE date(sl.created_at)>=? AND date(sl.created_at)<? AND {ledger_where} GROUP BY month""", [period_start, period_end, *ledger_args])
    invoice_trend = fetch_all("""SELECT strftime('%Y-%m',invoice_date)month,
        SUM(CASE WHEN match_status IN('Matched','Verified') THEN 1 ELSE 0 END)matched,
        SUM(CASE WHEN match_status='Variance' THEN 1 ELSE 0 END)exceptions,
        SUM(CASE WHEN match_status='Pending' THEN 1 ELSE 0 END)pending FROM invoices
        WHERE date(invoice_date)>=? AND date(invoice_date)<? GROUP BY month""", (period_start, period_end))
    warehouse_values = fetch_all(f"""SELECT w.id warehouse_id,w.name warehouse_name,ROUND(SUM(il.quantity_remaining*il.unit_cost),2)total_value
        FROM warehouses w JOIN inventory_layers il ON il.warehouse_id=w.id WHERE w.deleted_at IS NULL AND {inv_where}
        GROUP BY w.id,w.name ORDER BY total_value DESC""", inv_args)
    departments = fetch_all(f"""SELECT COALESCE(d.name,'Unassigned')department_name,ROUND(SUM(mii.value),2)total_value
        FROM material_issue_items mii JOIN material_issues mi ON mi.id=mii.issue_id JOIN employees e ON e.id=mi.employee_id
        LEFT JOIN departments d ON d.id=e.department_id WHERE mi.status IN('Approved','Posted') AND {issue_where}
        GROUP BY COALESCE(d.name,'Unassigned') ORDER BY total_value DESC""", issue_args)
    counts = fetch_one("""SELECT
        (SELECT COUNT(*) FROM purchase_orders WHERE status IN('Approved','Printed','Partially Received'))open_pos,
        (SELECT COALESCE(SUM(total_amount),0) FROM purchase_orders WHERE status IN('Approved','Printed','Partially Received'))outstanding_po_value,
        (SELECT COUNT(*) FROM purchase_orders WHERE status IN('Approved','Printed','Partially Received') AND committed_delivery_date IS NOT NULL AND date(committed_delivery_date)<date('now'))overdue_pos,
        (SELECT COUNT(*) FROM purchase_requisitions WHERE status IN('Draft','Submitted','Approved','Partially Ordered'))open_prs,
        (SELECT COUNT(*) FROM replenishment_drafts WHERE status NOT IN('Converted to PR','Cancelled'))open_replenishment_checks,
        (SELECT COUNT(*) FROM purchase_requisitions pr WHERE status='Submitted' AND EXISTS(SELECT 1 FROM approval_log al WHERE al.document_type='PR' AND al.document_id=pr.id AND al.decision='Pending'))pending_pr_approvals,
        (SELECT COUNT(*) FROM suppliers WHERE deleted_at IS NULL)supplier_count,
        (SELECT COUNT(*) FROM rfqs WHERE workflow_status NOT IN('Awarded','Closed','Cancelled'))open_rfqs,
        (SELECT COUNT(*) FROM rfqs WHERE workflow_status IN('Issued','Quotations Pending'))rfqs_awaiting_quotations,
        (SELECT COUNT(*) FROM rfqs WHERE workflow_status='Under Evaluation')rfqs_under_evaluation,
        (SELECT COUNT(*) FROM rfqs WHERE workflow_status='Awaiting Approval')rfqs_awaiting_approval,
        (SELECT COUNT(*) FROM rfqs WHERE workflow_status IN('Awarded','Partially Awarded') AND strftime('%Y-%m',updated_at)=strftime('%Y-%m','now'))rfqs_awarded_month,
        (SELECT ROUND(COALESCE(AVG(n),0),2) FROM(SELECT COUNT(*)n FROM rfq_suppliers GROUP BY rfq_id))average_suppliers_per_rfq,
        (SELECT ROUND(CASE WHEN COUNT(*)=0 THEN 0 ELSE 100.0*SUM(response_status IN('Received','Quotation Received'))/COUNT(*)END,2) FROM rfq_suppliers)supplier_response_rate,
        (SELECT ROUND(COALESCE(AVG(rating),0),2) FROM suppliers WHERE deleted_at IS NULL)avg_supplier_rating,
        (SELECT COUNT(*) FROM invoices WHERE match_status='Pending')invoices_pending,
        (SELECT COUNT(*) FROM invoices WHERE match_status='Variance')invoice_exceptions,
        (SELECT COUNT(*) FROM invoices WHERE match_status IN('Matched','Verified'))matched_invoices,
        (SELECT COUNT(*) FROM item_duplicate_reviews WHERE review_status='Pending Review')potential_duplicate_items,
        (SELECT COUNT(*) FROM items WHERE deleted_at IS NULL AND active_yn=0)inactive_items,
        (SELECT COUNT(*) FROM items WHERE deleted_at IS NULL AND active_yn=1 AND COALESCE(min_stock,0)<=0)items_missing_reorder_level,
        (SELECT COUNT(*) FROM employees e WHERE e.deleted_at IS NULL AND e.status='Active' AND EXISTS(SELECT 1 FROM employee_availability a WHERE a.employee_id=e.id AND date('now') BETWEEN a.date_from AND a.date_to AND a.availability_status<>'Available'))employees_unavailable_today,
        (SELECT COUNT(*) FROM employees e JOIN departments d ON d.id=e.department_id WHERE e.deleted_at IS NULL AND e.status='Active' AND lower(d.name)='warehouse')active_warehouse_employees,
        (SELECT COUNT(*) FROM employees e JOIN departments d ON d.id=e.department_id WHERE e.deleted_at IS NULL AND e.status='Active' AND lower(d.name)='procurement')active_procurement_employees,
        (SELECT COUNT(*) FROM calendar_coverage_warnings WHERE warning_status='OPEN' AND calendar_date=date('now'))coverage_warnings,
        (SELECT COUNT(*) FROM employee_work_calendar WHERE calendar_date>=date('now') AND status IN('DRAFT','PROVISIONAL'))unpublished_entries""") or {}
    workforce = fetch_one("""SELECT
        SUM(CASE WHEN c.day_type='WORKDAY' AND (lower(COALESCE(s.shift_code,'')) LIKE '%morning%' OR time(COALESCE(c.shift_start,s.start_time))<'12:00') THEN 1 ELSE 0 END)morning_today,
        SUM(CASE WHEN c.day_type='WORKDAY' AND (lower(COALESCE(s.shift_code,'')) LIKE '%afternoon%' OR time(COALESCE(c.shift_start,s.start_time)) BETWEEN '12:00' AND '17:59') THEN 1 ELSE 0 END)afternoon_today,
        SUM(CASE WHEN c.day_type='WORKDAY' AND (lower(COALESCE(s.shift_code,'')) LIKE '%evening%' OR time(COALESCE(c.shift_start,s.start_time))>='18:00') THEN 1 ELSE 0 END)evening_today,
        SUM(c.day_type='OFF')off_today,SUM(c.day_type='HOLIDAY_WORKING')holiday_workers_today
        FROM employee_work_calendar c LEFT JOIN shifts s ON s.id=c.shift_id WHERE c.calendar_date=date('now')""") or {}
    approvals = fetch_one("""SELECT (SELECT COUNT(*)FROM purchase_orders WHERE status='PendingApproval')+
        (SELECT COUNT(*)FROM purchase_requisitions WHERE status='Submitted')+(SELECT COUNT(*)FROM material_issues WHERE status='PendingApproval')+
        (SELECT COUNT(*)FROM stock_adjustments WHERE status='Pending')value""")['value']
    p_trend = filtered_month_series(purchase, ['value'], period_start, period_end)
    c_trend = filtered_month_series(consumption, ['value'], period_start, period_end)
    upcoming_holiday=fetch_one("SELECT holiday_name,holiday_type,COALESCE(observed_date,holiday_date) holiday_date,COALESCE(holiday_end_date,observed_date,holiday_date) holiday_end_date,country_code,region FROM holidays WHERE active_yn=1 AND date(COALESCE(holiday_end_date,observed_date,holiday_date))>=date('now') ORDER BY date(COALESCE(observed_date,holiday_date)),id LIMIT 1")or{}
    backup=backup_schedule();last_backup=fetch_one("SELECT created_at,backup_status FROM backup_restore_history WHERE backup_status='SUCCESS' ORDER BY id DESC LIMIT 1")or{}
    for row in p_trend + c_trend:
        row['total_value'] = row['value']
    result = {
        'generated_at': fetch_one("SELECT datetime('now')value")['value'],
        'selected_period': selected_period, 'selected_warehouse_id': None if str(warehouse_id).lower() == 'all' else int(warehouse_id),
        'dashboard_profile': 'executive' if user['role'] == 'SupplyChainManager' else 'procurement' if user['role'] in ['PurchaseManager', 'PurchaseOfficer'] else 'warehouse',
        'scope_warehouse_ids': [] if user['role'] == 'SupplyChainManager' else user.get('warehouse_ids', []),
        'company_name': company.get('name'), 'company_logo_url': company.get('logo_url'), 'financial_year': company.get('financial_year'),
        'total_inventory_value': round(float(inventory_value or 0), 2), 'monthly_purchase': round(float(monthly_purchase or 0), 2),
        'monthly_consumption': round(float(monthly_consumption or 0), 2), 'low_stock_items': int(stock.get('low_stock_items') or 0),
        'out_of_stock_items': int(stock.get('out_of_stock_items') or 0), 'pending_approvals': int(approvals or 0),
        'purchase_trend': p_trend, 'consumption_trend': c_trend,
        'stock_movement_trend': month_series(movement, ['stock_in', 'stock_out']),
        'invoice_match_trend': month_series(invoice_trend, ['matched', 'exceptions', 'pending']),
        'po_status_distribution': [{'label': r['status'], 'value': r['value']} for r in fetch_all('SELECT status,COUNT(*)value FROM purchase_orders GROUP BY status ORDER BY status')],
        'warehouse_values': warehouse_values, 'department_consumption': departments,
        'upcoming_public_holiday':upcoming_holiday,'next_backup_at_utc':backup['scheduled_utc'].isoformat(),'backup_time_zone':backup['time_zone'],'last_successful_backup':last_backup,
        **{key: 0 if value is None else value for key, value in counts.items()},
        **{key: int(value or 0) for key, value in workforce.items()},
    }

    if user['role']=='SupplyChainManager':return result
    common={'generated_at','selected_period','selected_warehouse_id','dashboard_profile','scope_warehouse_ids','company_name','company_logo_url','financial_year'}
    procurement={'monthly_purchase','open_prs','pending_pr_approvals','open_pos','outstanding_po_value','overdue_pos','supplier_count','avg_supplier_rating','invoices_pending','invoice_exceptions','matched_invoices','purchase_trend','po_status_distribution','invoice_match_trend'}
    warehouse={'total_inventory_value','monthly_consumption','low_stock_items','out_of_stock_items','items_missing_reorder_level','employees_unavailable_today','consumption_trend','stock_movement_trend','warehouse_values','department_consumption'}
    if user['role'] in ('PurchaseManager','PurchaseOfficer'):
        return {key:value for key,value in result.items() if key in common|procurement}
    ids=[int(warehouse_id)] if str(warehouse_id)!='all' else [int(i) for i in user.get('warehouse_ids',[])]
    marks=','.join('?' for _ in ids) or 'NULL'
    scoped_stock=fetch_one(f"""SELECT COALESCE(SUM(CASE WHEN quantity<=minimum AND minimum>0 THEN 1 ELSE 0 END),0)low_stock_items,
      COALESCE(SUM(CASE WHEN quantity<=0 THEN 1 ELSE 0 END),0)out_of_stock_items,
      COUNT(DISTINCT CASE WHEN minimum<=0 THEN item_id END)items_missing_reorder_level
      FROM(SELECT i.id item_id,w.id warehouse_id,COALESCE(NULLIF(i.min_stock,0),i.reorder_level,0)minimum,
        COALESCE((SELECT SUM(s.quantity)FROM inventory_stock s WHERE s.item_id=i.id AND s.warehouse_id=w.id),0)quantity
        FROM items i JOIN warehouses w ON(i.default_warehouse_id=w.id OR EXISTS(SELECT 1 FROM item_warehouse_settings iws WHERE iws.item_id=i.id AND iws.warehouse_id=w.id))
        WHERE i.deleted_at IS NULL AND i.active_yn=1 AND w.id IN({marks}))""",ids)
    result.update(scoped_stock)
    result['employees_unavailable_today']=fetch_one(f"""SELECT COUNT(*) value FROM employees e WHERE e.deleted_at IS NULL AND e.status='Active' AND e.warehouse_id IN({marks})
      AND EXISTS(SELECT 1 FROM employee_availability a WHERE a.employee_id=e.id AND date('now') BETWEEN a.date_from AND a.date_to AND a.availability_status<>'Available')""",ids)['value']
    return {key:value for key,value in result.items() if key in common|warehouse}
