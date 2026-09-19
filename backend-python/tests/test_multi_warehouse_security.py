import shutil
import sqlite3

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import database
from app.main import app
from app.security import sign_token
from app.stock import consume, receive


def setup_isolated_inventory(tmp_path, monkeypatch):
    target = tmp_path / 'multi-warehouse.db'
    shutil.copy2(database.DB_PATH, target)
    monkeypatch.setattr(database, 'DB_PATH', target)
    with sqlite3.connect(target) as c:
        c.row_factory = sqlite3.Row
        a = c.execute("INSERT INTO warehouses(warehouse_code,name)VALUES('MW-A','Multi Warehouse A')").lastrowid
        b = c.execute("INSERT INTO warehouses(warehouse_code,name)VALUES('MW-B','Multi Warehouse B')").lastrowid
        department=c.execute("INSERT OR IGNORE INTO departments(name)VALUES('Warehouse')").lastrowid
        if not department:department=c.execute("SELECT id FROM departments WHERE name='Warehouse'").fetchone()['id']
        employee=c.execute("INSERT INTO employees(employee_code,name,department_id,position,status,warehouse_id,system_access_yn)VALUES('MW-EMP','Warehouse Scope Tester',?,'Storekeeper','Active',?,1)",(department,a)).lastrowid
        user_id=c.execute("INSERT INTO users(username,password_hash,full_name,role,is_active,warehouse_id,employee_id)VALUES('mw.scope.tester','unused','Warehouse Scope Tester','Storekeeper',1,?,?)",(a,employee)).lastrowid
        la = c.execute("INSERT INTO locations(warehouse_id,type,code,label)VALUES(?,'Bin','MW-A-BIN','A Bin')",(a,)).lastrowid
        lb = c.execute("INSERT INTO locations(warehouse_id,type,code,label)VALUES(?,'Bin','MW-B-BIN','B Bin')",(b,)).lastrowid
        item = c.execute("INSERT INTO items(item_code,description,uom,standard_cost,active_yn)VALUES('MW-ITEM','Warehouse isolated item','EA',10,1)").lastrowid
        c.execute('INSERT INTO user_warehouse_assignments(user_id,warehouse_id,is_active)VALUES(?,?,1)',(user_id,a))
        for warehouse,location,qty,cost in [(a,la,10,10),(b,lb,20,25)]:
            c.execute('INSERT INTO inventory_stock(item_id,warehouse_id,location_id,quantity)VALUES(?,?,?,?)',(item,warehouse,location,qty))
            c.execute('INSERT INTO inventory_layers(item_id,warehouse_id,location_id,quantity_remaining,unit_cost,received_date)VALUES(?,?,?,?,?,date(\'now\'))',(item,warehouse,location,qty,cost))
    token = sign_token({'id':user_id,'tenant_key':'default'})
    return target, TestClient(app), {'Authorization':f'Bearer {token}'}, {'a':a,'b':b,'la':la,'lb':lb,'item':item,'employee':employee,'user_id':user_id}


def test_inventory_and_reports_only_return_authorized_warehouses(tmp_path,monkeypatch):
    _target,client,headers,data=setup_isolated_inventory(tmp_path,monkeypatch)
    valuation=client.get('/api/inventory/valuation',headers=headers)
    assert valuation.status_code==200
    row=next(row for row in valuation.json()if row['item_id']==data['item'])
    assert row['quantity']==10
    layers=client.get(f"/api/inventory/valuation/{data['item']}/layers",headers=headers).json()['layers']
    assert {row['warehouse_id']for row in layers}=={data['a']}
    report=client.get('/api/reports/fifo-valuation',headers=headers)
    assert report.status_code==200
    assert all(row['warehouse_name']=='Multi Warehouse A' for row in report.json() if row['item_code']=='MW-ITEM')
    forbidden=client.get('/api/inventory/valuation',params={'warehouse_id':data['b']},headers=headers)
    assert forbidden.status_code==403


def test_transfer_rejects_same_but_source_user_may_dispatch_to_destination(tmp_path,monkeypatch):
    _target,client,headers,data=setup_isolated_inventory(tmp_path,monkeypatch)
    base={'item_id':data['item'],'quantity':1,'from_warehouse_id':data['a'],'from_location_id':data['la']}
    same=client.post('/api/warehouse/transfers',headers=headers,json={**base,'to_warehouse_id':data['a'],'to_location_id':data['la']})
    assert same.status_code==400
    dispatched=client.post('/api/warehouse/transfers',headers=headers,json={**base,'to_warehouse_id':data['b'],'to_location_id':data['lb']})
    assert dispatched.status_code==201


def test_fifo_and_location_validation_are_warehouse_isolated(tmp_path,monkeypatch):
    target,_client,_headers,data=setup_isolated_inventory(tmp_path,monkeypatch)
    with database.transaction(immediate=True)as c:
        cost,used=consume(c,item_id=data['item'],warehouse_id=data['a'],location_id=data['la'],quantity=4)
        assert cost==40
        assert used and all(unit_cost==10 for _layer,_qty,unit_cost in used)
        try:
            receive(c,item_id=data['item'],warehouse_id=data['a'],location_id=data['lb'],quantity=1,unit_cost=10)
        except HTTPException as error:
            assert error.status_code==400
        else:
            raise AssertionError('Cross-warehouse location was accepted')
    with sqlite3.connect(target)as c:
        assert c.execute('SELECT quantity FROM inventory_stock WHERE item_id=?AND warehouse_id=?',(data['item'],data['a'])).fetchone()[0]==6
        assert c.execute('SELECT quantity FROM inventory_stock WHERE item_id=?AND warehouse_id=?',(data['item'],data['b'])).fetchone()[0]==20


def test_purchase_orders_and_attachments_follow_delivery_warehouse_scope(tmp_path,monkeypatch):
    target,client,headers,data=setup_isolated_inventory(tmp_path,monkeypatch)
    with sqlite3.connect(target)as c:
        supplier=c.execute("INSERT INTO suppliers(supplier_code,name)VALUES('MW-SUP','Scoped Supplier')").lastrowid
        allowed=c.execute("INSERT INTO purchase_orders(po_number,supplier_id,status,delivery_warehouse_id)VALUES('MW-PO-A',?,'Approved',?)",(supplier,data['a'])).lastrowid
        denied=c.execute("INSERT INTO purchase_orders(po_number,supplier_id,status,delivery_warehouse_id)VALUES('MW-PO-B',?,'Approved',?)",(supplier,data['b'])).lastrowid
    listed=client.get('/api/procurement/pos',headers=headers)
    assert listed.status_code==200
    assert {row['id']for row in listed.json()}=={allowed}
    assert client.get(f'/api/procurement/pos/{denied}',headers=headers).status_code==404
    assert client.get(f'/api/attachments/PO/{denied}',headers=headers).status_code==404


def test_tool_checkout_validates_employee_and_preserves_custody_history(tmp_path,monkeypatch):
    target,client,headers,data=setup_isolated_inventory(tmp_path,monkeypatch)
    with sqlite3.connect(target)as c:
        c.execute("UPDATE items SET consumable_returnable='Returnable' WHERE id=?",(data['item'],))
        tool=c.execute("INSERT INTO tools(tool_code,serial_number,item_id,warehouse_id,condition)VALUES('MW-TOOL','MW-SERIAL',?,?,'Good')",(data['item'],data['a'])).lastrowid
        inactive=c.execute("INSERT INTO employees(employee_code,name,status,system_access_yn)VALUES('MW-INACTIVE','Inactive Employee','Inactive',0)").lastrowid
    assert client.put(f'/api/advanced/tools/{tool}/checkout',headers=headers,json={'employee_id':inactive}).status_code==400
    assert client.put(f'/api/advanced/tools/{tool}/checkout',headers=headers,json={'employee_id':data['employee']}).status_code==200
    assert client.put(f'/api/advanced/tools/{tool}/checkout',headers=headers,json={'employee_id':data['employee']}).status_code==409
    assert client.put(f'/api/advanced/tools/{tool}/checkin',headers=headers,json={'condition':'Damaged'}).status_code==200
    with sqlite3.connect(target)as c:
        assert c.execute('SELECT employee_id,condition FROM tools WHERE id=?',(tool,)).fetchone()==(None,'Damaged')
        assert c.execute('SELECT employee_id,return_condition,status FROM tool_custody_history WHERE tool_id=?',(tool,)).fetchone()==(data['employee'],'Damaged','RETURNED')
