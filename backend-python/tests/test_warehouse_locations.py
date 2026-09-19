import shutil
import sqlite3

from fastapi.testclient import TestClient

from app import database
from app.main import app
from app.security import sign_token


def test_location_hierarchy_generates_codes_and_supports_editing(tmp_path, monkeypatch):
    test_database = tmp_path / "warehouse-locations.db"
    shutil.copy2(database.DB_PATH, test_database)
    monkeypatch.setattr(database, "DB_PATH", test_database)
    with sqlite3.connect(test_database) as connection:
        connection.row_factory = sqlite3.Row
        user = connection.execute("SELECT id,username,full_name,role,warehouse_id FROM users WHERE role='SupplyChainManager' AND deleted_at IS NULL ORDER BY id LIMIT 1").fetchone()
        warehouse = connection.execute("SELECT id,warehouse_code FROM warehouses WHERE deleted_at IS NULL ORDER BY id LIMIT 1").fetchone()
    token = sign_token({**dict(user), "warehouse_ids": [], "permission_keys": []})
    headers = {"Authorization": f"Bearer {token}"}
    client = TestClient(app)

    with sqlite3.connect(test_database) as connection:
        legacy_id = connection.execute("INSERT INTO warehouses(name,warehouse_code) VALUES('Legacy Missing Code',NULL)").lastrowid
    repaired_warehouses = client.get("/api/masters/warehouses", headers=headers)
    assert repaired_warehouses.status_code == 200
    assert next(row for row in repaired_warehouses.json() if row["id"] == legacy_id)["warehouse_code"].startswith("WH")

    zone = client.post("/api/masters/locations", json={"warehouse_id": warehouse["id"], "type": "Zone", "label": "Test Zone", "structure_type": "RACK_SHELF_BIN", "storage_classification": "TOOLS", "environment": "INDOOR"}, headers=headers)
    assert zone.status_code == 201, zone.text
    assert zone.json()["code"].startswith(f"{warehouse['warehouse_code']}-Z")
    assert not zone.json()["code"].startswith("NONE-")

    rack = client.post("/api/masters/locations", json={"warehouse_id": warehouse["id"], "type": "Rack", "parent_id": zone.json()["id"], "label": "Test Rack"}, headers=headers)
    assert rack.status_code == 201, rack.text
    assert rack.json()["parent_id"] == zone.json()["id"]

    invalid_bin = client.post("/api/masters/locations", json={"warehouse_id": warehouse["id"], "type": "Bin", "parent_id": rack.json()["id"]}, headers=headers)
    assert invalid_bin.status_code == 400
    assert "under a Shelf" in invalid_bin.json()["error"]

    shelves = client.post(f"/api/masters/locations/{rack.json()['id']}/generate", json={"count": 2}, headers=headers)
    assert shelves.status_code == 201, shelves.text
    assert shelves.json()["created"] == 2

    edited = client.put(f"/api/masters/locations/{rack.json()['id']}", json={"label": "Updated Rack", "status": "Maintenance"}, headers=headers)
    assert edited.status_code == 200, edited.text
    assert edited.json()["label"] == "Updated Rack"

    listed = client.get("/api/masters/locations", headers=headers)
    listed_rack = next(row for row in listed.json() if row["id"] == rack.json()["id"])
    assert listed_rack["parent_code"] == zone.json()["code"]
    assert "site_name" in listed_rack
    with sqlite3.connect(test_database) as connection:
        item_id = connection.execute("SELECT id FROM items ORDER BY id LIMIT 1").fetchone()[0]
        connection.execute("INSERT INTO inventory_stock(item_id,warehouse_id,location_id,quantity) VALUES(?,?,?,1)",(item_id,warehouse["id"],rack.json()["id"]))
    blocked = client.delete(f"/api/masters/locations/{zone.json()['id']}/permanent", headers=headers)
    assert blocked.status_code == 409
    assert "inventory_stock.location_id" in blocked.json()["error"]


def test_aisle_hierarchy_quick_setup_and_terminal_locations(tmp_path, monkeypatch):
    test_database = tmp_path / "warehouse-aisles.db"
    shutil.copy2(database.DB_PATH, test_database)
    monkeypatch.setattr(database, "DB_PATH", test_database)
    with sqlite3.connect(test_database) as connection:
        connection.row_factory = sqlite3.Row
        user = connection.execute("SELECT id,username,full_name,role,warehouse_id FROM users WHERE role='SupplyChainManager' AND deleted_at IS NULL ORDER BY id LIMIT 1").fetchone()
        warehouse = connection.execute("SELECT id FROM warehouses WHERE deleted_at IS NULL ORDER BY id LIMIT 1").fetchone()
    headers = {"Authorization": f"Bearer {sign_token({**dict(user), 'warehouse_ids': [], 'permission_keys': []})}"}
    client = TestClient(app)

    zone = client.post("/api/masters/locations", json={"warehouse_id": warehouse["id"], "type": "Zone", "label": "Aisle Zone", "structure_type": "AISLE_RACK_SHELF_BIN"}, headers=headers)
    assert zone.status_code == 201, zone.text
    invalid_rack = client.post("/api/masters/locations", json={"warehouse_id": warehouse["id"], "type": "Rack", "parent_id": zone.json()["id"]}, headers=headers)
    assert invalid_rack.status_code == 400

    setup = client.post(f"/api/masters/locations/{zone.json()['id']}/quick-setup", json={"aisles": 2, "racks_per_aisle": 3, "shelves_per_rack": 2, "bins_per_shelf": 2}, headers=headers)
    assert setup.status_code == 201, setup.text
    assert setup.json()["created"] == {"Aisle": 2, "Rack": 6, "Shelf": 12, "Bin": 24}
    repeated = client.post(f"/api/masters/locations/{zone.json()['id']}/quick-setup", json={"aisles": 1, "racks_per_aisle": 1, "shelves_per_rack": 1, "bins_per_shelf": 1}, headers=headers)
    assert repeated.status_code == 201
    assert repeated.json()["total_created"] == 0

    listed = client.get("/api/masters/locations", headers=headers).json()
    descendants = [row for row in listed if row.get("structure_type") == "AISLE_RACK_SHELF_BIN" and row["id"] != zone.json()["id"]]
    assert sum(row["type"] == "Aisle" for row in descendants) == 2
    assert all(row["is_terminal_storage"] == (row["type"] == "Bin") for row in descendants)
    assert all(row["hierarchy_path"] for row in descendants)

    deleted = client.delete(f"/api/masters/locations/{zone.json()['id']}/permanent", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_count"] == 45
    remaining_ids = {row["id"] for row in client.get("/api/masters/locations", headers=headers).json()}
    assert zone.json()["id"] not in remaining_ids
