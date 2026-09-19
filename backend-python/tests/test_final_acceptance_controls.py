import shutil
import sqlite3

from fastapi.testclient import TestClient

from app import database
from app.main import app
from app.security import sign_token


def _isolated_client(tmp_path, monkeypatch):
    path = tmp_path / "final-acceptance.db"
    shutil.copy2(database.DB_PATH, path)
    monkeypatch.setattr(database, "DB_PATH", path)
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        user = connection.execute("SELECT id FROM users WHERE role='SupplyChainManager' LIMIT 1").fetchone()[0]
    return path, TestClient(app), {"Authorization": f"Bearer {sign_token({'id': user})}"}


def test_grn_requires_batch_and_expiry_for_controlled_items(tmp_path, monkeypatch):
    path, client, headers = _isolated_client(tmp_path, monkeypatch)
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        supplier = connection.execute("SELECT id FROM suppliers LIMIT 1").fetchone()[0]
        item = connection.execute("SELECT id FROM items LIMIT 1").fetchone()[0]
        warehouse, location = connection.execute("SELECT warehouse_id,id FROM locations WHERE type='Bin' LIMIT 1").fetchone()
        employee = connection.execute("SELECT id FROM employees WHERE warehouse_id=? AND status='Active' LIMIT 1", (warehouse,)).fetchone()[0]
        connection.execute("UPDATE items SET batch_control_yn=1,expiry_control_yn=1 WHERE id=?", (item,))
    po = client.post("/api/procurement/pos", headers=headers, json={"supplier_id": supplier, "delivery_warehouse_id": warehouse, "items": [{"item_id": item, "quantity": 2, "price": 10, "tax": 0}]})
    assert po.status_code == 201, po.text
    line = {"item_id": item, "quantity_received": 1, "accepted_qty": 1, "rejected_qty": 0}
    missing_batch = client.post("/api/warehouse/grns", headers=headers, json={"po_id": po.json()["id"], "warehouse_id": warehouse, "received_for_employee_id": employee, "items": [line]})
    assert missing_batch.status_code == 400 and "Batch is required" in missing_batch.json()["error"]
    missing_expiry = client.post("/api/warehouse/grns", headers=headers, json={"po_id": po.json()["id"], "warehouse_id": warehouse, "received_for_employee_id": employee, "items": [{**line, "batch": "LOT-1"}]})
    assert missing_expiry.status_code == 400 and "Expiry date is required" in missing_expiry.json()["error"]
    posted = client.post("/api/warehouse/grns", headers=headers, json={"po_id": po.json()["id"], "warehouse_id": warehouse, "received_for_employee_id": employee, "items": [{**line, "batch": "LOT-1", "expiry_date": "2027-12-31"}]})
    assert posted.status_code == 201, posted.text
    assert posted.json()['accepted_value'] == 10
    gid = posted.json()['id']
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM grns").fetchone()[0] == 1
        assert connection.execute('SELECT accepted_value FROM grns WHERE id=?', (gid,)).fetchone()[0] == 10
        # Historical postings left the header at zero despite correctly costed lines.
        connection.execute('UPDATE grns SET accepted_value=0 WHERE id=?', (gid,))
    listed = client.get('/api/warehouse/grns', headers=headers)
    assert listed.status_code == 200
    assert next(row for row in listed.json() if row['id'] == gid)['accepted_value'] == 10
    detail = client.get(f'/api/warehouse/grns/{gid}', headers=headers)
    assert detail.status_code == 200
    assert detail.json()['accepted_value'] == 10


def test_putaway_override_cannot_bypass_capacity_or_storage_rule(tmp_path, monkeypatch):
    path, client, headers = _isolated_client(tmp_path, monkeypatch)
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        user = connection.execute("SELECT id FROM users WHERE role='SupplyChainManager' LIMIT 1").fetchone()[0]
        warehouse = connection.execute("SELECT id FROM warehouses LIMIT 1").fetchone()[0]
        item = connection.execute("SELECT id FROM items LIMIT 1").fetchone()[0]
        connection.execute("UPDATE items SET category='PPE' WHERE id=?", (item,))
        connection.execute("INSERT INTO item_category_storage_rules(category,storage_classification,environment,structure_type,priority,created_by) VALUES('PPE','PPE','INDOOR','RACK_SHELF_BIN',1,?)", (user,))
        valid = connection.execute("INSERT INTO locations(warehouse_id,type,code,label,storage_classification,environment,structure_type,capacity_quantity,active_yn,status) VALUES(?,'Bin','ACC-VALID','Valid PPE Bin','PPE','INDOOR','RACK_SHELF_BIN',100,1,'Available')", (warehouse,)).lastrowid
        full = connection.execute("INSERT INTO locations(warehouse_id,type,code,label,storage_classification,environment,structure_type,capacity_quantity,active_yn,status) VALUES(?,'Bin','ACC-FULL','Full PPE Bin','PPE','INDOOR','RACK_SHELF_BIN',5,1,'Available')", (warehouse,)).lastrowid
        wrong = connection.execute("INSERT INTO locations(warehouse_id,type,code,label,storage_classification,environment,structure_type,capacity_quantity,active_yn,status) VALUES(?,'Bay','ACC-WRONG','Wrong Area','AGGREGATE','OUTDOOR','BAY',100,1,'Available')", (warehouse,)).lastrowid
        recommendation = connection.execute("INSERT INTO putaway_recommendations(item_id,warehouse_id,quantity,inventory_status,recommended_location_id,recommended_by) VALUES(?,?,10,'AVAILABLE',?,?)", (item, warehouse, valid, user)).lastrowid
    for selected in (full, wrong):
        response = client.put(f"/api/masters/putaway/{recommendation}/confirm", headers=headers, json={"selected_location_id": selected, "override_reason": "Alternate location"})
        assert response.status_code == 409, response.text
    accepted = client.put(f"/api/masters/putaway/{recommendation}/confirm", headers=headers, json={"selected_location_id": valid})
    assert accepted.status_code == 200, accepted.text


def test_inspection_partial_release_putaway_reconciles_quantity_and_value(tmp_path, monkeypatch):
    path, client, headers = _isolated_client(tmp_path, monkeypatch)
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        supplier = connection.execute("SELECT id FROM suppliers LIMIT 1").fetchone()[0]
        item = connection.execute("SELECT id FROM items LIMIT 1").fetchone()[0]
        warehouse, location = connection.execute("SELECT warehouse_id,id FROM locations WHERE type='Bin' LIMIT 1").fetchone()
        employee = connection.execute("SELECT id FROM employees WHERE warehouse_id=? AND status='Active' LIMIT 1", (warehouse,)).fetchone()[0]
        storekeeper = connection.execute("SELECT id FROM users WHERE role='Storekeeper' LIMIT 1").fetchone()[0]
        connection.execute("UPDATE items SET inspection_required_yn=1,uom='EA',purchase_uom='EA',conversion_factor=1 WHERE id=?", (item,))
    po = client.post("/api/procurement/pos", headers=headers, json={"supplier_id": supplier, "delivery_warehouse_id": warehouse, "items": [{"item_id": item, "quantity": 100, "price": 20, "tax": 0}]})
    assert po.status_code == 201, po.text
    grn = client.post("/api/warehouse/grns", headers=headers, json={"po_id": po.json()["id"], "warehouse_id": warehouse, "received_for_employee_id": employee, "items": [{"item_id": item, "quantity_received": 100, "accepted_qty": 100, "rejected_qty": 0}]})
    assert grn.status_code == 201, grn.text
    queue = client.get("/api/warehouse/receiving-queue", headers=headers).json()
    hold = next(row for row in queue if row["item_id"] == item)
    assert hold["inventory_status"] == "INSPECTION_PENDING" and hold["quantity"] == 100
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COALESCE(SUM(quantity),0) FROM inventory_stock WHERE item_id=?", (item,)).fetchone()[0] == 0
    storekeeper_headers = {"Authorization": f"Bearer {sign_token({'id': storekeeper})}"}
    denied = client.post("/api/warehouse/inspections", headers=storekeeper_headers, json={"hold_id": hold["id"], "inspected_quantity": 1, "passed_quantity": 1, "failed_quantity": 0})
    assert denied.status_code == 403
    first = client.post("/api/warehouse/inspections", headers=headers, json={"hold_id": hold["id"], "inspected_quantity": 60, "passed_quantity": 55, "failed_quantity": 5, "remarks": "Partial quality inspection", "inspector_name": "Test Inspector", "inspector_department": "Quality", "inspector_designation": "QA Engineer"})
    assert first.status_code == 201, first.text
    assert first.json()["remaining_quantity"] == 40
    detail = client.get(f"/api/warehouse/grns/{grn.json()['id']}", headers=headers).json()
    recorded = detail['inspections'][0]
    assert recorded['inspector_name'] == 'Test Inspector'
    assert recorded['inspector_department'] == 'Quality'
    assert recorded['inspector_designation'] == 'QA Engineer'
    assert client.get(f"/api/attachments/GRN/{grn.json()['id']}", headers=headers).json() == []
    from app.routes import attachments
    documents = tmp_path / 'inspection-documents'
    documents.mkdir()
    monkeypatch.setattr(attachments, 'DOCS', documents)
    uploaded = client.post(f"/api/attachments/GRN/{grn.json()['id']}", headers=headers,
                           files={'file': ('inspection-approval.pdf', b'%PDF-1.4\nInspection approval', 'application/pdf')})
    assert uploaded.status_code == 201, uploaded.text
    evidence = client.get(f"/api/attachments/file/{uploaded.json()['id']}", headers=headers)
    assert evidence.status_code == 200 and evidence.content.startswith(b'%PDF-')

    second = client.post("/api/warehouse/inspections", headers=headers, json={"hold_id": hold["id"], "inspected_quantity": 40, "passed_quantity": 40, "failed_quantity": 0, "remarks": "Remaining quantity passed"})
    assert second.status_code == 201, second.text
    pending = [row for row in client.get("/api/warehouse/receiving-queue", headers=headers).json() if row["item_id"] == item and row["inventory_status"] == "PUT_AWAY_PENDING"]
    assert sum(row["quantity"] for row in pending) == 95
    for row in pending:
        recommendation = client.post("/api/masters/putaway/recommend", headers=headers, json={"item_id": item, "warehouse_id": warehouse, "quantity": row["quantity"], "inventory_status": "AVAILABLE", "source_table": "inventory_quarantine", "source_id": row["id"]})
        assert recommendation.status_code == 200, recommendation.text
        confirmed = client.put(f"/api/masters/putaway/{recommendation.json()['recommendation_id']}/confirm", headers=headers, json={"selected_location_id": recommendation.json()["location"]["id"]})
        assert confirmed.status_code == 200, confirmed.text
    with sqlite3.connect(path) as connection:
        available = connection.execute("SELECT COALESCE(SUM(quantity),0) FROM inventory_stock WHERE item_id=? AND warehouse_id=?", (item, warehouse)).fetchone()[0]
        fifo = connection.execute("SELECT COALESCE(SUM(quantity_remaining),0),COALESCE(SUM(quantity_remaining*unit_cost),0) FROM inventory_layers WHERE item_id=? AND warehouse_id=?", (item, warehouse)).fetchone()
        restricted = connection.execute("SELECT inventory_status,SUM(quantity),SUM(quantity*unit_cost) FROM inventory_quarantine WHERE item_id=? AND released_at IS NULL GROUP BY inventory_status", (item,)).fetchall()
    assert available == fifo[0] == 95 and fifo[1] == 1900
    assert restricted == [("REJECTED", 5, 100)]
    item_row = next(row for row in client.get('/api/masters/items', headers=headers).json() if row['id'] == item)
    assert item_row['available_stock'] == 95
    assert item_row['stock_unit_cost'] == 20
