from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
import bcrypt,json,secrets
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError,available_timezones

from ..audit import log_audit
from ..crud import crud_router
from ..database import connect,fetch_all, fetch_one
from ..database import transaction
from ..permissions import defaults_for_role
from ..security import User, roles
from ..storage import upload_path
from ..stock import consume,receive,is_terminal_storage_location

router = APIRouter(prefix='/api/masters', tags=['masters'])
SIGNATURES=upload_path('signatures')
MGMT = ['SupplyChainManager','PurchaseManager','WarehouseManager']

router.include_router(crud_router('/company','company',['name','address','phone','email','website','registration_number','branch_info','logo_url','tax_info','currency','country_code','city_id','postal_code','region_province','financial_year'],soft_delete=True,write_roles=['SupplyChainManager']))
router.include_router(crud_router('/departments','departments',['name'],soft_delete=True,order_by='name',write_roles=MGMT))
router.include_router(crud_router('/suppliers','suppliers',['supplier_code','name','contact_person','phone','email','address','payment_terms','country_code','city_id','postal_code','region_province','preferred_currency'],soft_delete=True,order_by='name',write_roles=['SupplyChainManager','PurchaseManager','PurchaseOfficer'],auto_code=('supplier_code','SUP'),duplicate_fields=('name',),immutable_fields=('supplier_code',)))
router.include_router(crud_router('/items','items',['item_code','description','category','subcategory','uom','purchase_uom','issue_uom','conversion_factor','consumable_returnable','high_value_flag','always_approval_yn','tool_control_yn','batch_control_yn','expiry_control_yn','inspection_required_yn','min_stock','max_stock','reorder_level','standard_cost','last_purchase_price','active_yn','replacement_item_id','duplicate_status'],soft_delete=True,order_by='item_code',write_roles=['SupplyChainManager','PurchaseManager','PurchaseOfficer','WarehouseManager','WarehouseSupervisor','Storekeeper'],auto_code=('item_code','ITM'),duplicate_fields=('description',),immutable_fields=('item_code',)))

@router.get('/employee-directory')
def employee_directory(_user: User):
    return fetch_all('''SELECT e.id,e.employee_code,e.name,e.department_id,e.warehouse_id,e.approval_role,d.name department_name,e.position,
      COALESCE((SELECT '['||group_concat(warehouse_id)||']' FROM employee_warehouse_assignments WHERE employee_id=e.id AND active_yn=1 AND warehouse_id IS NOT NULL),'[]') warehouse_ids_json,
      COALESCE((SELECT MAX(all_warehouses_yn) FROM employee_warehouse_assignments WHERE employee_id=e.id AND active_yn=1),0) all_warehouses_yn
      FROM employees e LEFT JOIN departments d ON d.id=e.department_id WHERE e.deleted_at IS NULL AND e.status='Active' ORDER BY e.name''')

@router.get('/employees')
def employees(_user: dict = Depends(roles(*MGMT))):
    return fetch_all('''SELECT e.*,d.name department_name,w.name warehouse_name,
      COALESCE((SELECT group_concat(w2.name, ', ') FROM employee_warehouse_assignments ewa JOIN warehouses w2 ON w2.id=ewa.warehouse_id WHERE ewa.employee_id=e.id AND ewa.active_yn=1 AND ewa.all_warehouses_yn=0),'') assigned_warehouses,
      (SELECT MAX(all_warehouses_yn) FROM employee_warehouse_assignments WHERE employee_id=e.id AND active_yn=1) all_warehouses_yn,
      (SELECT '['||group_concat(warehouse_id)||']' FROM employee_warehouse_assignments WHERE employee_id=e.id AND active_yn=1 AND warehouse_id IS NOT NULL) warehouse_ids_json,
      (SELECT u.username FROM users u WHERE u.employee_id=e.id AND u.deleted_at IS NULL ORDER BY u.is_active DESC,u.id DESC LIMIT 1) login_id
      FROM employees e LEFT JOIN departments d ON d.id=e.department_id LEFT JOIN warehouses w ON w.id=e.warehouse_id
      WHERE e.deleted_at IS NULL AND lower(COALESCE(d.name,'')) IN ('warehouse','procurement') ORDER BY e.name''')

@router.get('/general-employees')
def general_employees(_user: User):
    return fetch_all('''SELECT e.*,d.name department_name FROM employees e JOIN departments d ON d.id=e.department_id
      WHERE e.deleted_at IS NULL AND lower(d.name) NOT IN ('warehouse','procurement') ORDER BY d.name,e.name,e.employee_code''')

@router.post('/general-employees',status_code=201)
def create_general_employee(body:dict,user:User):
    return create_company_employee(body,user)

@router.post('/general-employees/quick',status_code=201)
def quick_general_employee(body:dict,user:User):
    return create_company_employee(body,user)

@router.put('/general-employees/{employee_id}')
def update_general_employee(employee_id:int,body:dict,user:dict=Depends(roles(*MGMT))):
    existing=fetch_one('SELECT id FROM employees WHERE id=? AND deleted_at IS NULL',(employee_id,))
    if not existing:raise HTTPException(404,'Employee not found')
    department=fetch_one('SELECT name FROM departments WHERE id=? AND deleted_at IS NULL',(body.get('department_id'),))
    if not department or department['name'].strip().lower() in ('warehouse','procurement'):raise HTTPException(400,'Select a general company department')
    name=str(body.get('name')or'').strip()
    if not name:raise HTTPException(400,'Employee name is required')
    with transaction(immediate=True)as c:
        c.execute('UPDATE employees SET name=?,department_id=?,position=?,email=?,payroll_number=?,status=? WHERE id=?',(name,body['department_id'],body.get('position'),str(body.get('email')or'').strip()or None,str(body.get('payroll_number')or'').strip()or None,body.get('status')or'Active',employee_id))
        log_audit(c,'employees',employee_id,'UPDATE',user['id'],after={'name':name,'department_id':body['department_id'],'employee_scope':'GENERAL'})
    return fetch_one('SELECT e.*,d.name department_name FROM employees e JOIN departments d ON d.id=e.department_id WHERE e.id=?',(employee_id,))

@router.delete('/general-employees/{employee_id}')
def delete_general_employee(employee_id:int,user:dict=Depends(roles(*MGMT))):
    with transaction(immediate=True)as c:
        c.execute("UPDATE employees SET status='Inactive',deleted_at=datetime('now'),system_access_yn=0 WHERE id=?",(employee_id,));log_audit(c,'employees',employee_id,'DELETE',user['id'],after={'employee_scope':'GENERAL','soft_deleted':True})
    return {'success':True,'softDeleted':True}

def create_company_employee(body:dict,user:dict):
    name=str(body.get('name')or'').strip()
    try:department_id=int(body.get('department_id'))
    except (TypeError,ValueError):department_id=0
    if not name or department_id<=0:raise HTTPException(400,'Employee name and department are required')
    department=fetch_one('SELECT id,name FROM departments WHERE id=? AND deleted_at IS NULL',(department_id,))
    if not department:raise HTTPException(400,'Select a valid active department')
    if any(word in department['name'].strip().lower() for word in ('warehouse','procurement','purchas')):raise HTTPException(400,'Warehouse and Procurement employees must be created in Supply Chain Employees')
    seq=(fetch_one("SELECT MAX(CAST(SUBSTR(employee_code,5)AS INTEGER)) sequence FROM employees WHERE employee_code GLOB 'EMP-[0-9]*'")or{}).get('sequence')or 0;code=f'EMP-{seq+1:04d}'
    with transaction(immediate=True)as c:
        cur=c.execute("INSERT INTO employees(employee_code,name,first_name,last_name,department_id,position,email,payroll_number,status,approval_role,permission_keys,system_access_yn) VALUES(?,?,?,?,?,?,?,?,?,'Helper','[]',0)",(code,name,str(body.get('first_name')or'').strip()or None,str(body.get('last_name')or'').strip()or None,department_id,body.get('position'),str(body.get('email')or'').strip()or None,str(body.get('payroll_number')or'').strip()or None,body.get('status')or'Active'))
        log_audit(c,'employees',cur.lastrowid,'CREATE',user['id'],after={'employee_code':code,'name':name,'department_id':department_id,'employee_scope':'GENERAL'});eid=cur.lastrowid
    return fetch_one('SELECT e.*,d.name department_name FROM employees e JOIN departments d ON d.id=e.department_id WHERE e.id=?',(eid,))

@router.get('/role-permission-defaults')
def role_defaults(_user: dict = Depends(roles('SupplyChainManager'))):
    names=['SupplyChainManager','PurchaseManager','PurchaseOfficer','WarehouseManager','WarehouseSupervisor','Storekeeper','Helper']
    return {name: defaults_for_role(name) for name in names}

@router.get('/operational-items')
def operational_items(_user: User):
    return fetch_all('SELECT i.*,COALESCE((SELECT SUM(s.quantity)FROM inventory_stock s WHERE s.item_id=i.id),0)available_stock FROM items i WHERE i.deleted_at IS NULL AND i.active_yn<>0 ORDER BY i.item_code')

@router.get('/warehouses')
def warehouses(user: User):
    with transaction(immediate=True) as connection:
        missing=connection.execute("SELECT id FROM warehouses WHERE trim(COALESCE(warehouse_code,''))='' ORDER BY id").fetchall()
        used={str(row['warehouse_code']).upper() for row in connection.execute("SELECT warehouse_code FROM warehouses WHERE trim(COALESCE(warehouse_code,''))<>''")}
        sequence=1
        for row in missing:
            while f'WH{sequence:02d}' in used:sequence+=1
            code=f'WH{sequence:02d}';connection.execute('UPDATE warehouses SET warehouse_code=? WHERE id=?',(code,row['id']));used.add(code);sequence+=1
    ids=user['warehouse_ids']
    company_scope=user['role'] in ['SupplyChainManager','PurchaseManager','PurchaseOfficer']
    rows=fetch_all('SELECT * FROM warehouses WHERE deleted_at IS NULL ORDER BY name')if company_scope else fetch_all(f"SELECT * FROM warehouses WHERE deleted_at IS NULL AND id IN({','.join('?'for _ in ids)or'NULL'}) ORDER BY name",ids)
    for row in rows:
        try:row['operating_days']=json.loads(row.get('operating_days_json')or'[]')
        except ValueError:row['operating_days']=[]
        row.pop('replenishment_days_json',None);row.pop('auto_replenishment_enabled',None)
        row['operating_schedule']=fetch_all('SELECT weekday,is_open,open_time,close_time,cross_midnight_yn FROM warehouse_operating_schedules WHERE warehouse_id=? ORDER BY weekday',(row['id'],))
    return rows

def warehouse_deactivation_readiness(connection,warehouse_id):
    warehouse=connection.execute('SELECT * FROM warehouses WHERE id=?',(warehouse_id,)).fetchone()
    if not warehouse:return None
    stock=list(connection.execute("""SELECT i.item_code,i.description,l.code location_code,s.quantity FROM inventory_stock s JOIN items i ON i.id=s.item_id
      LEFT JOIN locations l ON l.id=s.location_id WHERE s.warehouse_id=? AND ABS(s.quantity)>.000001 ORDER BY i.item_code,l.code""",(warehouse_id,)).fetchall())
    fifo=list(connection.execute("""SELECT i.item_code,i.description,l.code location_code,il.batch,il.quantity_remaining,il.unit_cost FROM inventory_layers il JOIN items i ON i.id=il.item_id
      LEFT JOIN locations l ON l.id=il.location_id WHERE il.warehouse_id=? AND il.quantity_remaining>.000001 ORDER BY il.received_date,il.id""",(warehouse_id,)).fetchall())
    definitions=[
      ('Active Stock Reservations',"SELECT r.id record_id,i.item_code,r.quantity,r.status,r.reference_type,r.reference_id FROM stock_reservations r JOIN items i ON i.id=r.item_id WHERE r.warehouse_id=? AND lower(r.status)='active'"),
      ('Transfers In Transit',"SELECT id record_id,transfer_number reference,status,from_warehouse_id,to_warehouse_id FROM transfers WHERE(from_warehouse_id=? OR to_warehouse_id=?)AND status='In Transit'"),
      ('Open Material Issues',"SELECT DISTINCT mi.id record_id,mi.issue_number reference,mi.status FROM material_issues mi JOIN material_issue_items mii ON mii.issue_id=mi.id WHERE mii.warehouse_id=? AND mi.status IN('PendingApproval','Approved')"),
      ('Pending Stock Adjustments',"SELECT id record_id,adjustment_number reference,status FROM stock_adjustments WHERE warehouse_id=? AND status='Pending'"),
      ('Open Cycle Counts',"SELECT id record_id,count_number reference,status FROM cycle_counts WHERE warehouse_id=? AND status IN('Draft','Counted')"),
      ('Issued Tools',"SELECT id record_id,tool_code reference,condition,employee_id FROM tools WHERE warehouse_id=? AND issue_date IS NOT NULL AND return_date IS NULL"),
      ('Active Employees',"SELECT id record_id,employee_code reference,name,status FROM employees WHERE warehouse_id=? AND deleted_at IS NULL AND status='Active'")]
    tasks=[]
    if stock:tasks.append({'category':'Stock Balance Must Be Zero','count':len(stock),'records':[dict(row)for row in stock]})
    if fifo:tasks.append({'category':'FIFO Quantity Must Be Zero','count':len(fifo),'records':[dict(row)for row in fifo]})
    for category,sql in definitions:
        params=(warehouse_id,warehouse_id)if category=='Transfers In Transit'else(warehouse_id,);records=[dict(row)for row in connection.execute(sql,params).fetchall()]
        if records:tasks.append({'category':category,'count':len(records),'records':records})
    stock_quantity=sum(float(row['quantity'])for row in stock);fifo_quantity=sum(float(row['quantity_remaining'])for row in fifo)
    return {'warehouse':dict(warehouse),'ready':not tasks,'open_task_count':sum(item['count']for item in tasks),'stock_quantity':stock_quantity,'fifo_quantity':fifo_quantity,'open_tasks':tasks}

def warehouse_deactivation_snapshot(connection,warehouse_id,readiness):
    queries={
      'stock_balances':"SELECT s.*,i.item_code,i.description,l.code location_code FROM inventory_stock s JOIN items i ON i.id=s.item_id LEFT JOIN locations l ON l.id=s.location_id WHERE s.warehouse_id=?",
      'fifo_layers':"SELECT il.*,i.item_code,i.description,l.code location_code FROM inventory_layers il JOIN items i ON i.id=il.item_id LEFT JOIN locations l ON l.id=il.location_id WHERE il.warehouse_id=?",
      'stock_ledger':"SELECT sl.*,i.item_code FROM stock_ledger sl JOIN items i ON i.id=sl.item_id WHERE sl.warehouse_id=? ORDER BY sl.id",
      'grns':"SELECT g.grn_number,g.grn_date,g.po_id,g.supplier_id,g.delivery_note,gi.* FROM grns g JOIN grn_items gi ON gi.grn_id=g.id WHERE gi.warehouse_id=? ORDER BY g.id,gi.id",
      'material_issues':"SELECT mi.issue_number,mi.issue_date,mi.status,mi.employee_id,mii.* FROM material_issues mi JOIN material_issue_items mii ON mii.issue_id=mi.id WHERE mii.warehouse_id=? ORDER BY mi.id,mii.id",
      'returns':"SELECT * FROM returns WHERE warehouse_id=? ORDER BY id",
      'transfers':"SELECT * FROM transfers WHERE from_warehouse_id=? OR to_warehouse_id=? ORDER BY id",
      'transfer_receipts':"SELECT * FROM transfer_receipts WHERE warehouse_id=? ORDER BY id",
      'bin_transfers':"SELECT * FROM bin_transfers WHERE warehouse_id=? ORDER BY id",
      'adjustments':"SELECT * FROM stock_adjustments WHERE warehouse_id=? ORDER BY id",
      'cycle_counts':"SELECT cc.*,cci.item_id,cci.system_qty,cci.counted_qty,cci.variance FROM cycle_counts cc LEFT JOIN cycle_count_items cci ON cci.count_id=cc.id WHERE cc.warehouse_id=? ORDER BY cc.id,cci.id",
      'tools':"SELECT * FROM tools WHERE warehouse_id=? ORDER BY id"}
    snapshot={'readiness':readiness,'reports':{}}
    for name,sql in queries.items():
        params=(warehouse_id,warehouse_id)if name=='transfers'else(warehouse_id,);snapshot['reports'][name]=[dict(row)for row in connection.execute(sql,params).fetchall()]
    return snapshot

@router.get('/warehouses/deactivation-reports')
def deactivation_reports(_user:dict=Depends(roles('SupplyChainManager'))):
    rows=fetch_all("SELECT r.id,r.report_number,r.warehouse_id,r.warehouse_code,r.warehouse_name,r.deactivation_reason,r.stock_quantity,r.fifo_quantity,r.open_task_count,r.deactivated_at,u.full_name deactivated_by_name FROM warehouse_deactivation_reports r JOIN users u ON u.id=r.deactivated_by ORDER BY r.id DESC")
    return rows

@router.get('/warehouses/deactivation-reports/{report_id}')
def deactivation_report(report_id:int,_user:dict=Depends(roles('SupplyChainManager'))):
    row=fetch_one("SELECT r.*,u.full_name deactivated_by_name FROM warehouse_deactivation_reports r JOIN users u ON u.id=r.deactivated_by WHERE r.id=?",(report_id,))
    if not row:raise HTTPException(404,'Warehouse deactivation report not found')
    row['snapshot']=json.loads(row.pop('snapshot_json'));return row

@router.get('/warehouses/{warehouse_id}/deactivation-readiness')
def deactivation_readiness(warehouse_id:int,_user:dict=Depends(roles('SupplyChainManager'))):
    with connect()as c:result=warehouse_deactivation_readiness(c,warehouse_id)
    if not result or result['warehouse'].get('deleted_at'):raise HTTPException(404,'Active warehouse not found')
    return result

@router.post('/warehouses/{warehouse_id}/deactivate')
def deactivate_warehouse(warehouse_id:int,body:dict,user:dict=Depends(roles('SupplyChainManager'))):
    reason=str(body.get('reason')or'').strip()
    if len(reason)<5:raise HTTPException(400,'Enter a clear warehouse deactivation reason')
    with transaction(immediate=True)as c:
        readiness=warehouse_deactivation_readiness(c,warehouse_id)
        if not readiness or readiness['warehouse'].get('deleted_at'):raise HTTPException(404,'Active warehouse not found')
        if not readiness['ready']:raise HTTPException(409,f"Warehouse cannot be deactivated. Close {readiness['open_task_count']} open task(s) and reduce stock and FIFO quantities to zero first.")
        snapshot=warehouse_deactivation_snapshot(c,warehouse_id,readiness);warehouse=readiness['warehouse'];report_number=f"WDR-{datetime.now().strftime('%Y%m%d%H%M%S')}-{warehouse_id}"
        cur=c.execute("""INSERT INTO warehouse_deactivation_reports(report_number,warehouse_id,warehouse_code,warehouse_name,deactivation_reason,stock_quantity,fifo_quantity,open_task_count,snapshot_json,deactivated_by)
          VALUES(?,?,?,?,?,?,?,?,?,?)""",(report_number,warehouse_id,warehouse.get('warehouse_code')or f'WH-{warehouse_id}',warehouse['name'],reason,readiness['stock_quantity'],readiness['fifo_quantity'],readiness['open_task_count'],json.dumps(snapshot,default=str),user['id']))
        c.execute("UPDATE warehouses SET deleted_at=datetime('now') WHERE id=? AND deleted_at IS NULL",(warehouse_id,));c.execute('UPDATE shifts SET active_yn=0 WHERE warehouse_id=?',(warehouse_id,));c.execute('UPDATE locations SET deleted_at=COALESCE(deleted_at,datetime(\'now\')) WHERE warehouse_id=?',(warehouse_id,));c.execute('UPDATE warehouse_operating_schedules SET is_open=0,updated_by=?,updated_at=datetime(\'now\') WHERE warehouse_id=?',(user['id'],warehouse_id));c.execute("UPDATE user_warehouse_assignments SET is_active=0,effective_to=COALESCE(effective_to,date('now')) WHERE warehouse_id=? AND is_active=1",(warehouse_id,));c.execute("UPDATE employee_warehouse_assignments SET active_yn=0,effective_to=COALESCE(effective_to,date('now')) WHERE warehouse_id=? AND active_yn=1",(warehouse_id,));c.execute("UPDATE employee_work_calendar SET day_type='OFF',shift_id=NULL,shift_start=NULL,shift_end=NULL,remarks='Warehouse Deactivated',updated_at=datetime('now'),updated_by=? WHERE warehouse_id=? AND calendar_date>=date('now') AND manual_override_yn=0",(user['id'],warehouse_id))
        log_audit(c,'warehouses',warehouse_id,'DELETE',user['id'],warehouse,{**warehouse,'deleted_at':'now','deactivation_reason':reason,'deactivation_report_id':cur.lastrowid,'deactivation_report_number':report_number})
    return {'success':True,'warehouse_id':warehouse_id,'report_id':cur.lastrowid,'report_number':report_number,'message':f'{warehouse["name"]} deactivated. The complete warehouse history was retained in report {report_number}.'}

@router.delete('/warehouses/{warehouse_id}')
def delete_warehouse(warehouse_id:int,body:dict,user:dict=Depends(roles('SupplyChainManager'))):
    return deactivate_warehouse(warehouse_id,body,user)

@router.get('/locations')
def locations(user: User):
    ids=user['warehouse_ids']
    select_sql='SELECT l.*,w.name warehouse_name,w.site_name,p.code parent_code,p.label parent_label FROM locations l JOIN warehouses w ON w.id=l.warehouse_id LEFT JOIN locations p ON p.id=l.parent_id WHERE l.deleted_at IS NULL'
    rows=fetch_all(select_sql+(' ORDER BY w.name,l.code'if user['role']=='SupplyChainManager'else f" AND l.warehouse_id IN({','.join('?'for _ in ids)or'NULL'}) ORDER BY w.name,l.code"),()if user['role']=='SupplyChainManager'else ids);by_id={row['id']:row for row in rows}
    for row in rows:
        path=[];cursor=row;seen=set()
        while cursor and cursor['id']not in seen:seen.add(cursor['id']);path.append(cursor.get('label')or cursor.get('code'));cursor=by_id.get(cursor.get('parent_id'))
        row['hierarchy_path']=' > '.join(reversed(path));row['is_terminal_storage']=is_terminal_storage_location(row)
    return rows

def warehouse_window(body,existing=None):
    start=str(body.get('operating_start_time')or(existing or{}).get('operating_start_time')or'00:00')[:5]
    end=str(body.get('operating_end_time')or(existing or{}).get('operating_end_time')or'00:00')[:5]
    try:
        sh,sm=map(int,start.split(':'));eh,em=map(int,end.split(':'))
        if not(0<=sh<24 and 0<=eh<24 and 0<=sm<60 and 0<=em<60):raise ValueError
    except(ValueError,TypeError):raise HTTPException(400,'Warehouse operating times must use HH:MM format')
    duration=((eh*60+em)-(sh*60+sm))%1440 or 1440
    if duration<60 or duration>1440:raise HTTPException(400,'Warehouse operating window must be between 1 and 24 hours')
    return start,end,duration

def warehouse_operating_configuration(body,existing=None):
    time_zone=str(body.get('time_zone')or(existing or{}).get('time_zone')or'').strip()
    try:ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError,ValueError):raise HTTPException(400,'Select a valid IANA warehouse time zone')
    operation_24h=int(bool(body.get('operation_24h_yn',(existing or{}).get('operation_24h_yn',0))))
    days=body.get('operating_days')
    if days is None:
        try:days=json.loads((existing or{}).get('operating_days_json')or'[0,1,2,3,4,5,6]')
        except (TypeError,ValueError):days=list(range(7))
    try:days=sorted(set(int(day)for day in days));assert days and all(0<=day<=6 for day in days)
    except (TypeError,ValueError,AssertionError):raise HTTPException(400,'Select at least one valid operating day')
    schedules=body.get('operating_schedule')
    if schedules is not None:
        if not isinstance(schedules,list):raise HTTPException(400,'Operating schedule must contain day-specific rows')
        seen=set()
        for row in schedules:
            try:weekday=int(row.get('weekday'));assert 0<=weekday<=6 and weekday not in seen;seen.add(weekday)
            except (TypeError,ValueError,AssertionError):raise HTTPException(400,'Each day-specific schedule must identify one unique weekday')
            if row.get('is_open'):
                warehouse_window({'operating_start_time':row.get('open_time'),'operating_end_time':row.get('close_time')})
    return time_zone,operation_24h,days,schedules

def save_operating_schedule(connection,warehouse_id,days,start,end,operation_24h,schedules,user_id):
    configured={int(row['weekday']):row for row in(schedules or[])}
    for weekday in range(7):
        row=configured.get(weekday);is_open=int(weekday in days and bool(row.get('is_open')))if row is not None else int(weekday in days)
        open_time='00:00'if operation_24h else(str(row.get('open_time'))[:5]if row and is_open else start if is_open else None)
        close_time='00:00'if operation_24h else(str(row.get('close_time'))[:5]if row and is_open else end if is_open else None)
        cross=int(bool(is_open and close_time<=open_time))
        connection.execute("""INSERT INTO warehouse_operating_schedules(warehouse_id,weekday,is_open,open_time,close_time,cross_midnight_yn,created_by)
          VALUES(?,?,?,?,?,?,?)ON CONFLICT(warehouse_id,weekday)DO UPDATE SET is_open=excluded.is_open,open_time=excluded.open_time,
          close_time=excluded.close_time,cross_midnight_yn=excluded.cross_midnight_yn,updated_by=excluded.created_by,updated_at=datetime('now')""",(warehouse_id,weekday,is_open,open_time,close_time,cross,user_id))

@router.get('/time-zones')
def time_zones(_user:User):return sorted(available_timezones())

def automatic_shift_design(start,duration):
    start_minutes=int(start[:2])*60+int(start[3:5]);design=[]
    if duration<=480:
        break_minutes=30 if duration>=360 else(15 if duration>=240 else 0);offsets=[0];scheduled_lengths=[duration]
    else:
        break_minutes=30;scheduled_minutes=480;final_offset=duration-scheduled_minutes
        count=max(2,(final_offset+359)//360+1)
        offsets=[0]
        for index in range(1,count-1):
            raw_start=start_minutes+(index*final_offset/(count-1));standard_start=int((raw_start+15)//30)*30
            offsets.append(standard_start-start_minutes)
        offsets.append(final_offset);scheduled_lengths=[scheduled_minutes]*count
    for offset,scheduled_minutes in zip(offsets,scheduled_lengths):
        finish=start_minutes+offset+scheduled_minutes;working_minutes=scheduled_minutes-break_minutes
        sequence=len(design)+1;label='Night Shift' if sequence==4 else['First Shift','Second Shift','Third Shift'][sequence-1]
        design.append({'sequence':sequence,'shift_label':label,'start_time':f'{((start_minutes+offset)%1440)//60:02d}:{(start_minutes+offset)%60:02d}','end_time':f'{(finish%1440)//60:02d}:{finish%60:02d}','working_minutes':working_minutes,'break_minutes':break_minutes,'scheduled_minutes':scheduled_minutes,'cross_midnight_yn':int((start_minutes+offset)%1440+scheduled_minutes>=1440)})
    return design

def create_warehouse_shifts(connection,warehouse_id,start,duration,shifts_enabled=True,regenerate_multi=True):
    start_minutes=int(start[:2])*60+int(start[3:5])
    design=automatic_shift_design(start,duration);count=len(design)
    labels=['First Shift','Second Shift','Third Shift','Night Shift']
    existing=list(connection.execute("SELECT * FROM shifts WHERE warehouse_id=? AND schedule_mode='MULTI'",(warehouse_id,)).fetchall())
    existing.sort(key=lambda row:(((int(row['start_time'][:2])*60+int(row['start_time'][3:5]))-start_minutes)%1440,row['id']))
    for index in range(count if regenerate_multi else 0):
        proposed=design[index];times=(proposed['start_time'],proposed['end_time'],proposed['cross_midnight_yn']);break_minutes=proposed['break_minutes']
        if index<len(existing):
            connection.execute('UPDATE shifts SET shift_label=?,start_time=?,end_time=?,cross_midnight_yn=?,break_minutes=?,active_yn=? WHERE id=?',(proposed['shift_label'],)+times+(break_minutes,int(bool(shifts_enabled)),existing[index]['id']))
            connection.execute("UPDATE employee_work_calendar SET shift_start=?,shift_end=? WHERE shift_id=? AND calendar_date>=date('now') AND manual_override_yn=0",(times[0],times[1],existing[index]['id']))
        else:connection.execute("""INSERT INTO shifts(shift_code,shift_label,start_time,end_time,cross_midnight_yn,break_minutes,department_scope,active_yn,warehouse_id,schedule_mode)
            VALUES(?,?,?,?,?,?,'Warehouse',?,?, 'MULTI')""",(f'WH{warehouse_id}-SHIFT-{index+1}',labels[index]if index<len(labels)else f'Shift {index+1}',*times,break_minutes,int(bool(shifts_enabled)),warehouse_id))
    if regenerate_multi:
        for row in existing[count:]:connection.execute('UPDATE shifts SET active_yn=0 WHERE id=?',(row['id'],))
    else:
        for index,row in enumerate(existing):connection.execute('UPDATE shifts SET active_yn=? WHERE id=?',(int(bool(shifts_enabled)and index<count),row['id']))
    standard_break=30 if duration>=360 else(15 if duration>=240 else 0);finish_minutes=(start_minutes+duration)%1440;end=f'{finish_minutes//60:02d}:{finish_minutes%60:02d}'
    standard=connection.execute("SELECT id FROM shifts WHERE warehouse_id=? AND schedule_mode='STANDARD'",(warehouse_id,)).fetchone()
    standard_values=(start,end,int(start_minutes+duration>=1440),standard_break,int(not shifts_enabled))
    if standard:
        connection.execute("UPDATE shifts SET start_time=?,end_time=?,cross_midnight_yn=?,break_minutes=?,active_yn=? WHERE id=?",standard_values+(standard['id'],))
    else:
        connection.execute("""INSERT INTO shifts(shift_code,shift_label,start_time,end_time,cross_midnight_yn,break_minutes,department_scope,active_yn,warehouse_id,schedule_mode)
            VALUES(?,?,?, ?,?,?,'Warehouse',?,?,'STANDARD')""",(f'WH{warehouse_id}-STANDARD','Standard Operating Hours',*standard_values,warehouse_id))

@router.post('/warehouses',status_code=201)
def create_warehouse(body:dict,user:dict=Depends(roles('SupplyChainManager','WarehouseManager'))):
    body={key:value for key,value in body.items() if key!='warehouse_code'}
    start,end,duration=warehouse_window(body);time_zone,operation_24h,days,schedules=warehouse_operating_configuration(body);body={**body,'operating_start_time':start,'operating_end_time':end,'time_zone':time_zone,'operation_24h_yn':operation_24h,'operating_days_json':json.dumps(days),'shifts_enabled_yn':int(bool(body.get('shifts_enabled_yn',1)))}
    body['auto_replenishment_enabled']=0
    fields=['warehouse_code','name','site_type','site_name','address','city','country_code','city_id','postal_code','region_province','operating_start_time','operating_end_time','time_zone','operation_24h_yn','operating_days_json','shifts_enabled_yn','auto_replenishment_enabled'];keys=[k for k in fields if body.get(k)not in[None,'']]
    with transaction(immediate=True)as c:
        sequence=c.execute('SELECT COALESCE(MAX(id),0)+1 n FROM warehouses').fetchone()['n'];body['warehouse_code']=f'WH{sequence:02d}';keys=['warehouse_code',*keys]
        cur=c.execute(f"INSERT INTO warehouses({','.join(keys)})VALUES({','.join('?'for _ in keys)})",tuple(body[k]for k in keys));rid=cur.lastrowid;create_warehouse_shifts(c,rid,start,duration,bool(body['shifts_enabled_yn']));save_operating_schedule(c,rid,days,start,end,operation_24h,schedules,user['id']);log_audit(c,'warehouses',rid,'CREATE',user['id'],after={**body,'operating_duration_minutes':duration,'operating_schedule':schedules})
    return fetch_one('SELECT * FROM warehouses WHERE id=?',(rid,))

@router.post('/warehouses/{warehouse_id}/shift-design-preview')
def preview_warehouse_shift_design(warehouse_id:int,body:dict,user:dict=Depends(roles('SupplyChainManager'))):
    existing=fetch_one('SELECT * FROM warehouses WHERE id=? AND deleted_at IS NULL',(warehouse_id,))
    if not existing:raise HTTPException(404,'Warehouse not found')
    start,end,duration=warehouse_window(body,existing);enabled=int(bool(body.get('shifts_enabled_yn',existing.get('shifts_enabled_yn',1))))
    standard_break=30 if duration>=360 else(15 if duration>=240 else 0);finish=int(end[:2])*60+int(end[3:5])
    design=automatic_shift_design(start,duration)if enabled else[{'sequence':1,'start_time':start,'end_time':f'{finish//60:02d}:{finish%60:02d}','working_minutes':max(0,duration-standard_break),'break_minutes':standard_break,'scheduled_minutes':duration}]
    return {'warehouse_id':warehouse_id,'warehouse_name':existing['name'],'operating_start_time':start,'operating_end_time':end,'operating_duration_minutes':duration,'shifts_enabled_yn':enabled,'minimum_overlap_minutes':120,'proposed_shifts':design,'requires_confirmation':True}

@router.put('/warehouses/{warehouse_id}')
def update_warehouse(warehouse_id:int,body:dict,user:dict=Depends(roles('SupplyChainManager'))):
    existing=fetch_one('SELECT * FROM warehouses WHERE id=? AND deleted_at IS NULL',(warehouse_id,))
    if not existing:raise HTTPException(404,'Warehouse not found')
    start,end,duration=warehouse_window(body,existing);time_zone,operation_24h,days,schedules=warehouse_operating_configuration(body,existing);fields=['name','site_type','site_name','address','city','country_code','city_id','postal_code','region_province','operating_start_time','operating_end_time','time_zone','operation_24h_yn','operating_days_json','shifts_enabled_yn'];values={**existing,**body,'operating_start_time':start,'operating_end_time':end,'time_zone':time_zone,'operation_24h_yn':operation_24h,'operating_days_json':json.dumps(days),'shifts_enabled_yn':int(bool(body.get('shifts_enabled_yn',existing.get('shifts_enabled_yn',1))))};keys=[key for key in fields if key in body or key in('operating_start_time','operating_end_time','time_zone','operation_24h_yn','operating_days_json')]
    times_changed=start!=existing.get('operating_start_time')or end!=existing.get('operating_end_time')
    if times_changed and not body.get('confirm_shift_design'):raise HTTPException(409,'Operating-time changes require review and confirmation of the automatically designed shift schedule.')
    with transaction(immediate=True)as c:
        c.execute(f"UPDATE warehouses SET {','.join(key+'=?'for key in keys)} WHERE id=?",tuple(values[key]for key in keys)+(warehouse_id,))
        create_warehouse_shifts(c,warehouse_id,start,duration,bool(values['shifts_enabled_yn']),times_changed)
        save_operating_schedule(c,warehouse_id,days,start,end,operation_24h,schedules,user['id'])
        log_audit(c,'warehouses',warehouse_id,'UPDATE',user['id'],existing,{**values,'operating_duration_minutes':duration,'operating_schedule':schedules,'automatic_shift_design':automatic_shift_design(start,duration)if times_changed and values['shifts_enabled_yn']else None,'manager_confirmed':bool(body.get('confirm_shift_design'))})
    return fetch_one('SELECT * FROM warehouses WHERE id=?',(warehouse_id,))

LOCATION_PARENTS={'Zone':set(),'Aisle':{'Zone'},'Rack':{'Zone','Aisle'},'Shelf':{'Rack'},'Bin':{'Zone','Aisle','Rack','Shelf'},'Bay':{'Zone'},'Yard Slot':{'Zone'},'Ground Stack':{'Zone'},'Open Area':{'Zone'},'Staging':{'Zone'}}
STRUCTURE_CHILD={'AISLE_RACK_SHELF_BIN':'Aisle','RACK_SHELF_BIN':'Rack','RACK':'Rack','BAY':'Bay','YARD_SLOT':'Yard Slot','GROUND_STACK':'Ground Stack','BIN_ONLY':'Bin','STAGING':'Staging'}
TYPE_PREFIX={'Aisle':'A','Rack':'R','Shelf':'S','Bin':'B','Bay':'BAY','Yard Slot':'SLOT','Ground Stack':'GS','Staging':'STAGE'}

def _location_code(connection,warehouse,parent,location_type,sequence):
    segment=f"{TYPE_PREFIX[location_type]}{sequence:02d}";return f"{parent['code']}-{segment}" if parent else segment

def _validate_structure(parent,child_type):
    structure=str(parent.get('structure_type')or'').upper()
    allowed={'AISLE_RACK_SHELF_BIN':{'Zone':{'Aisle'},'Aisle':{'Rack'},'Rack':{'Shelf'},'Shelf':{'Bin'}},'RACK_SHELF_BIN':{'Zone':{'Rack'},'Rack':{'Shelf'},'Shelf':{'Bin'}},'RACK':{'Zone':{'Rack'}},'BAY':{'Zone':{'Bay'}},'YARD_SLOT':{'Zone':{'Yard Slot'}},'GROUND_STACK':{'Zone':{'Ground Stack'}},'BIN_ONLY':{'Zone':{'Bin'}},'STAGING':{'Zone':{'Staging'}}}
    children=allowed.get(structure,{}).get(parent['type'],set())
    if child_type not in children:
        if structure=='RACK_SHELF_BIN'and parent['type']=='Rack'and child_type=='Bin':raise HTTPException(400,'Bins must be created under a Shelf for this storage structure.')
        raise HTTPException(400,f'{child_type} cannot be created under {parent["type"]} for the {structure or "configured"} storage structure')

@router.post('/locations',status_code=201)
def create_location(body:dict,user:dict=Depends(roles('SupplyChainManager','WarehouseManager'))):
    try:warehouse_id=int(body.get('warehouse_id'))
    except(TypeError,ValueError):raise HTTPException(400,'Select a warehouse site')
    if user['role']!='SupplyChainManager'and warehouse_id not in user['warehouse_ids']:raise HTTPException(403,'Warehouse access denied')
    warehouse=fetch_one('SELECT id,warehouse_code FROM warehouses WHERE id=? AND deleted_at IS NULL',(warehouse_id,))
    if not warehouse:raise HTTPException(400,'Selected warehouse does not exist')
    location_type=str(body.get('type')or'').title();allowed_parents=LOCATION_PARENTS
    if location_type not in allowed_parents:raise HTTPException(400,'Select a valid storage level')
    parent_id=body.get('parent_id')
    if location_type!='Zone':
        try:parent_id=int(parent_id)
        except(TypeError,ValueError):raise HTTPException(400,f'Select a parent location for the {location_type}')
        parent=fetch_one('SELECT * FROM locations WHERE id=? AND deleted_at IS NULL AND COALESCE(active_yn,1)=1',(parent_id,))
        if not parent or parent['warehouse_id']!=warehouse_id or parent['type']not in allowed_parents[location_type]:raise HTTPException(400,f'The selected parent is not valid for this {location_type}')
        _validate_structure(parent,location_type)
    else:
        parent_id=None
        body={**body,'structure_type':body.get('structure_type')or'RACK_SHELF_BIN','storage_classification':body.get('storage_classification')or'GENERAL','environment':body.get('environment')or'INDOOR'}
    body={**body,'warehouse_id':warehouse_id,'type':location_type,'parent_id':parent_id}
    if parent_id:
        for inherited in ('structure_type','storage_classification','environment'):
            if not body.get(inherited):body[inherited]=parent.get(inherited)
    fields=['warehouse_id','parent_id','code','type','label','location_type','storage_type','status','max_quantity','max_weight','max_volume','allowed_category','restricted_category','temperature_requirement','hazardous_material','inspection_required','cycle_count_frequency_days','storage_classification','environment','structure_type','capacity_quantity','capacity_uom','secure_storage','temperature_controlled','mixing_rule','active_yn','full_code'];
    with transaction(immediate=True)as c:
        if not str(body.get('code')or'').strip():
            if location_type=='Zone':
                prefix=f"{warehouse['warehouse_code']}-Z";numbers=[int(str(row['code']).rsplit('-Z',1)[-1])for row in c.execute('SELECT code FROM locations WHERE warehouse_id=? AND parent_id IS NULL',(warehouse_id,)).fetchall()if str(row['code']).rsplit('-Z',1)[-1].isdigit()];body['code']=f'{prefix}{(max(numbers)if numbers else 0)+1:02d}'
            else:
                parent=dict(c.execute('SELECT * FROM locations WHERE id=?',(parent_id,)).fetchone());count=c.execute('SELECT COUNT(*) n FROM locations WHERE parent_id=? AND type=?',(parent_id,location_type)).fetchone()['n'];body['code']=_location_code(c,warehouse,parent,location_type,count+1)
        body['code']=str(body['code']).strip().upper();body['full_code']=body['code'];keys=[k for k in fields if body.get(k)not in[None,'']]
        cur=c.execute(f"INSERT INTO locations({','.join(keys)})VALUES({','.join('?'for _ in keys)})",tuple(body[k]for k in keys));rid=cur.lastrowid;log_audit(c,'locations',rid,'CREATE',user['id'],after=body)
    return fetch_one('SELECT * FROM locations WHERE id=?',(rid,))

@router.put('/locations/{location_id}')
def update_location(location_id:int,body:dict,user:dict=Depends(roles('SupplyChainManager','WarehouseManager'))):
    existing=fetch_one('SELECT * FROM locations WHERE id=? AND deleted_at IS NULL',(location_id,))
    if not existing:raise HTTPException(404,'Storage location not found')
    if user['role']!='SupplyChainManager'and existing['warehouse_id']not in user['warehouse_ids']:raise HTTPException(403,'Warehouse access denied')
    fields=['label','location_type','storage_type','status','max_quantity','max_weight','max_volume','allowed_category','restricted_category','temperature_requirement','hazardous_material','inspection_required','cycle_count_frequency_days','storage_classification','environment','structure_type','capacity_quantity','capacity_uom','secure_storage','temperature_controlled','mixing_rule','active_yn'];keys=[key for key in fields if key in body]
    if ('active_yn'in body and not body['active_yn'])or body.get('status')=='Inactive':
        descendants=fetch_all('''WITH RECURSIVE tree(id)AS(SELECT id FROM locations WHERE id=? UNION ALL SELECT l.id FROM locations l JOIN tree t ON l.parent_id=t.id)SELECT id FROM tree''',(location_id,));ids=[x['id']for x in descendants];marks=','.join('?'for _ in ids);holders=fetch_one(f"SELECT COALESCE((SELECT SUM(quantity)FROM inventory_stock WHERE location_id IN({marks})),0)+COALESCE((SELECT SUM(quantity)FROM inventory_quarantine WHERE released_at IS NULL AND location_id IN({marks})),0) quantity",ids+ids)
        if holders and float(holders.get('quantity')or 0)>0:raise HTTPException(409,f"{existing['type']} {existing['code']} cannot be deactivated because available or restricted inventory exists in it or a child location")
    if not keys:raise HTTPException(400,'No editable location fields were supplied')
    with transaction(immediate=True)as c:
        c.execute(f"UPDATE locations SET {','.join(key+'=?'for key in keys)},modified_by=?,modified_at=datetime('now') WHERE id=?",tuple(body[key]for key in keys)+(user['id'],location_id));log_audit(c,'locations',location_id,'UPDATE',user['id'],existing,body)
    return fetch_one('SELECT * FROM locations WHERE id=?',(location_id,))

@router.delete('/locations/{location_id}/permanent')
def delete_empty_location(location_id:int,user:dict=Depends(roles('SupplyChainManager'))):
    existing=fetch_one('SELECT * FROM locations WHERE id=? AND deleted_at IS NULL',(location_id,))
    if not existing:raise HTTPException(404,'Storage location not found')
    with transaction(immediate=True)as c:
        tree=c.execute('''WITH RECURSIVE branch(id,depth)AS(
          SELECT id,0 FROM locations WHERE id=?
          UNION ALL SELECT l.id,b.depth+1 FROM locations l JOIN branch b ON l.parent_id=b.id
        )SELECT id,depth FROM branch ORDER BY depth DESC''',(location_id,)).fetchall()
        ids=[row['id']for row in tree];marks=','.join('?'for _ in ids);references=[]
        tables=[row['name']for row in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            if table=='locations':continue
            for foreign_key in c.execute(f'PRAGMA foreign_key_list("{table}")').fetchall():
                if foreign_key['table']!='locations':continue
                column=foreign_key['from'];count=c.execute(f'SELECT COUNT(*) n FROM "{table}" WHERE "{column}" IN({marks})',ids).fetchone()['n']
                if count:references.append(f'{table}.{column} ({count})')
        if references:raise HTTPException(409,'This storage branch cannot be deleted because it has inventory or operational history: '+', '.join(references))
        before={'root':dict(existing),'location_ids':ids,'deleted_count':len(ids)}
        for row in tree:c.execute('DELETE FROM locations WHERE id=?',(row['id'],))
        log_audit(c,'locations',location_id,'DELETE',user['id'],before=before,after={'permanent':True,'empty_branch_verified':True})
    return {'success':True,'deleted_count':len(ids),'deleted_location_ids':ids}

@router.post('/locations/{parent_id}/generate',status_code=201)
def generate_locations(parent_id:int,body:dict,user:dict=Depends(roles('SupplyChainManager','WarehouseManager'))):
    parent=fetch_one('SELECT * FROM locations WHERE id=? AND deleted_at IS NULL AND active_yn=1',(parent_id,))
    if not parent:raise HTTPException(404,'Active parent location not found')
    if user['role']!='SupplyChainManager'and parent['warehouse_id']not in user['warehouse_ids']:raise HTTPException(403,'Warehouse access denied')
    inferred='Rack'if parent['type']=='Aisle'else'Shelf'if parent['type']=='Rack'and parent.get('structure_type')in('RACK_SHELF_BIN','AISLE_RACK_SHELF_BIN')else'Bin'if parent['type']=='Shelf'else STRUCTURE_CHILD.get(parent.get('structure_type'))
    child_type=str(body.get('type')or inferred or'').replace('_',' ').title()
    if child_type not in LOCATION_PARENTS or parent['type']not in LOCATION_PARENTS[child_type]:raise HTTPException(400,'This child type is not valid for the selected parent structure')
    _validate_structure(parent,child_type)
    try:target=int(body.get('count'))
    except(TypeError,ValueError):raise HTTPException(400,'Generation count must be a whole number')
    if target<1 or target>500:raise HTTPException(400,'Generation count must be between 1 and 500')
    warehouse=fetch_one('SELECT * FROM warehouses WHERE id=?',(parent['warehouse_id'],));created=[]
    with transaction(immediate=True)as c:
        existing=c.execute('SELECT COUNT(*) n FROM locations WHERE parent_id=? AND type=?',(parent_id,child_type)).fetchone()['n']
        for sequence in range(existing+1,target+1):
            code=_location_code(c,warehouse,parent,child_type,sequence);cur=c.execute('''INSERT INTO locations(warehouse_id,parent_id,code,full_code,type,label,location_type,status,active_yn,environment,storage_classification,structure_type)
              VALUES(?,?,?,?,?,?,?,'Available',1,?,?,?)''',(parent['warehouse_id'],parent_id,code,code,child_type,f'{child_type} {sequence:02d}',child_type,parent.get('environment'),parent.get('storage_classification'),parent.get('structure_type')));created.append(cur.lastrowid);log_audit(c,'locations',cur.lastrowid,'CREATE',user['id'],after={'event':f'{child_type.upper()}_GENERATED','parent_id':parent_id,'code':code})
    return {'created':len(created),'target_count':target,'location_ids':created}

@router.post('/locations/{zone_id}/quick-setup',status_code=201)
def quick_setup(zone_id:int,body:dict,user:dict=Depends(roles('SupplyChainManager','WarehouseManager'))):
    zone=fetch_one("SELECT * FROM locations WHERE id=? AND type='Zone' AND deleted_at IS NULL AND active_yn=1",(zone_id,))
    if not zone:raise HTTPException(404,'Active storage Zone not found')
    if user['role']!='SupplyChainManager'and zone['warehouse_id']not in user['warehouse_ids']:raise HTTPException(403,'Warehouse access denied')
    levels={'AISLE_RACK_SHELF_BIN':[('Aisle','aisles'),('Rack','racks_per_aisle'),('Shelf','shelves_per_rack'),('Bin','bins_per_shelf')],'RACK_SHELF_BIN':[('Rack','racks'),('Shelf','shelves_per_rack'),('Bin','bins_per_shelf')]}.get(zone.get('structure_type'))
    if not levels:raise HTTPException(400,'Quick Setup is available only for the Aisle/Rack/Shelf/Bin structures')
    parents=[zone];created={kind:0 for kind,_ in levels}
    for kind,key in levels:
        try:target=int(body.get(key)or 0)
        except(TypeError,ValueError):raise HTTPException(400,f'{key.replace("_"," ").title()} must be a whole number')
        if target<1 or target>100:raise HTTPException(400,f'{key.replace("_"," ").title()} must be between 1 and 100')
        next_parents=[]
        for parent in parents:
            result=generate_locations(parent['id'],{'count':target},user);created[kind]+=result['created'];next_parents.extend(fetch_all('SELECT * FROM locations WHERE parent_id=? AND type=? AND deleted_at IS NULL ORDER BY code',(parent['id'],kind)))
        parents=next_parents
    return {'created':created,'total_created':sum(created.values()),'message':'Quick Setup completed without deleting or renumbering existing locations'}

@router.get('/storage-rules')
def storage_rules(user:dict=Depends(roles('SupplyChainManager','WarehouseManager'))):
    return fetch_all('SELECT r.*,w.name preferred_warehouse_name FROM item_category_storage_rules r LEFT JOIN warehouses w ON w.id=r.preferred_warehouse_id ORDER BY r.category,r.priority,r.id')

@router.post('/storage-rules',status_code=201)
def create_storage_rule(body:dict,user:dict=Depends(roles('SupplyChainManager'))):
    category=str(body.get('category')or'').strip()
    if not category:raise HTTPException(400,'Item category is required')
    fields=['category','storage_classification','environment','structure_type','secure_required','hazardous_required','temperature_controlled_required','preferred_warehouse_id','priority','active_yn'];data={**body,'category':category,'priority':int(body.get('priority')or 100),'active_yn':int(body.get('active_yn',1))}
    with transaction(immediate=True)as c:keys=[x for x in fields if data.get(x)is not None];cur=c.execute(f"INSERT INTO item_category_storage_rules({','.join(keys)},created_by)VALUES({','.join('?'for _ in keys)},?)",tuple(data[x]for x in keys)+(user['id'],));log_audit(c,'item_category_storage_rules',cur.lastrowid,'CREATE',user['id'],after=data);rid=cur.lastrowid
    return {'id':rid}

def _location_compatible(item,location,inventory_status='AVAILABLE'):
    classification=str(location.get('storage_classification')or'').upper()
    if inventory_status in ('DAMAGED','REJECTED','INSPECTION_PENDING') and classification!='QUARANTINE':return False
    if inventory_status=='REPAIR_PENDING' and classification not in ('REPAIR','QUARANTINE'):return False
    if item.get('secure_storage_required')and not location.get('secure_storage'):return False
    if item.get('hazardous_storage_required')and not location.get('hazardous_material'):return False
    if item.get('temperature_controlled_required')and not location.get('temperature_controlled'):return False
    return True

def _capacity_in_base(item,location,value):
    unit=str(location.get('capacity_uom')or item.get('uom')or'').upper();base=str(item.get('uom')or'').upper()
    if unit==base:return float(value)
    if unit==str(item.get('purchase_uom')or'').upper():return float(value)*float(item.get('conversion_factor')or 1)
    raise ValueError('Location capacity UOM is not convertible to the item Base UOM')

def _putaway_override_compatible(item,location,warehouse_id,quantity,inventory_status):
    if not _location_compatible(item,location,inventory_status):return False
    if location.get('deleted_at')or not location.get('active_yn')or location.get('status')in('Inactive','Blocked','Maintenance','Full')or not is_terminal_storage_location(location):return False
    parent=fetch_one('SELECT active_yn,status FROM locations WHERE id=?',(location.get('parent_id'),))if location.get('parent_id')else None
    if parent and(not parent.get('active_yn')or parent.get('status')=='Inactive'):return False
    occupancy=(fetch_one('SELECT COALESCE(SUM(quantity),0) quantity FROM inventory_stock WHERE location_id=?',(location['id'],))or{}).get('quantity')or 0
    capacity=location.get('capacity_quantity')or location.get('max_quantity')
    try:base_capacity=None if capacity in(None,'')else _capacity_in_base(item,location,capacity)
    except ValueError:return False
    if base_capacity is not None and base_capacity-float(occupancy)+1e-6<float(quantity):return False
    mixing=str(location.get('mixing_rule')or'MIXED_ITEMS_ALLOWED').upper()
    if mixing=='EMPTY_ONLY'and float(occupancy)>1e-8:return False
    if mixing=='SAME_ITEM_ONLY'and fetch_one('SELECT id FROM inventory_stock WHERE location_id=? AND item_id<>? AND quantity>0 LIMIT 1',(location['id'],item['id'])):return False
    allowed=str(location.get('allowed_category')or'').strip();restricted=str(location.get('restricted_category')or'').strip()
    if allowed and str(item.get('category')or'').lower()!=allowed.lower():return False
    if restricted and str(item.get('category')or'').lower()==restricted.lower():return False
    rules=fetch_all('SELECT * FROM item_category_storage_rules WHERE lower(category)=lower(?) AND active_yn=1 AND (preferred_warehouse_id IS NULL OR preferred_warehouse_id=?) ORDER BY priority,id',(item.get('category'),warehouse_id))
    for rule in rules or[{}]:
        classification=item.get('storage_classification_override')or rule.get('storage_classification');environment=item.get('environment_override')or rule.get('environment');structure=item.get('structure_type_override')or rule.get('structure_type')
        if rule.get('secure_required')and not location.get('secure_storage'):continue
        if rule.get('hazardous_required')and not location.get('hazardous_material'):continue
        if rule.get('temperature_controlled_required')and not location.get('temperature_controlled'):continue
        if classification and str(location.get('storage_classification')or'').upper()!=str(classification).upper():continue
        if environment and str(location.get('environment')or'').upper()!=str(environment).upper():continue
        if structure and str(location.get('structure_type')or'').upper()!=str(structure).upper() and str(location.get('type')or'').upper().replace(' ','_')!=str(structure).upper():continue
        return True
    return False

@router.post('/putaway/recommend')
def recommend_putaway(body:dict,user:dict=Depends(roles('SupplyChainManager','WarehouseManager','WarehouseSupervisor','Storekeeper'))):
    warehouse_id=int(body.get('warehouse_id'));quantity=float(body.get('quantity')or 0);item=fetch_one('SELECT * FROM items WHERE id=? AND deleted_at IS NULL',(body.get('item_id'),))
    if not item or quantity<=0:raise HTTPException(400,'Valid item and positive quantity are required')
    if user['role']!='SupplyChainManager'and warehouse_id not in user['warehouse_ids']:raise HTTPException(403,'Warehouse access denied')
    source_table=body.get('source_table');source_id=body.get('source_id')
    if source_table=='inventory_quarantine':
        hold=fetch_one("SELECT * FROM inventory_quarantine WHERE id=? AND warehouse_id=? AND item_id=? AND inventory_status='PUT_AWAY_PENDING' AND released_at IS NULL",(source_id,warehouse_id,item['id']))
        if not hold or abs(float(hold['quantity'])-quantity)>.0001:raise HTTPException(409,'Put-away source is no longer pending or its quantity changed')
    rules=fetch_all('SELECT * FROM item_category_storage_rules WHERE lower(category)=lower(?) AND active_yn=1 AND (preferred_warehouse_id IS NULL OR preferred_warehouse_id=?) ORDER BY priority,id',(item.get('category'),warehouse_id));inventory_status=str(body.get('inventory_status')or'AVAILABLE').upper();locations=fetch_all('''SELECT l.*,COALESCE((SELECT SUM(s.quantity) FROM inventory_stock s WHERE s.location_id=l.id),0) occupancy,COALESCE((SELECT SUM(s.quantity) FROM inventory_stock s WHERE s.location_id=l.id AND s.item_id=?),0) same_item FROM locations l WHERE l.warehouse_id=? AND l.deleted_at IS NULL AND l.active_yn=1 AND l.status NOT IN('Inactive','Blocked','Maintenance','Full') AND NOT EXISTS(SELECT 1 FROM locations p WHERE p.id=l.parent_id AND (p.active_yn=0 OR p.status='Inactive'))''',(item['id'],warehouse_id))
    ranked=[]
    for loc in locations:
        if not is_terminal_storage_location(loc)or not _location_compatible(item,loc,inventory_status):continue
        capacity=loc.get('capacity_quantity')or loc.get('max_quantity')
        try:remaining=None if capacity in(None,'')else _capacity_in_base(item,loc,capacity)-float(loc['occupancy'])
        except ValueError:continue
        if remaining is not None and remaining+1e-6<quantity:continue
        mixing=str(loc.get('mixing_rule')or'MIXED_ITEMS_ALLOWED').upper()
        if mixing=='EMPTY_ONLY'and float(loc['occupancy'])>1e-8:continue
        if mixing=='SAME_ITEM_ONLY'and float(loc['occupancy'])-float(loc['same_item'])>1e-8:continue
        for rule in rules or[{}]:
            classification=item.get('storage_classification_override')or rule.get('storage_classification');environment=item.get('environment_override')or rule.get('environment');structure=item.get('structure_type_override')or rule.get('structure_type')
            if rule.get('secure_required')and not loc.get('secure_storage'):continue
            if rule.get('hazardous_required')and not loc.get('hazardous_material'):continue
            if rule.get('temperature_controlled_required')and not loc.get('temperature_controlled'):continue
            if classification and str(loc.get('storage_classification')or'').upper()!=str(classification).upper():continue
            if environment and str(loc.get('environment')or'').upper()!=str(environment).upper():continue
            if structure and str(loc.get('structure_type')or'').upper()!=str(structure).upper() and str(loc.get('type')or'').upper().replace(' ','_')!=str(structure).upper():continue
            ranked.append((int(rule.get('priority')or 100),0 if float(loc['same_item'])>0 else 1,-(remaining or 0),loc['code'],loc));break
    if not ranked:raise HTTPException(409,'No active location has sufficient capacity and meets the mandatory storage requirements for this item')
    selected=sorted(ranked,key=lambda x:x[:4])[0][4]
    with transaction(immediate=True)as c:cur=c.execute('INSERT INTO putaway_recommendations(item_id,warehouse_id,quantity,inventory_status,recommended_location_id,reason,source_table,source_id,recommended_by)VALUES(?,?,?,?,?,?,?,?,?)',(item['id'],warehouse_id,quantity,inventory_status,selected['id'],'Highest-priority compatible active location with capacity',source_table,source_id,user['id']));log_audit(c,'putaway_recommendations',cur.lastrowid,'CREATE',user['id'],after={'event':'PUTAWAY_RECOMMENDED','location_id':selected['id'],'source_table':source_table,'source_id':source_id});recommendation_id=cur.lastrowid
    compatible=[entry[4] for entry in sorted(ranked,key=lambda x:x[:4])]
    return {'recommendation_id':recommendation_id,'location':selected,'compatible_locations':compatible,'reason':'Highest-priority compatible active terminal location with capacity'}

@router.put('/putaway/{recommendation_id}/confirm')
def confirm_putaway(recommendation_id:int,body:dict,user:dict=Depends(roles('SupplyChainManager','WarehouseManager','WarehouseSupervisor','Storekeeper'))):
    recommendation=fetch_one("SELECT * FROM putaway_recommendations WHERE id=? AND status='RECOMMENDED'",(recommendation_id,))
    if not recommendation:raise HTTPException(404,'Open put-away recommendation not found')
    if user['role']!='SupplyChainManager'and recommendation['warehouse_id']not in user['warehouse_ids']:raise HTTPException(403,'Warehouse access denied')
    selected_id=int(body.get('selected_location_id')or recommendation['recommended_location_id']);selected=fetch_one('SELECT * FROM locations WHERE id=? AND warehouse_id=?',(selected_id,recommendation['warehouse_id']))
    item=fetch_one('SELECT * FROM items WHERE id=?',(recommendation['item_id'],))
    if not selected or not _putaway_override_compatible(item,selected,recommendation['warehouse_id'],recommendation['quantity'],recommendation['inventory_status']):raise HTTPException(409,'Selected location does not meet the mandatory storage, status, structure, or capacity requirements for this item')
    override=selected_id!=recommendation['recommended_location_id'];reason=str(body.get('override_reason')or'').strip()
    if override and len(reason)<5:raise HTTPException(400,'An override reason is required when selecting another compatible location')
    if recommendation.get('source_table')=='inventory_quarantine':
        hold=fetch_one("SELECT * FROM inventory_quarantine WHERE id=? AND inventory_status='PUT_AWAY_PENDING' AND released_at IS NULL",(recommendation.get('source_id'),))
        if not hold or int(hold['item_id'])!=int(item['id'])or abs(float(hold['quantity'])-float(recommendation['quantity']))>.0001:raise HTTPException(409,'Put-away source is no longer pending or its quantity changed')
        with transaction(immediate=True)as c:
            current=c.execute('SELECT released_at FROM inventory_quarantine WHERE id=?',(hold['id'],)).fetchone()
            if current['released_at']:raise HTTPException(409,'This stock has already completed put-away. Refresh the queue')
            linked_tool=c.execute('SELECT * FROM tools WHERE id=?',(hold.get('tool_id'),)).fetchone()
            if linked_tool:
                if float(hold['quantity'])!=1 or linked_tool['warehouse_id']!=recommendation['warehouse_id'] or linked_tool['employee_id']:raise HTTPException(409,'Tool does not match this put-away receipt')
                c.execute("UPDATE tools SET location_id=?,condition='Good',status='Available' WHERE id=?",(selected_id,linked_tool['id']))
                log_audit(c,'tools',linked_tool['id'],'UPDATE',user['id'],dict(linked_tool),{'event':'TRANSFER_PUTAWAY','location_id':selected_id,'hold_id':hold['id']})
            if hold.get('source_grn_item_id'):
                pending_tools=c.execute("SELECT id FROM tools WHERE source_grn_item_id=? AND location_id IS NULL AND condition='Good' ORDER BY source_unit_number",(hold['source_grn_item_id'],)).fetchall()
                if pending_tools:
                    quantity=float(hold['quantity'])
                    if not quantity.is_integer() or quantity>len(pending_tools):raise HTTPException(409,'Controlled tool put-away requires matching whole pending units')
                    for pending_tool in pending_tools[:int(quantity)]:
                        c.execute('UPDATE tools SET location_id=? WHERE id=?',(selected_id,pending_tool['id']))
                        log_audit(c,'tools',pending_tool['id'],'UPDATE',user['id'],after={'event':'GRN_PUTAWAY','location_id':selected_id,'hold_id':hold['id']})
            receive(c,item_id=item['id'],warehouse_id=recommendation['warehouse_id'],location_id=selected_id,quantity=float(hold['quantity']),unit_cost=float(hold['unit_cost']),batch=hold.get('batch'),expiry_date=hold.get('expiry_date'),source_grn_item_id=linked_tool['source_grn_item_id'] if linked_tool else hold.get('source_grn_item_id'),transaction_type='PUTAWAY_IN',reference_number=f'PUT-{recommendation_id}',reference_table='putaway_recommendations',reference_id=recommendation_id,created_by=user['id'])
            c.execute("UPDATE inventory_quarantine SET released_at=datetime('now'),released_by=? WHERE id=?",(user['id'],hold['id']));c.execute("UPDATE putaway_recommendations SET selected_location_id=?,status='CONFIRMED',override_reason=?,confirmed_by=?,confirmed_at=datetime('now') WHERE id=?",(selected_id,reason or None,user['id'],recommendation_id));log_audit(c,'putaway_recommendations',recommendation_id,'UPDATE',user['id'],recommendation,{'event':'PUTAWAY_OVERRIDDEN'if override else'PUTAWAY_CONFIRMED','selected_location_id':selected_id,'quantity':hold['quantity'],'value':float(hold['quantity'])*float(hold['unit_cost']),'override_reason':reason})
            if hold.get('source_grn_item_id'):
                from ..receiving import refresh_receipt_status
                linked=c.execute('SELECT g.po_id FROM grn_items gi JOIN grns g ON g.id=gi.grn_id WHERE gi.id=?',(hold['source_grn_item_id'],)).fetchone()
                if linked:refresh_receipt_status(c,linked['po_id'])
        return {'success':True,'status':'CONFIRMED','inventory_status':'AVAILABLE','selected_location_id':selected_id,'override':override}
    source_id=body.get('source_location_id')
    if source_id and int(source_id)!=selected_id:
        source=fetch_one('SELECT * FROM locations WHERE id=? AND warehouse_id=?',(source_id,recommendation['warehouse_id']))
        if not source:raise HTTPException(400,'Source location is not in the receiving warehouse')
        with transaction(immediate=True)as c:
            _cost,layers=consume(c,item_id=item['id'],warehouse_id=recommendation['warehouse_id'],location_id=int(source_id),quantity=recommendation['quantity'],transaction_type='PUTAWAY_OUT',reference_number=f'PUT-{recommendation_id}',reference_table='putaway_recommendations',reference_id=recommendation_id,created_by=user['id']);
            for _layer_id,layer_quantity,unit_cost in layers:receive(c,item_id=item['id'],warehouse_id=recommendation['warehouse_id'],location_id=selected_id,quantity=layer_quantity,unit_cost=unit_cost,transaction_type='PUTAWAY_IN',reference_number=f'PUT-{recommendation_id}',reference_table='putaway_recommendations',reference_id=recommendation_id,created_by=user['id'])
            c.execute("UPDATE putaway_recommendations SET selected_location_id=?,status='CONFIRMED',override_reason=?,confirmed_by=?,confirmed_at=datetime('now') WHERE id=?",(selected_id,reason or None,user['id'],recommendation_id));log_audit(c,'putaway_recommendations',recommendation_id,'UPDATE',user['id'],recommendation,{'event':'PUTAWAY_OVERRIDDEN'if override else'PUTAWAY_CONFIRMED','selected_location_id':selected_id,'override_reason':reason})
    else:
        with transaction(immediate=True)as c:c.execute("UPDATE putaway_recommendations SET selected_location_id=?,status='CONFIRMED',override_reason=?,confirmed_by=?,confirmed_at=datetime('now') WHERE id=?",(selected_id,reason or None,user['id'],recommendation_id));log_audit(c,'putaway_recommendations',recommendation_id,'UPDATE',user['id'],recommendation,{'event':'PUTAWAY_OVERRIDDEN'if override else'PUTAWAY_CONFIRMED','selected_location_id':selected_id,'override_reason':reason})
    return {'success':True,'status':'CONFIRMED','selected_location_id':selected_id,'override':override}

@router.post('/employees',status_code=201)
def create_employee(body:dict,user:dict=Depends(roles(*MGMT))):
    role=str(body.get('approval_role')or'Storekeeper');first=str(body.get('first_name')or'').strip();last=str(body.get('last_name')or'').strip();name=str(body.get('name')or f'{first} {last}').strip()
    if not name:raise HTTPException(400,'Employee name is required')
    email=str(body.get('email')or'').strip();payroll=str(body.get('payroll_number')or'').strip()
    birth=str(body.get('date_of_birth')or'').strip()
    duplicate=fetch_one('''SELECT id,employee_code,name,email,payroll_number FROM employees WHERE deleted_at IS NULL AND
      ((?<>'' AND lower(trim(email))=lower(trim(?))) OR (?<>'' AND lower(trim(payroll_number))=lower(trim(?))) OR
       (?<>'' AND lower(trim(name))=lower(trim(?)) AND date_of_birth=?)) ORDER BY id LIMIT 1''',(email,email,payroll,payroll,birth,name,birth))
    if duplicate:raise HTTPException(409,f"Employee already exists as {duplicate['employee_code']} ({duplicate['name']}). Open the existing record instead of creating another login.")
    requested_permissions=body.get('permission_keys')
    if isinstance(requested_permissions,str):
        try:requested_permissions=json.loads(requested_permissions)
        except (ValueError,TypeError):requested_permissions=None
    if not isinstance(requested_permissions,list):requested_permissions=defaults_for_role(role)
    seq=(fetch_one("SELECT MAX(CAST(SUBSTR(employee_code,5)AS INTEGER))sequence FROM employees WHERE employee_code GLOB 'EMP-[0-9]*'")or{}).get('sequence')or 0;code=f'EMP-{seq+1:04d}';fields=['employee_code','name','first_name','middle_name','last_name','date_of_birth','payroll_number','email','country_code','city_id','address_line','postal_code','warehouse_id','department_id','position','reports_to','reports_to_employee_id','supervisor','approval_limit','approval_role','permission_keys','system_access_yn','status'];data={**body,'employee_code':code,'name':name,'approval_role':role,'permission_keys':json.dumps(requested_permissions),'system_access_yn':0 if role=='Helper'else int(body.get('system_access_yn',1))};keys=[k for k in fields if data.get(k)not in[None,'']]
    username=(f'{first}.{last}'if first and last else name.replace(' ','.')).lower();base=username;suffix=1
    while fetch_one('SELECT id FROM users WHERE username=?',(username,)):suffix+=1;username=f'{base}{suffix}'
    with transaction(immediate=True)as c:
        cur=c.execute(f"INSERT INTO employees({','.join(keys)})VALUES({','.join('?'for _ in keys)})",tuple(data[k]for k in keys));eid=cur.lastrowid
        if data['system_access_yn']:c.execute("INSERT INTO users(employee_id,username,password_hash,full_name,role,warehouse_id,must_change_password,password_changed_at,password_expires_at)VALUES(?,?,?,?,?,?,1,datetime('now'),datetime('now','+7 days'))",(eid,username,bcrypt.hashpw(b'password123',bcrypt.gensalt()).decode(),name,role,data.get('warehouse_id')))
    credentials={'employee_code':code,'username':username,'password':'password123'}if data['system_access_yn']else None
    return {'id':eid,'employee_code':code,'username':username if data['system_access_yn']else None,'temporary_password':'password123'if data['system_access_yn']else None,'credentials':credentials}

@router.put('/employees/{employee_id}')
def update_employee(employee_id:int,body:dict,user:dict=Depends(roles(*MGMT))):
    before=fetch_one('SELECT * FROM employees WHERE id=? AND deleted_at IS NULL',(employee_id,))
    if not before:raise HTTPException(404,'Employee not found')
    role=str(body.get('approval_role')or before.get('approval_role')or'Storekeeper')
    first=str(body.get('first_name')or'').strip();middle=str(body.get('middle_name')or'').strip();last=str(body.get('last_name')or'').strip()
    name=' '.join(part for part in (first,middle,last) if part).strip()or str(body.get('name')or before.get('name')or'').strip()
    if not name:raise HTTPException(400,'Employee name is required')
    try:department_id=int(body.get('department_id'))
    except (TypeError,ValueError):raise HTTPException(400,'Select Warehouse or Procurement department')
    department=fetch_one('SELECT name FROM departments WHERE id=? AND deleted_at IS NULL',(department_id,))
    if not department or not any(word in department['name'].strip().lower()for word in('warehouse','procurement','purchas')):raise HTTPException(400,'Supply Chain employees must use Warehouse or Procurement department')
    warehouse_department='warehouse'in department['name'].strip().lower()
    warehouse_roles={'WarehouseManager','WarehouseSupervisor','Storekeeper','Helper','SupplyChainManager'};procurement_roles={'PurchaseManager','PurchaseOfficer','SupplyChainManager'}
    if role not in(warehouse_roles if warehouse_department else procurement_roles):raise HTTPException(400,f'{role} is not valid for {department["name"]}')
    email=str(body.get('email')or'').strip();payroll=str(body.get('payroll_number')or'').strip();birth=str(body.get('date_of_birth')or'').strip()
    duplicate=fetch_one('''SELECT employee_code,name FROM employees WHERE id<>? AND deleted_at IS NULL AND
      ((?<>'' AND lower(trim(email))=lower(trim(?))) OR (?<>'' AND lower(trim(payroll_number))=lower(trim(?))) OR
       (?<>'' AND lower(trim(name))=lower(trim(?)) AND date_of_birth=?)) LIMIT 1''',(employee_id,email,email,payroll,payroll,birth,name,birth))
    if duplicate:raise HTTPException(409,f"Employee data already belongs to {duplicate['employee_code']} ({duplicate['name']})")
    permissions=body.get('permission_keys',before.get('permission_keys')or'[]')
    if isinstance(permissions,list):permissions=json.dumps(permissions)
    else:
        try:permissions=json.dumps(json.loads(str(permissions or'[]')))
        except (ValueError,TypeError):permissions='[]'
    status=str(body.get('status')or'Active');system_access=0 if role=='Helper'else int(body.get('system_access_yn',before.get('system_access_yn',1))or 0)
    values=(name,first or None,middle or None,last or None,birth or None,payroll or None,email or None,department_id,body.get('position'),body.get('reports_to_employee_id'),float(body.get('approval_limit')or 0),role,'[]'if role=='Helper'else permissions,system_access,status,body.get('warehouse_id'),employee_id)
    with transaction(immediate=True)as c:
        c.execute('''UPDATE employees SET name=?,first_name=?,middle_name=?,last_name=?,date_of_birth=?,payroll_number=?,email=?,department_id=?,position=?,reports_to_employee_id=?,approval_limit=?,approval_role=?,permission_keys=?,system_access_yn=?,status=?,warehouse_id=? WHERE id=?''',values)
        c.execute('''UPDATE users SET full_name=?,role=?,warehouse_id=?,is_active=? WHERE employee_id=? AND deleted_at IS NULL''',(name,role,body.get('warehouse_id'),int(system_access and status=='Active'),employee_id))
        log_audit(c,'employees',employee_id,'UPDATE',user['id'],before,{'name':name,'department_id':department_id,'approval_role':role,'status':status,'system_access_yn':system_access})
    return fetch_one('''SELECT e.*,d.name department_name,(SELECT u.username FROM users u WHERE u.employee_id=e.id AND u.deleted_at IS NULL ORDER BY u.id DESC LIMIT 1)login_id FROM employees e LEFT JOIN departments d ON d.id=e.department_id WHERE e.id=?''',(employee_id,))

@router.delete('/employees/{employee_id}')
def delete_employee(employee_id:int,user:dict=Depends(roles('SupplyChainManager'))):
    with transaction(immediate=True)as c:c.execute("UPDATE employees SET status='Inactive',deleted_at=datetime('now'),system_access_yn=0 WHERE id=?",(employee_id,));c.execute("UPDATE users SET is_active=0,deleted_at=datetime('now')WHERE employee_id=?",(employee_id,))
    return {'success':True,'softDeleted':True}

@router.get('/employee-signatures/{filename}')
def signature(filename:str,_u:User):
    target=SIGNATURES/Path(filename).name
    if target.name!=filename or not target.exists():raise HTTPException(404,'Signature not found')
    return FileResponse(target,media_type='image/png')

@router.get('/employee-signature-by-name')
def signature_by_name(name:str,_u:User):
    row=fetch_one('SELECT signature_url FROM employees WHERE lower(name)=lower(?) AND status=\'Active\' AND deleted_at IS NULL',(name.strip(),))
    if not row or not row.get('signature_url'):raise HTTPException(404,'Employee signature not found')
    filename=Path(row['signature_url']).name;target=SIGNATURES/filename
    if not target.exists():raise HTTPException(404,'Employee signature file not found')
    return FileResponse(target,media_type='image/png')

@router.post('/employees/{employee_id}/signature')
async def upload_signature(employee_id:int,user:dict=Depends(roles(*MGMT)),signature:UploadFile=File(...)):
    data=await signature.read(2*1024*1024+1)
    # PNG color types 4 and 6 contain an alpha channel; reject opaque images server-side.
    if len(data)>2*1024*1024 or len(data)<26 or signature.content_type!='image/png'or data[:8]!=b'\x89PNG\r\n\x1a\n'or data[25]not in(4,6):raise HTTPException(400,'Processed signature must be a transparent PNG')
    employee=fetch_one('SELECT id,signature_url FROM employees WHERE id=? AND deleted_at IS NULL',(employee_id,))
    if not employee:raise HTTPException(404,'Employee not found')
    name=secrets.token_hex(16);(SIGNATURES/name).write_bytes(data);url=f'/masters/employee-signatures/{name}'
    with transaction(immediate=True)as c:c.execute('UPDATE employees SET signature_url=? WHERE id=?',(url,employee_id));log_audit(c,'employees',employee_id,'UPDATE',user['id'],{'signature_url':employee.get('signature_url')},{'signature_url':url})
    previous=str(employee.get('signature_url')or'')
    if previous.startswith('/masters/employee-signatures/'):(SIGNATURES/Path(previous).name).unlink(missing_ok=True)
    return {'signature_url':url}

def assign_employee(employee_id,ids,all_scope,primary,user_id):
    ids=list(dict.fromkeys(int(wid)for wid in ids if str(wid).strip()))
    primary=int(primary)if primary not in(None,'')else None
    if primary and primary not in ids:ids.append(primary)
    if ids:
        valid={row['id']for row in fetch_all(f"SELECT id FROM warehouses WHERE deleted_at IS NULL AND id IN({','.join('?'for _ in ids)})",ids)}
        if valid!=set(ids):raise HTTPException(400,'One or more assigned warehouses are inactive or do not exist')
    with transaction(immediate=True)as c:
        c.execute("UPDATE employee_warehouse_assignments SET active_yn=0,effective_to=date('now')WHERE employee_id=?AND active_yn=1",(employee_id,))
        if all_scope:
            existing=c.execute('SELECT id FROM employee_warehouse_assignments WHERE employee_id=? AND all_warehouses_yn=1 ORDER BY id DESC LIMIT 1',(employee_id,)).fetchone()
            if existing:c.execute("UPDATE employee_warehouse_assignments SET warehouse_id=NULL,all_warehouses_yn=1,primary_warehouse_yn=0,effective_from=date('now'),effective_to=NULL,active_yn=1,created_by=? WHERE id=?",(user_id,existing['id']))
            else:c.execute('INSERT INTO employee_warehouse_assignments(employee_id,all_warehouses_yn,created_by)VALUES(?,1,?)',(employee_id,user_id))
        else:
            for wid in ids:c.execute("""INSERT INTO employee_warehouse_assignments(employee_id,warehouse_id,primary_warehouse_yn,created_by)
                VALUES(?,?,?,?) ON CONFLICT(employee_id,warehouse_id) DO UPDATE SET all_warehouses_yn=0,
                primary_warehouse_yn=excluded.primary_warehouse_yn,effective_from=date('now'),effective_to=NULL,
                active_yn=1,created_by=excluded.created_by""",(employee_id,wid,int(wid==(primary or ids[0])),user_id))
        c.execute('UPDATE employees SET warehouse_id=? WHERE id=?',(None if all_scope else(primary or(ids[0]if ids else None)),employee_id))
    return {'warehouse_ids':ids,'all_warehouses_yn':all_scope,'primary_warehouse_id':None if all_scope else(primary or(ids[0]if ids else None))}

@router.put('/employees/{employee_id}/warehouse-assignments')
def employee_assign(employee_id:int,b:dict,u:dict=Depends(roles('SupplyChainManager'))):return assign_employee(employee_id,b.get('warehouse_ids')or[],bool(b.get('all_warehouses_yn')),b.get('primary_warehouse_id'),u['id'])

@router.get('/warehouse-assignments')
def assignments(_u:dict=Depends(roles('SupplyChainManager'))):return fetch_all('SELECT uwa.*,u.username,u.full_name,w.warehouse_code,w.name warehouse_name FROM user_warehouse_assignments uwa JOIN users u ON u.id=uwa.user_id JOIN warehouses w ON w.id=uwa.warehouse_id ORDER BY u.full_name,w.warehouse_code')

@router.put('/users/{user_id}/warehouse-assignments')
def user_assign(user_id:int,b:dict,u:dict=Depends(roles('SupplyChainManager'))):
    ids=list(dict.fromkeys(b.get('warehouse_ids')or[]))
    with transaction(immediate=True)as c:
        c.execute("UPDATE user_warehouse_assignments SET is_active=0,effective_to=date('now')WHERE user_id=?AND is_active=1",(user_id,))
        for wid in ids:c.execute('INSERT INTO user_warehouse_assignments(user_id,warehouse_id,is_active,assigned_by)VALUES(?,?,1,?)ON CONFLICT(user_id,warehouse_id)DO UPDATE SET is_active=1,effective_to=NULL,assigned_by=excluded.assigned_by',(user_id,wid,u['id']))
        c.execute('UPDATE users SET warehouse_id=? WHERE id=?',((b.get('primary_warehouse_id')or(ids[0]if ids else None)),user_id))
    return {'warehouse_ids':ids}

@router.put('/role-permission-defaults/{role}')
def save_defaults(role:str,b:dict,u:dict=Depends(roles('SupplyChainManager'))):
    keys=b.get('permission_keys')or[]
    with transaction(immediate=True)as c:c.execute('INSERT INTO settings(key,value)VALUES(?,?)ON CONFLICT(key)DO UPDATE SET value=excluded.value',(f'role_permission_defaults_{role}',json.dumps(keys)))
    return {'role':role,'permission_keys':keys}

@router.get('/item-taxonomy')
def item_taxonomy(_u:User):
    categories=fetch_all('SELECT id,name FROM item_categories WHERE active_yn=1 ORDER BY name')
    subcategories=fetch_all('SELECT s.id,s.category_id,s.name,c.name category FROM item_subcategories s JOIN item_categories c ON c.id=s.category_id WHERE s.active_yn=1 AND c.active_yn=1 ORDER BY c.name,s.name')
    return {'categories':categories,'subcategories':subcategories}

@router.post('/item-taxonomy/categories',status_code=201)
def create_item_category(body:dict,user:dict=Depends(roles('SupplyChainManager','WarehouseManager','WarehouseSupervisor','Storekeeper'))):
    name=' '.join(str(body.get('name')or'').strip().split())
    if len(name)<2:raise HTTPException(400,'Category name is required')
    with transaction(immediate=True)as c:
        existing=c.execute('SELECT id,name FROM item_categories WHERE name=? COLLATE NOCASE',(name,)).fetchone()
        if existing:c.execute('UPDATE item_categories SET active_yn=1 WHERE id=?',(existing['id'],));category_id=existing['id']
        else:category_id=c.execute('INSERT INTO item_categories(name,created_by)VALUES(?,?)',(name,user['id'])).lastrowid
        log_audit(c,'item_categories',category_id,'CREATE',user['id'],after={'name':name})
    return fetch_one('SELECT id,name FROM item_categories WHERE id=?',(category_id,))

@router.post('/item-taxonomy/subcategories',status_code=201)
def create_item_subcategory(body:dict,user:dict=Depends(roles('SupplyChainManager','WarehouseManager','WarehouseSupervisor','Storekeeper'))):
    name=' '.join(str(body.get('name')or'').strip().split())
    try:category_id=int(body.get('category_id'))
    except(TypeError,ValueError):raise HTTPException(400,'Select a category first')
    if len(name)<2 or not fetch_one('SELECT id FROM item_categories WHERE id=? AND active_yn=1',(category_id,)):raise HTTPException(400,'Valid category and subcategory names are required')
    with transaction(immediate=True)as c:
        existing=c.execute('SELECT id FROM item_subcategories WHERE category_id=? AND name=? COLLATE NOCASE',(category_id,name)).fetchone()
        if existing:c.execute('UPDATE item_subcategories SET active_yn=1 WHERE id=?',(existing['id'],));subcategory_id=existing['id']
        else:subcategory_id=c.execute('INSERT INTO item_subcategories(category_id,name,created_by)VALUES(?,?,?)',(category_id,name,user['id'])).lastrowid
        log_audit(c,'item_subcategories',subcategory_id,'CREATE',user['id'],after={'category_id':category_id,'name':name})
    return fetch_one('SELECT id,category_id,name FROM item_subcategories WHERE id=?',(subcategory_id,))

@router.post('/items/similarity')
def similarity(b:dict,_u:User):
    def normalized(value):return ' '.join(str(value or'').strip().lower().split())
    term=normalized(b.get('description'))
    if len(term)<4:return []
    try:exclude_id=int(b.get('exclude_id'))if b.get('exclude_id')not in(None,'')else None
    except (TypeError,ValueError):exclude_id=None
    requested={key:normalized(b.get(key))for key in('category','subcategory','uom')}
    rows=fetch_all('SELECT id,item_code,description,category,subcategory,uom FROM items WHERE deleted_at IS NULL AND active_yn=1 AND(? IS NULL OR id<>?)',(exclude_id,exclude_id))
    matches=[]
    for row in rows:
        description=normalized(row.get('description'));description_score=SequenceMatcher(None,term,description).ratio()
        exact_description=description==term;conflict=False;bonuses=[]
        for key in ('category','subcategory','uom'):
            existing=normalized(row.get(key));incoming=requested[key]
            if incoming and existing:
                same=incoming==existing;bonuses.append(1.0 if same else 0.0);conflict=conflict or not same
        score=description_score if not bonuses else description_score*.85+(sum(bonuses)/len(bonuses))*.15
        if score<.45 and term not in description and description not in term:continue
        matches.append({**row,'score':round(score*100),'match_type':'Exact Duplicate'if exact_description and not conflict else('High Similarity'if score>=.8 else'Possible Duplicate')})
    return sorted(matches,key=lambda row:(-row['score'],row['item_code']))[:10]

@router.put('/items/{item_id}/duplicate-review')
def duplicate_review(item_id:int,b:dict,u:dict=Depends(roles('SupplyChainManager'))):
    with transaction(immediate=True)as c:c.execute("UPDATE item_duplicate_reviews SET review_status=?,review_reason=?,replacement_item_id=?,reviewed_at=datetime('now'),reviewed_by=? WHERE primary_item_id=?OR possible_duplicate_item_id=?",(b.get('status'),b.get('reason'),b.get('replacement_item_id'),u['id'],item_id,item_id));c.execute('UPDATE items SET duplicate_status=?,replacement_item_id=?,active_yn=CASE WHEN ? IN(\'Merged\',\'Disabled\')THEN 0 ELSE active_yn END WHERE id=?',(b.get('status'),b.get('replacement_item_id'),b.get('status'),item_id))
    return {'success':True,'status':b.get('status'),'replacement_item_id':b.get('replacement_item_id')}
