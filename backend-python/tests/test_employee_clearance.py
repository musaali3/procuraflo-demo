import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import database
from app.database import ensure_company_employee_schema
from app.main import app
from app.security import sign_token


def setup(tmp_path, monkeypatch):
    path = tmp_path / 'employee-clearance.db'
    shutil.copy2(database.DB_PATH, path)
    monkeypatch.setattr(database, 'DB_PATH', path)
    ensure_company_employee_schema()
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO company(name,currency,base_currency,financial_year) VALUES('Clearance Test Company','SAR','SAR','2026')")
        department = connection.execute("SELECT id FROM departments WHERE name='Engineering'").fetchone()[0]
        warehouses = [connection.execute("INSERT INTO warehouses(warehouse_code,name) VALUES(?,?)", (f'CLR-WH-{index}', name)).lastrowid for index,name in enumerate(('Main Warehouse','Project Warehouse'),1)]
        employee = connection.execute("INSERT INTO employees(employee_code,name,department_id,position,warehouse_id,status) VALUES('EMP-CLR','Clearance Employee',?,'Engineer',?,'Active')", (department,warehouses[0])).lastrowid
        manager_employee = connection.execute("INSERT INTO employees(employee_code,name,department_id,position,warehouse_id,status) VALUES('EMP-SCM','Clearance Manager',?,'Supply Chain Manager',?,'Active')", (department,warehouses[0])).lastrowid
        manager = connection.execute("INSERT INTO users(username,password_hash,full_name,role,employee_id) VALUES('clearance.manager','x','Clearance Manager','SupplyChainManager',?)", (manager_employee,)).lastrowid
        for role in ('PurchaseManager','PurchaseOfficer','WarehouseManager','WarehouseSupervisor','Storekeeper'):
            connection.execute("INSERT INTO users(username,password_hash,full_name,role) VALUES(?,?,?,?)", (f'clearance.{role.lower()}','x',role,role))
        item = connection.execute("INSERT INTO items(item_code,description,consumable_returnable,standard_cost) VALUES('CLR-ITEM','Returnable Test Tool','Returnable',125)").lastrowid
        connection.execute("INSERT OR IGNORE INTO system_maintenance(id,active_yn,session_epoch) VALUES(1,0,1)")
    headers = {'Authorization': f"Bearer {sign_token({'id': manager})}"}
    return path, TestClient(app), headers, employee, item, warehouses


def posted_issue(path, employee, item, warehouse, number, quantity):
    with sqlite3.connect(path) as connection:
        manager = connection.execute("SELECT id FROM users WHERE role='SupplyChainManager' LIMIT 1").fetchone()[0]
        issue = connection.execute("INSERT INTO material_issues(issue_number,employee_id,purpose,approval_required,status,created_by,total_value) VALUES(?,?,?,0,'Posted',?,?)", (number, employee, 'Clearance test', manager, quantity * 125)).lastrowid
        connection.execute("INSERT INTO material_issue_items(issue_id,item_id,warehouse_id,quantity,value) VALUES(?,?,?,?,?)", (issue, item, warehouse, quantity, quantity * 125))


def start(client, headers, employee):
    response = client.post('/api/employee-clearance', headers=headers, json={'employee_id': employee, 'clearance_reason': 'Resignation'})
    assert response.status_code == 201, response.text
    return response.json()


def test_company_wide_inactive_warehouse_and_cross_warehouse_return(tmp_path, monkeypatch):
    path, client, headers, employee, item, warehouses = setup(tmp_path, monkeypatch)
    posted_issue(path, employee, item, warehouses[1], 'CLR-ISSUE-A', 1)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE warehouses SET deleted_at=datetime('now') WHERE id=?", (warehouses[1],))
    created = start(client, headers, employee)
    assert created['status'] == 'Not Clear'
    assert created['items'][0]['warehouse_id'] == warehouses[1]
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO returns(return_number,item_id,employee_id,quantity,condition,warehouse_id) VALUES('CLR-RETURN-X',?,?,1,'Good',?)", (item, employee, warehouses[0]))
    detail = client.get(f"/api/employee-clearance/{created['id']}", headers=headers).json()
    assert detail['status'] == 'Clear for HR Processing'
    assert detail['outstanding_item_count'] == 0


def test_duplicate_damaged_resolution_final_verification_and_history(tmp_path, monkeypatch):
    path, client, headers, employee, item, warehouses = setup(tmp_path, monkeypatch)
    posted_issue(path, employee, item, warehouses[0], 'CLR-ISSUE-B', 1)
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO returns(return_number,item_id,employee_id,quantity,condition,warehouse_id) VALUES('CLR-RETURN-D',?,?,1,'Damaged',?)", (item, employee, warehouses[1]))
    created = start(client, headers, employee)
    duplicate = client.post('/api/employee-clearance', headers=headers, json={'employee_id': employee, 'clearance_reason': 'Termination'})
    assert duplicate.status_code == 409
    detail = client.get(f"/api/employee-clearance/{created['id']}", headers=headers).json()
    assert detail['status'] == 'Not Clear' and detail['unresolved_liability_count'] == 1
    blocked = client.post(f"/api/employee-clearance/{created['id']}/documents", headers=headers, json={'document_type': 'Clearance Certificate'})
    assert blocked.status_code == 409
    liability = detail['unresolved_liabilities'][0]
    resolved = client.post(f"/api/employee-clearance/{created['id']}/liabilities/{liability['id']}/resolve", headers=headers, json={'resolution_status': 'Liability Waived', 'resolution_reason': 'Management approved write-off', 'resolution_reference': 'MGT-42'})
    assert resolved.status_code == 200 and resolved.json()['status'] == 'Clear for HR Processing'
    issued = client.post(f"/api/employee-clearance/{created['id']}/documents", headers=headers, json={'document_type': 'Clearance Certificate'})
    assert issued.status_code == 201, issued.text
    history = client.get(f"/api/employee-clearance/{created['id']}", headers=headers).json()
    assert history['letter_status'] == 'Clearance Certificate Issued'
    assert len(history['documents']) == 1 and history['final_verification_at']
    rehire_cycle = client.post('/api/employee-clearance', headers=headers, json={'employee_id': employee, 'clearance_reason': 'Contract Completion'})
    assert rehire_cycle.status_code == 201, rehire_cycle.text


@pytest.mark.parametrize('role', ['PurchaseManager','PurchaseOfficer','WarehouseManager','WarehouseSupervisor','Storekeeper'])
def test_supply_chain_manager_only(role, tmp_path, monkeypatch):
    path, client, _headers, _employee, _item, _warehouses = setup(tmp_path, monkeypatch)
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT id FROM users WHERE role=? AND is_active=1 AND deleted_at IS NULL LIMIT 1", (role,)).fetchone()
    if not row: pytest.skip(f'No {role} fixture')
    denied = {'Authorization': f"Bearer {sign_token({'id': row[0]})}"}
    assert client.get('/api/employee-clearance', headers=denied).status_code == 403
    assert client.get('/api/employee-clearance/audit-report', headers=denied).status_code == 403
