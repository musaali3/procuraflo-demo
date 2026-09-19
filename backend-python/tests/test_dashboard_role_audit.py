import sqlite3

from fastapi.testclient import TestClient

from app.database import DB_PATH, fetch_all
from app.main import app
from app.security import sign_token


REQUIRED_KPIS = {
    'generated_at', 'dashboard_profile', 'scope_warehouse_ids', 'company_name',
    'total_inventory_value', 'monthly_purchase', 'monthly_consumption',
    'low_stock_items', 'out_of_stock_items', 'pending_approvals', 'supplier_count',
    'avg_supplier_rating', 'open_pos', 'outstanding_po_value', 'overdue_pos',
    'open_prs', 'pending_pr_approvals', 'invoices_pending', 'invoice_exceptions',
    'matched_invoices', 'potential_duplicate_items', 'inactive_items',
    'items_missing_reorder_level', 'employees_unavailable_today',
    'active_warehouse_employees', 'active_procurement_employees', 'morning_today',
    'afternoon_today', 'evening_today', 'off_today', 'holiday_workers_today',
    'coverage_warnings', 'unpublished_entries', 'purchase_trend',
    'consumption_trend', 'stock_movement_trend', 'invoice_match_trend',
    'po_status_distribution', 'warehouse_values', 'department_consumption',
}


def headers(user_id):
    return {'Authorization': f"Bearer {sign_token({'id': user_id})}"}


def test_every_active_system_role_gets_complete_live_dashboard():
    client = TestClient(app)
    users = fetch_all("SELECT id,role FROM users WHERE deleted_at IS NULL AND is_active=1")
    assert users
    observed_roles = set()
    for user in users:
        response = client.get('/api/dashboard/kpis', headers=headers(user['id']))
        assert response.status_code == 200, (user['role'], response.text)
        data = response.json()
        common={'generated_at','dashboard_profile','scope_warehouse_ids','company_name'}
        assert common <= data.keys()
        expected_profile = 'executive' if user['role'] == 'SupplyChainManager' else 'procurement' if user['role'] in {'PurchaseManager', 'PurchaseOfficer'} else 'warehouse'
        assert data['dashboard_profile'] == expected_profile
        if expected_profile=='executive':
            assert REQUIRED_KPIS <= data.keys()
        elif expected_profile=='warehouse':
            assert 'monthly_purchase' not in data and 'invoice_exceptions' not in data
            assert 'total_inventory_value' in data
        else:
            assert 'total_inventory_value' not in data and 'active_warehouse_employees' not in data
            assert 'monthly_purchase' in data
        for key in ('purchase_trend','consumption_trend'):
            if key in data:assert len(data[key])==1
        for key in ('stock_movement_trend','invoice_match_trend'):
            if key in data:assert len(data[key])==6
        assert all(data[key] is not None for key in data if key!='selected_warehouse_id' and key!='company_logo_url')
        assert client.get('/api/dashboard/tasks', headers=headers(user['id'])).status_code == 200
        observed_roles.add(user['role'])
    assert observed_roles == {'SupplyChainManager', 'PurchaseManager', 'PurchaseOfficer', 'WarehouseManager', 'WarehouseSupervisor', 'Storekeeper'}


def test_executive_totals_match_source_tables():
    client = TestClient(app)
    scm = next(user for user in fetch_all("SELECT id,role FROM users WHERE role='SupplyChainManager' AND is_active=1 AND deleted_at IS NULL LIMIT 1"))
    data = client.get('/api/dashboard/kpis', headers=headers(scm['id'])).json()
    with sqlite3.connect(DB_PATH) as connection:
        inventory = connection.execute('SELECT COALESCE(SUM(quantity_remaining*unit_cost),0) FROM inventory_layers').fetchone()[0]
        suppliers = connection.execute('SELECT COUNT(*) FROM suppliers WHERE deleted_at IS NULL').fetchone()[0]
        open_pos = connection.execute("SELECT COUNT(*) FROM purchase_orders WHERE status IN('Approved','Printed')").fetchone()[0]
        matched = connection.execute("SELECT COUNT(*) FROM invoices WHERE match_status IN('Matched','Verified')").fetchone()[0]
    assert data['total_inventory_value'] == round(inventory, 2)
    assert data['supplier_count'] == suppliers
    assert data['open_pos'] == open_pos
    assert data['matched_invoices'] == matched


def test_warehouse_dashboards_never_include_an_unassigned_warehouse():
    client = TestClient(app)
    warehouse_users = fetch_all("SELECT id,role FROM users WHERE role IN('WarehouseManager','WarehouseSupervisor','Storekeeper') AND is_active=1 AND deleted_at IS NULL")
    for user in warehouse_users:
        data = client.get('/api/dashboard/kpis', headers=headers(user['id'])).json()
        allowed = set(data['scope_warehouse_ids'])
        assert allowed
        assert {row['warehouse_id'] for row in data['warehouse_values']} <= allowed
        placeholders = ','.join('?' for _ in allowed)
        with sqlite3.connect(DB_PATH) as connection:
            expected = connection.execute(f'SELECT COALESCE(SUM(quantity_remaining*unit_cost),0) FROM inventory_layers WHERE warehouse_id IN({placeholders})', tuple(allowed)).fetchone()[0]
        assert data['total_inventory_value'] == round(expected, 2)


def test_task_types_all_have_frontend_drill_down_routes():
    client = TestClient(app)
    scm = fetch_all("SELECT id FROM users WHERE role='SupplyChainManager' AND is_active=1 AND deleted_at IS NULL LIMIT 1")[0]
    task_types = {task['type'] for task in client.get('/api/dashboard/tasks', headers=headers(scm['id'])).json()}
    supported = {'PO approval', 'PR review', 'PO delivery overdue', 'Issue approval',
                 'Adjustment approval', 'Low stock', 'Duplicate items pending review',
                     'Employee coverage gap', 'Three-way match exception', 'RFQ closing'}
    assert task_types <= supported
