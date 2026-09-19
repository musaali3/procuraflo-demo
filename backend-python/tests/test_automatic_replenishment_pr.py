import shutil
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app import database
from app.main import app
from app.replenishment import _due, run_replenishment
from app.security import sign_token


def test_manual_stock_replenishment_check_creates_reviewable_draft(tmp_path, monkeypatch):
    path = tmp_path / "stock-replenishment-check.db"
    shutil.copy2(database.DB_PATH, path)
    monkeypatch.setattr(database, "DB_PATH", path)
    database.ensure_company_employee_schema()
    with database.transaction(immediate=True) as connection:
        connection.execute("INSERT INTO company(name,financial_year,base_currency)VALUES('Test Company','2026','SAR')")
        department_id = connection.execute("SELECT id FROM departments WHERE lower(name)='warehouse'").fetchone()["id"]
        employee_id = connection.execute("INSERT INTO employees(employee_code,name,department_id,warehouse_id,status,approval_role,system_access_yn)VALUES('EMP-WH','Warehouse Reviewer',?,1,'Active','WarehouseManager',1)", (department_id,)).lastrowid
        user_id = connection.execute("INSERT INTO users(username,password_hash,full_name,role,employee_id,warehouse_id,is_active)VALUES('warehouse-reviewer','x','Warehouse Reviewer','WarehouseManager',?,1,1)", (employee_id,)).lastrowid
        connection.execute("INSERT INTO user_warehouse_assignments(user_id,warehouse_id,is_active)VALUES(?,1,1)", (user_id,))
        item_id = connection.execute("""INSERT INTO items(item_code,description,uom,purchase_uom,conversion_factor,reorder_level,standard_cost,default_warehouse_id,active_yn)
          VALUES('ITEM-AUTO','Automatic Replenishment Item','EA','BOX',10,15,2,1,1)""").lastrowid
        connection.execute("INSERT INTO inventory_stock(item_id,warehouse_id,quantity)VALUES(?,?,5)", (item_id, 1))
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + sign_token({"id": user_id})}

    assert run_replenishment(manual=True)["created"] == []
    created = client.post("/api/warehouse/replenishment/check", headers=headers, json={"warehouse_id": 1})
    assert created.status_code == 201, created.text
    draft = client.get(f"/api/warehouse/replenishment/drafts/{created.json()['id']}", headers=headers).json()
    line = next(row for row in draft["lines"] if row["item_id"] == item_id)
    assert line["available_qty"] == 5
    assert line["effective_stock_qty"] == 5
    assert line["system_recommended_qty"] == 10
    assert "Replenishment Required" in line["status_labels"]

    missing_payload = [{**row, "reviewed_qty": 0, "adjustment_reason": ""} if row["id"] == line["id"] else row for row in draft["lines"]]
    missing_reason = client.put(f"/api/warehouse/replenishment/drafts/{draft['id']}/review", headers=headers, json={"lines": missing_payload})
    assert missing_reason.status_code == 400
    reviewed_payload = [
        {**row, "reviewed_qty": 0, "adjustment_reason": "Stock found" if row["system_recommended_qty"] else ""}
        for row in draft["lines"]
    ]
    reviewed = client.put(f"/api/warehouse/replenishment/drafts/{draft['id']}/review", headers=headers, json={"lines": reviewed_payload})
    assert reviewed.status_code == 200, reviewed.text
    no_pr = client.post(f"/api/warehouse/replenishment/drafts/{draft['id']}/create-pr", headers=headers)
    assert no_pr.status_code == 400


def test_warehouse_schedule_uses_local_start_and_midnight():
    normal = {"time_zone": "Asia/Riyadh", "replenishment_days_json": "[0,3]", "operation_24h_yn": 0, "operating_start_time": "06:00"}
    assert _due(normal, datetime(2026, 9, 7, 3, 0, tzinfo=timezone.utc)) == (True, "2026-09-07", "06:00")
    assert _due(normal, datetime(2026, 9, 7, 2, 59, tzinfo=timezone.utc))[0] is False
    always = {**normal, "operation_24h_yn": 1}
    assert _due(always, datetime(2026, 9, 6, 21, 0, tzinfo=timezone.utc)) == (True, "2026-09-07", "00:00")
