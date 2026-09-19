"""Deterministic, disposable baseline for legacy integration tests.

The shipped bootstrap database is intentionally schema-only. Older tests used to
copy the developer database and therefore silently depended on local demo data.
This hook creates a synthetic session database before test modules are imported.
"""
import atexit
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path


_root=Path(tempfile.mkdtemp(prefix='procuraflow-tests-'))
_database=_root/'baseline.db'
_bootstrap=Path(__file__).resolve().parents[1]/'app'/'bootstrap.db'
shutil.copy2(_bootstrap,_database)
os.environ['DB_PATH']=str(_database)
os.environ['TENANT_DATA_DIR']=str(_root/'tenants')

with sqlite3.connect(_database) as c:
    c.execute("INSERT INTO company(name,currency,base_currency,financial_year,country_code,time_zone)VALUES('Test Precast Co','SAR','SAR','2026','SA','Asia/Riyadh')")
    procurement=c.execute("INSERT INTO departments(name)VALUES('Procurement')").lastrowid
    warehouse_department=c.execute("INSERT INTO departments(name)VALUES('Warehouse')").lastrowid
    warehouse_a=c.execute("INSERT INTO warehouses(name,warehouse_code,site_name,operating_start_time,operating_end_time,time_zone,operation_24h_yn)VALUES('Test Main Warehouse','TMW','Test Factory','00:00','00:00','Asia/Riyadh',1)").lastrowid
    warehouse_b=c.execute("INSERT INTO warehouses(name,warehouse_code,site_name,operating_start_time,operating_end_time,time_zone,operation_24h_yn)VALUES('Test Secondary Warehouse','TSW','Test Yard','00:00','00:00','Asia/Riyadh',1)").lastrowid
    bin_a=c.execute("INSERT INTO locations(warehouse_id,type,code,label)VALUES(?,'Bin','TMW-BIN-001','Primary Bin')",(warehouse_a,)).lastrowid
    c.execute("INSERT INTO locations(warehouse_id,type,code,label)VALUES(?,'Bin','TSW-BIN-001','Secondary Bin')",(warehouse_b,))
    roles=[('SupplyChainManager',procurement,None,1000000),('PurchaseManager',procurement,None,100000),('PurchaseOfficer',procurement,None,10000),('WarehouseManager',warehouse_department,warehouse_a,50000),('WarehouseSupervisor',warehouse_department,warehouse_a,10000),('Storekeeper',warehouse_department,warehouse_a,1000)]
    employee_ids={};user_ids={}
    for index,(role,department,wid,limit) in enumerate(roles,1):
        employee=c.execute("INSERT INTO employees(employee_code,name,department_id,position,status,approval_limit,approval_role,warehouse_id,system_access_yn,country_code)VALUES(?,?,?,?, 'Active',?,?,?,?, 'SA')",(f'TEST-{index:03}',f'Test {role}',department,role,limit,role,wid,1)).lastrowid
        user=c.execute("INSERT INTO users(username,password_hash,full_name,role,is_active,warehouse_id,employee_id)VALUES(?,?,?,?,1,?,?)",(f'test.{role.lower()}','unused',f'Test {role}',role,wid,employee)).lastrowid
        employee_ids[role]=employee;user_ids[role]=user
        if wid:c.execute("INSERT INTO user_warehouse_assignments(user_id,warehouse_id,assignment_role,is_active,assigned_by)VALUES(?,?,?,1,?)",(user,wid,role,user_ids.get('SupplyChainManager',user)))
    c.execute('UPDATE employees SET reports_to_employee_id=? WHERE id IN (?,?)',(employee_ids['SupplyChainManager'],employee_ids['PurchaseManager'],employee_ids['WarehouseManager']))
    c.execute('UPDATE employees SET reports_to_employee_id=? WHERE id=?',(employee_ids['PurchaseManager'],employee_ids['PurchaseOfficer']))
    c.execute('UPDATE employees SET reports_to_employee_id=? WHERE id=?',(employee_ids['WarehouseManager'],employee_ids['WarehouseSupervisor']))
    c.execute('UPDATE employees SET reports_to_employee_id=? WHERE id=?',(employee_ids['WarehouseSupervisor'],employee_ids['Storekeeper']))
    inactive=c.execute("INSERT INTO employees(employee_code,name,department_id,status,approval_role,system_access_yn)VALUES('TEST-INACTIVE','Inactive Test Employee',?,'Inactive','Storekeeper',0)",(warehouse_department,)).lastrowid
    c.execute("INSERT INTO employee_work_calendar(employee_id,department_id,role_code,calendar_date,day_type,status,warehouse_id)VALUES(?,?,? ,date('now'),'WORKDAY','DRAFT',?)",(inactive,warehouse_department,'Storekeeper',warehouse_a))
    c.execute("INSERT INTO items(item_code,description,category,uom,purchase_uom,issue_uom,conversion_factor,standard_cost,reorder_level,default_warehouse_id,default_location_id)VALUES('TEST-ITEM-001','Synthetic Test Cement','Raw Material','KG','BAG','KG',50,12.5,20,?,?)",(warehouse_a,bin_a))
    c.execute("INSERT INTO items(item_code,description,category,uom,purchase_uom,issue_uom,conversion_factor,standard_cost,reorder_level,default_warehouse_id,default_location_id)VALUES('TEST-ITEM-002','Synthetic Test Tool','Tool','EA','EA','EA',1,100,2,?,?)",(warehouse_a,bin_a))
    c.execute("INSERT INTO suppliers(supplier_code,name,active_yn,blocked_yn,preferred_currency)VALUES('TEST-SUP-001','Synthetic Supplier',1,0,'SAR')")
    for code,name,symbol in [('SAR','Saudi Riyal','SAR'),('USD','US Dollar','$'),('EUR','Euro','EUR')]:c.execute('INSERT OR IGNORE INTO currencies(currency_code,currency_name,currency_symbol)VALUES(?,?,?)',(code,name,symbol))
    for key,value in [('procurement_shifts_enabled','1'),('warehouse_shifts_enabled','1')]:c.execute('INSERT OR REPLACE INTO settings(key,value)VALUES(?,?)',(key,value))
    for code,label,start,end,scope in [('MORNING','Morning','06:00','14:30','ALL'),('AFTERNOON','Afternoon','14:00','22:30','ALL'),('EVENING','Evening','22:00','06:30','ALL')]:c.execute('INSERT OR IGNORE INTO shifts(shift_code,shift_label,start_time,end_time,cross_midnight_yn,department_scope,schedule_mode)VALUES(?,?,?,?,?,?,\'MULTI\')',(code,label,start,end,int(end<start),scope))
    for code,label,start,end in [('TMW-1','First Shift','00:00','08:30'),('TMW-2','Second Shift','05:15','13:45'),('TMW-3','Third Shift','10:30','19:00'),('TMW-4','Night Shift','15:30','00:00')]:c.execute("INSERT INTO shifts(shift_code,shift_label,start_time,end_time,cross_midnight_yn,department_scope,warehouse_id,schedule_mode)VALUES(?,?,?,?,?,'Warehouse',?,'MULTI')",(code,label,start,end,int(end<=start),warehouse_a))
    c.commit()


@atexit.register
def _cleanup():
    shutil.rmtree(_root,ignore_errors=True)
