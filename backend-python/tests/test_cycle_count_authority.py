import shutil
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import database
from app.main import app
from app.security import sign_token


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    path = tmp_path / "cycle-count-authority.db"
    shutil.copy2(database.DB_PATH, path)
    monkeypatch.setattr(database, "DB_PATH", path)
    database.ensure_company_employee_schema()
    with database.transaction(immediate=True) as c:
        users = {row["role"]: dict(row) for row in c.execute("SELECT * FROM users ORDER BY id DESC")}
        item = c.execute("SELECT id FROM items WHERE item_code='TEST-ITEM-002'").fetchone()["id"]
        warehouse = users["WarehouseSupervisor"]["warehouse_id"]
        location = c.execute("SELECT id FROM locations WHERE warehouse_id=? LIMIT 1", (warehouse,)).fetchone()["id"]
        c.execute("INSERT INTO inventory_stock(item_id,warehouse_id,location_id,quantity)VALUES(?,?,?,100)", (item, warehouse, location))
        c.execute("INSERT INTO inventory_layers(item_id,warehouse_id,location_id,quantity_remaining,unit_cost)VALUES(?,?,?,?,?)", (item, warehouse, location, 100, 100))
    client = TestClient(app)

    def call(role, method, url, body=None):
        return client.request(method, "/api" + url, headers={"Authorization": "Bearer " + sign_token({"id": users[role]["id"]})}, json=body)

    return SimpleNamespace(users=users, item=item, warehouse=warehouse, location=location, call=call)


def test_cycle_count_authority_and_variance_adjustment_are_separate(ctx):
    denied = ctx.call("PurchaseOfficer", "POST", "/inventory/cycle-counts", {"warehouse_id": ctx.warehouse, "item_ids": [ctx.item]})
    assert denied.status_code == 403
    blocked_storekeeper = ctx.call("Storekeeper", "POST", "/inventory/cycle-counts", {"warehouse_id": ctx.warehouse, "item_ids": [ctx.item]})
    assert blocked_storekeeper.status_code == 403

    created = ctx.call("WarehouseSupervisor", "POST", "/inventory/cycle-counts", {"warehouse_id": ctx.warehouse, "item_ids": [ctx.item]})
    assert created.status_code == 201, created.text
    count_id = created.json()["id"]
    detail = ctx.call("WarehouseSupervisor", "GET", f"/inventory/cycle-counts/{count_id}").json()
    submitted = ctx.call("WarehouseSupervisor", "PUT", f"/inventory/cycle-counts/{count_id}/submit-counts", {"counts": [{"item_id": ctx.item, "counted_qty": 96, "count_note": "Counted by bin sheet"}]})
    assert submitted.status_code == 200, submitted.text

    with database.transaction() as c:
        assert c.execute("SELECT quantity FROM inventory_stock WHERE item_id=? AND warehouse_id=? AND location_id=?", (ctx.item, ctx.warehouse, ctx.location)).fetchone()["quantity"] == 100
    premature = ctx.call("WarehouseManager", "PUT", f"/inventory/cycle-counts/{count_id}/approve")
    assert premature.status_code == 409

    proposed = ctx.call("WarehouseManager", "POST", f"/inventory/cycle-counts/{count_id}/adjustments", {"reason": "Variance verified", "comments": "Physical count was checked against the signed count sheet."})
    assert proposed.status_code == 201, proposed.text
    with database.transaction() as c:
        adjustment = c.execute("SELECT * FROM stock_adjustments WHERE cycle_count_id=?", (count_id,)).fetchone()
        assert adjustment["status"] == "Pending"
        assert adjustment["quantity_before"] == 100 and adjustment["quantity_after"] == 96 and adjustment["quantity_change"] == -4
        assert c.execute("SELECT quantity FROM inventory_stock WHERE item_id=? AND warehouse_id=? AND location_id=?", (ctx.item, ctx.warehouse, ctx.location)).fetchone()["quantity"] == 100

    wm_denied = ctx.call("WarehouseManager", "PUT", f"/inventory/cycle-counts/{count_id}/adjustments/approve")
    assert wm_denied.status_code == 403
    approved = ctx.call("SupplyChainManager", "PUT", f"/inventory/cycle-counts/{count_id}/adjustments/approve")
    assert approved.status_code == 200, approved.text
    with database.transaction() as c:
        assert c.execute("SELECT status FROM cycle_counts WHERE id=?", (count_id,)).fetchone()["status"] == "Approved"
        assert c.execute("SELECT status FROM stock_adjustments WHERE cycle_count_id=?", (count_id,)).fetchone()["status"] == "Approved"
        assert c.execute("SELECT quantity FROM inventory_stock WHERE item_id=? AND warehouse_id=? AND location_id=?", (ctx.item, ctx.warehouse, ctx.location)).fetchone()["quantity"] == 96


def test_no_variance_cycle_count_approval_does_not_post_inventory(ctx):
    created = ctx.call("WarehouseSupervisor", "POST", "/inventory/cycle-counts", {"warehouse_id": ctx.warehouse, "item_ids": [ctx.item]})
    count_id = created.json()["id"]
    assert ctx.call("WarehouseSupervisor", "PUT", f"/inventory/cycle-counts/{count_id}/submit-counts", {"counts": [{"item_id": ctx.item, "counted_qty": 100}]}).status_code == 200
    approved = ctx.call("WarehouseManager", "PUT", f"/inventory/cycle-counts/{count_id}/approve")
    assert approved.status_code == 200, approved.text
    with database.transaction() as c:
        assert c.execute("SELECT COUNT(*) FROM stock_ledger WHERE reference_table='cycle_counts' OR transaction_type LIKE 'CYCLE_COUNT_%'").fetchone()[0] == 0
        assert c.execute("SELECT quantity FROM inventory_stock WHERE item_id=? AND warehouse_id=? AND location_id=?", (ctx.item, ctx.warehouse, ctx.location)).fetchone()["quantity"] == 100


def test_storekeeper_has_cycle_count_permission_and_can_count_without_supervisor(ctx):
    with database.transaction(immediate=True) as c:
        c.execute(
            "UPDATE employees SET permission_keys=? WHERE id=?",
            ('["task.pr","task.inventory"]', ctx.users["Storekeeper"]["employee_id"]),
        )
    database.ensure_company_employee_schema()

    profile = ctx.call("Storekeeper", "GET", "/auth/me")
    assert profile.status_code == 200, profile.text
    assert "task.cycle_count" in profile.json()["permission_keys"]

    with database.transaction(immediate=True) as c:
        warehouse_id = c.execute("INSERT INTO warehouses(name,warehouse_code)VALUES('No Supervisor Warehouse','NOSUP')").lastrowid
        c.execute(
            "INSERT INTO locations(warehouse_id,type,code,label)VALUES(?,?,?,?)",
            (warehouse_id, "Bin", "NOSUP-A1", "No Supervisor A1"),
        )
        c.execute(
            "INSERT INTO user_warehouse_assignments(user_id,warehouse_id,is_active)VALUES(?,?,1)",
            (ctx.users["Storekeeper"]["id"], warehouse_id),
        )
        c.execute(
            "INSERT INTO user_warehouse_assignments(user_id,warehouse_id,is_active,effective_to)VALUES(?,?,0,date('now'))",
            (ctx.users["WarehouseSupervisor"]["id"], warehouse_id),
        )

    eligible = ctx.call("Storekeeper", "GET", "/inventory/cycle-count-warehouses")
    assert eligible.status_code == 200, eligible.text
    eligible_warehouse = next(warehouse for warehouse in eligible.json() if warehouse["id"] == warehouse_id)
    assert eligible_warehouse["can_create_cycle_count"] is True
    assert eligible_warehouse["supervisor_assigned"] is False

    created = ctx.call("Storekeeper", "POST", "/inventory/cycle-counts", {"warehouse_id": warehouse_id, "item_ids": [ctx.item]})
    assert created.status_code == 201, created.text
    listing = ctx.call("Storekeeper", "GET", "/inventory/cycle-counts")
    row = next(count for count in listing.json() if count["id"] == created.json()["id"])
    assert row["can_count"] is True


def test_supply_chain_manager_can_generate_count_sheet(ctx):
    created = ctx.call("SupplyChainManager", "POST", "/inventory/cycle-counts", {"warehouse_id": ctx.warehouse, "item_ids": [ctx.item]})
    assert created.status_code == 201, created.text
    detail = ctx.call("SupplyChainManager", "GET", f"/inventory/cycle-counts/{created.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["items"][0]["item_id"] == ctx.item
