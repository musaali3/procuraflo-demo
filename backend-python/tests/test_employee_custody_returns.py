import shutil
import sqlite3

from fastapi.testclient import TestClient

from app import database
from app.main import app
from app.security import sign_token


def setup_return_custody(tmp_path, monkeypatch):
    path = tmp_path / 'employee-custody-returns.db'
    shutil.copy2(database.DB_PATH, path)
    monkeypatch.setattr(database, 'DB_PATH', path)
    with sqlite3.connect(path) as c:
        department = c.execute("SELECT id FROM departments WHERE lower(name)='warehouse'").fetchone()
        department = department[0] if department else c.execute("INSERT INTO departments(name)VALUES('Warehouse')").lastrowid
        manager_employee = c.execute("INSERT INTO employees(employee_code,name,department_id,approval_role,system_access_yn)VALUES('RET-MGR','Return Manager',?,'SupplyChainManager',1)",(department,)).lastrowid
        manager = c.execute("INSERT INTO users(employee_id,username,password_hash,full_name,role)VALUES(?,'return.manager','unused','Return Manager','SupplyChainManager')",(manager_employee,)).lastrowid
        employee_a = c.execute("INSERT INTO employees(employee_code,name,department_id,approval_role,system_access_yn)VALUES('RET-EMP-A','Alex Holder',?,'Helper',0)",(department,)).lastrowid
        employee_b = c.execute("INSERT INTO employees(employee_code,name,department_id,approval_role,system_access_yn)VALUES('RET-EMP-B','Blair Holder',?,'Helper',0)",(department,)).lastrowid
        warehouse = c.execute("INSERT INTO warehouses(warehouse_code,name)VALUES('RET-WH','Returns Warehouse')").lastrowid
        location = c.execute("INSERT INTO locations(warehouse_id,type,code,label)VALUES(?,'Bin','RET-BIN','Returns Bin')",(warehouse,)).lastrowid
        c.execute("INSERT INTO user_warehouse_assignments(user_id,warehouse_id,is_active)VALUES(?,?,1)",(manager,warehouse))
        item_a = c.execute("INSERT INTO items(item_code,description,uom,standard_cost,consumable_returnable)VALUES('RET-ITEM-A','Returnable Item A','EA',10,'Returnable')").lastrowid
        item_b = c.execute("INSERT INTO items(item_code,description,uom,standard_cost,consumable_returnable)VALUES('RET-ITEM-B','Returnable Item B','EA',20,'Returnable')").lastrowid
        for number,employee,item,quantity,value in [('RET-ISSUE-A1',employee_a,item_a,3,30),('RET-ISSUE-A2',employee_a,item_b,2,40),('RET-ISSUE-B1',employee_b,item_a,4,40)]:
            issue=c.execute("INSERT INTO material_issues(issue_number,employee_id,status,created_by)VALUES(?,?,'Posted',?)",(number,employee,manager)).lastrowid
            c.execute("INSERT INTO material_issue_items(issue_id,item_id,warehouse_id,location_id,quantity,value)VALUES(?,?,?,?,?,?)",(issue,item,warehouse,location,quantity,value))
        c.commit()
    token=sign_token({'id':manager,'username':'return.manager','full_name':'Return Manager','role':'SupplyChainManager','warehouse_id':warehouse,'warehouse_ids':[warehouse],'permission_keys':[]})
    return path,TestClient(app),{'Authorization':f'Bearer {token}'},employee_a,employee_b,item_a,item_b,warehouse,location


def test_custody_lookup_in_both_directions_and_atomic_multi_item_return(tmp_path,monkeypatch):
    path,client,headers,employee_a,employee_b,item_a,item_b,warehouse,location=setup_return_custody(tmp_path,monkeypatch)
    by_employee=client.get(f'/api/warehouse/returns/outstanding?employee_id={employee_a}',headers=headers)
    assert by_employee.status_code==200,by_employee.text
    assert {(row['item_id'],row['outstanding_quantity'])for row in by_employee.json()}=={(item_a,3),(item_b,2)}
    by_item=client.get(f'/api/warehouse/returns/outstanding?item_id={item_a}',headers=headers)
    assert by_item.status_code==200
    assert {row['employee_id']for row in by_item.json()}=={employee_a,employee_b}

    posted=client.post('/api/warehouse/returns',headers=headers,json={'employee_id':employee_a,'warehouse_id':warehouse,'location_id':location,'items':[
        {'item_id':item_a,'quantity':2,'condition':'Good'},
        {'item_id':item_b,'quantity':1,'condition':'Needs Repair'},
    ]})
    assert posted.status_code==201,posted.text
    assert posted.json()['count']==2
    remaining=client.get(f'/api/warehouse/returns/outstanding?employee_id={employee_a}',headers=headers).json()
    assert {(row['item_id'],row['outstanding_quantity'])for row in remaining}=={(item_a,1),(item_b,1)}
    with sqlite3.connect(path)as c:
        assert c.execute('SELECT COUNT(*)FROM returns WHERE employee_id=?',(employee_a,)).fetchone()[0]==2
        assert c.execute('SELECT COALESCE(SUM(quantity),0)FROM inventory_stock WHERE warehouse_id=?AND location_id=?',(warehouse,location)).fetchone()[0]==0
        assert c.execute("SELECT quantity FROM inventory_quarantine WHERE warehouse_id=?AND location_id=?AND inventory_status='PUT_AWAY_PENDING'",(warehouse,location)).fetchone()[0]==2
        quarantine=c.execute("SELECT quantity,inventory_status,unit_cost FROM inventory_quarantine WHERE warehouse_id=? AND inventory_status='REPAIR_PENDING'",(warehouse,)).fetchone()
        assert quarantine==(1,'REPAIR_PENDING',20)

    rejected=client.post('/api/warehouse/returns',headers=headers,json={'employee_id':employee_a,'warehouse_id':warehouse,'location_id':location,'items':[{'item_id':item_a,'quantity':2,'condition':'Good'}]})
    assert rejected.status_code==409
    with sqlite3.connect(path)as c:assert c.execute('SELECT COUNT(*)FROM returns WHERE employee_id=?',(employee_a,)).fetchone()[0]==2
