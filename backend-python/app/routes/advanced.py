from fastapi import APIRouter, Depends, HTTPException

from ..audit import log_audit
from ..crud import crud_router
from ..database import fetch_all, fetch_one, transaction
from ..security import User, roles

router=APIRouter(prefix='/api/advanced',tags=['advanced'])
TOOL_ROLES=['SupplyChainManager','WarehouseManager','WarehouseSupervisor','Storekeeper']

def tool_user(user:dict=Depends(roles(*TOOL_ROLES))):
    if 'task.tools' not in user.get('permission_keys',[]):raise HTTPException(403,'Tool Management permission is required')
    return user

@router.get('/tools')
def tools(user:dict=Depends(tool_user)):
    ids=user['warehouse_ids'];return fetch_all(f"SELECT t.*,i.item_code,i.description item_description,w.name warehouse_name FROM tools t JOIN items i ON i.id=t.item_id JOIN warehouses w ON w.id=t.warehouse_id WHERE t.warehouse_id IN({','.join('?'for _ in ids)or'NULL'})ORDER BY t.tool_code",ids)

@router.get('/tools/alerts/calibration')
def calibration(user:dict=Depends(tool_user)):
    ids=user['warehouse_ids']
    if not ids:return []
    return fetch_all(f"SELECT *,CAST(julianday(calibration_due_date)-julianday('now') AS INTEGER) days_remaining FROM tools WHERE calibration_due_date IS NOT NULL AND warehouse_id IN({','.join('?' for _ in ids)}) ORDER BY calibration_due_date",ids)

@router.get('/tools/{tool_id}')
def tool(tool_id:int,user:dict=Depends(tool_user)):
    row=fetch_one(f"SELECT t.*,i.item_code,i.description item_description,w.name warehouse_name FROM tools t JOIN items i ON i.id=t.item_id JOIN warehouses w ON w.id=t.warehouse_id WHERE t.id=?AND t.warehouse_id IN({','.join('?'for _ in user['warehouse_ids'])or'NULL'})",(tool_id,*user['warehouse_ids']))
    if not row:raise HTTPException(404,'Tool not found')
    return row

def scoped_tool(c, tool_id, user):
    if 'task.tools' not in user.get('permission_keys', []):
        raise HTTPException(403, 'Tool Management permission is required')
    row=c.execute('SELECT * FROM tools WHERE id=?',(tool_id,)).fetchone()
    if not row:raise HTTPException(404,'Tool not found')
    row=dict(row)
    if row['warehouse_id'] not in user['warehouse_ids']:raise HTTPException(403,'Tool is outside your authorized warehouses')
    return row


def registration_values(c, body, tool_id=None):
    from datetime import date
    serial=str(body.get('serial_number') or '').strip()
    if not serial:raise HTTPException(400,'Manufacturer Serial Number is required')
    if c.execute('SELECT 1 FROM tools WHERE lower(trim(serial_number))=lower(?) AND id<>?',(serial,tool_id or -1)).fetchone():
        raise HTTPException(409,'A tool with this manufacturer serial number already exists')
    due=body.get('calibration_due_date') or None
    required=bool(body.get('calibration_required_yn')) or bool(due)
    if due:
        try:date.fromisoformat(due)
        except (ValueError,TypeError):raise HTTPException(400,'Enter a valid calibration date')
    if required and not due:raise HTTPException(400,'Calibration due date is required for calibrated tools')
    return serial,body.get('make'),body.get('model'),due,int(required)


@router.post('/tools',status_code=201)
def register_tool(body:dict,user:dict=Depends(tool_user)):
    # Preserve manual registration for legacy/opening tools. GRN units use completion below.
    from uuid import uuid4
    wid=body.get('warehouse_id')
    if 'task.tools' not in user.get('permission_keys',[]):raise HTTPException(403,'Tool Management permission is required')
    if wid not in user['warehouse_ids']:raise HTTPException(403,'Select an authorized warehouse')
    with transaction(immediate=True) as c:
        item=c.execute("SELECT * FROM items WHERE id=? AND deleted_at IS NULL AND consumable_returnable='Returnable' AND active_yn=1",(body.get('item_id'),)).fetchone()
        if not item:raise HTTPException(400,'Linked item must be an active returnable item')
        if c.execute("SELECT 1 FROM tools WHERE item_id=? AND warehouse_id=? AND source_grn_item_id IS NOT NULL",(item['id'],wid)).fetchone():
            raise HTTPException(409,'Complete the pending GRN tool registrations for this item instead of creating another tool')
        values=registration_values(c,body)
        code='TOOL-'+uuid4().hex.upper()
        cur=c.execute("""INSERT INTO tools(tool_code,item_id,warehouse_id,serial_number,make,model,calibration_due_date,calibration_required_yn,condition,status,registered_at,registered_by)
            VALUES(?,?,?,?,?,?,?,?,'Good','Available',datetime('now'),?)""",(code,item['id'],wid,*values,user['id']))
        tool_id=cur.lastrowid
        log_audit(c,'tools',tool_id,'CREATE',user['id'],after={**body,'tool_code':code,'event':'MANUAL_REGISTRATION'})
    return tool(tool_id,user)


@router.put('/tools/{tool_id}/register')
def complete_registration(tool_id:int,body:dict,user:dict=Depends(tool_user)):
    with transaction(immediate=True) as c:
        before=scoped_tool(c,tool_id,user)
        if before['status']!='Pending Tool Registration':raise HTTPException(409,'This tool is no longer pending registration')
        if before['condition']!='Good':raise HTTPException(409,'This GRN unit failed inspection and requires receipt disposition before registration')
        values=registration_values(c,body,tool_id)
        c.execute("""UPDATE tools SET serial_number=?,make=?,model=?,calibration_due_date=?,calibration_required_yn=?,
            registered_at=datetime('now'),registered_by=?,status='Available' WHERE id=?""",(*values,user['id'],tool_id))
        log_audit(c,'tools',tool_id,'UPDATE',user['id'],before,{**body,'event':'REGISTRATION_COMPLETED','status':'Available'})
    return tool(tool_id,user)


def issue_eligible(c,row,warehouse_id):
    from datetime import date
    if warehouse_id!=row['warehouse_id']:raise HTTPException(403,'Select the warehouse that owns this tool')
    if row['transfer_pending_yn']:raise HTTPException(409,'Tool is in transit; the destination warehouse must confirm receipt')
    if row['status']!='Available' or not row['registered_at'] or row['condition']!='Good' or row['employee_id']:
        raise HTTPException(409,'Only a registered, Available tool in Good condition can be issued')
    if row['calibration_required_yn']:
        try:due=date.fromisoformat(row['calibration_due_date'] or '')
        except (ValueError,TypeError):raise HTTPException(409,'Required calibration is missing')
        if due<date.today():raise HTTPException(409,'Required calibration is overdue')
    if c.execute("SELECT 1 FROM inventory_quarantine WHERE ((source_table='tools' AND source_id=?) OR tool_id=?) AND released_at IS NULL",(row['id'],row['id'])).fetchone():
        raise HTTPException(409,'This tool is quarantined or under repair')
    if row['source_grn_item_id'] and not row['location_id']:raise HTTPException(409,'Complete receipt inspection and put-away before issuing this tool')
    if c.execute("SELECT 1 FROM tool_custody_history WHERE tool_id=? AND status='CHECKED_OUT'",(row['id'],)).fetchone():raise HTTPException(409,'Tool is already assigned')


def tool_stock_out(c,row,user,event):
    from ..stock import consume
    if not row['source_grn_item_id']:return row['custody_unit_cost']
    cost,_=consume(c,item_id=row['item_id'],warehouse_id=row['warehouse_id'],location_id=row['location_id'],quantity=1,
        transaction_type=event,reference_number=row['tool_code'],reference_table='tools',reference_id=row['id'],created_by=user['id'],source_grn_item_id=row['source_grn_item_id'])
    return cost


def tool_stock_in(c,row,user,event,warehouse_id=None,location_id=None):
    from ..stock import receive
    if row['source_grn_item_id']:
        receive(c,item_id=row['item_id'],warehouse_id=warehouse_id or row['warehouse_id'],location_id=location_id or row['location_id'],quantity=1,
            unit_cost=row['custody_unit_cost'],source_grn_item_id=row['source_grn_item_id'],transaction_type=event,
            reference_number=row['tool_code'],reference_table='tools',reference_id=row['id'],created_by=user['id'])


@router.put('/tools/{tool_id}/checkout')
def checkout(tool_id:int,body:dict,user:dict=Depends(tool_user)):
    employee_id=body.get('employee_id')
    if not isinstance(employee_id,int):raise HTTPException(400,'A valid employee is required')
    with transaction(immediate=True) as c:
        row=scoped_tool(c,tool_id,user)
        issue_eligible(c,row,body.get('warehouse_id'))
        employee=c.execute("SELECT id FROM employees WHERE id=? AND status='Active' AND deleted_at IS NULL",(employee_id,)).fetchone()
        if not employee:raise HTTPException(400,'Tool custody requires a valid active employee')
        cost=tool_stock_out(c,row,user,'TOOL_ISSUE')
        c.execute("UPDATE tools SET employee_id=?,issue_date=date('now'),return_date=NULL,status='Assigned',custody_unit_cost=? WHERE id=?",(employee_id,cost,tool_id))
        c.execute('INSERT INTO tool_custody_history(tool_id,employee_id,warehouse_id,checked_out_by)VALUES(?,?,?,?)',(tool_id,employee_id,row['warehouse_id'],user['id']))
        log_audit(c,'tools',tool_id,'UPDATE',user['id'],row,{'event':'MANUAL_ISSUE','employee_id':employee_id,'status':'Assigned'})
        from .clearance import refresh_active_for_employee
        refresh_active_for_employee(c,employee_id)
    return {'success':True}


@router.put('/tools/{tool_id}/checkin')
def checkin(tool_id:int,body:dict,user:dict=Depends(tool_user)):
    condition=body.get('condition')
    if condition not in ['Good','Damaged','Needs Repair']:raise HTTPException(400,'Select a valid return condition')
    with transaction(immediate=True) as c:
        row=scoped_tool(c,tool_id,user)
        if row['status']!='Assigned' or not row['employee_id'] or row['return_date']:raise HTTPException(409,'Tool is not currently assigned')
        status='Available' if condition=='Good' else ('Under Repair' if condition=='Needs Repair' else 'Quarantined')
        if condition=='Good':tool_stock_in(c,row,user,'TOOL_RETURN')
        else:
            c.execute("""INSERT INTO inventory_quarantine(item_id,warehouse_id,location_id,quantity,unit_cost,inventory_status,source_table,source_id,created_by,audit_reference)
                VALUES(?,?,?,1,?,?,'tools',?,?,?)""",(row['item_id'],row['warehouse_id'],row['location_id'],row['custody_unit_cost'],'REPAIR_PENDING' if condition=='Needs Repair' else 'DAMAGED',tool_id,user['id'],row['tool_code']))
        c.execute("UPDATE tools SET employee_id=NULL,return_date=date('now'),condition=?,status=? WHERE id=?",(condition,status,tool_id))
        c.execute("UPDATE tool_custody_history SET checked_in_by=?,checked_in_at=datetime('now'),return_condition=?,status='RETURNED' WHERE tool_id=? AND status='CHECKED_OUT'",(user['id'],condition,tool_id))
        log_audit(c,'tools',tool_id,'UPDATE',user['id'],row,{'event':'MANUAL_RETURN','condition':condition,'status':status,'employee_id':row['employee_id']})
        from .clearance import refresh_active_for_employee
        refresh_active_for_employee(c,row['employee_id'])
    return {'success':True}


@router.get('/tools/{tool_id}/history')
def tool_history(tool_id:int,user:dict=Depends(tool_user)):
    with transaction() as c:
        row=scoped_tool(c,tool_id,user)
        grn=c.execute('SELECT g.grn_number,g.id,gi.id grn_item_id FROM grn_items gi JOIN grns g ON g.id=gi.grn_id WHERE gi.id=?',(row['source_grn_item_id'],)).fetchone()
        return {'grn':dict(grn) if grn else None,
            'custody':[dict(r) for r in c.execute('SELECT h.*,e.name employee_name FROM tool_custody_history h JOIN employees e ON e.id=h.employee_id WHERE tool_id=? ORDER BY h.id',(tool_id,))],
            'events':[dict(r) for r in c.execute("SELECT * FROM audit_log WHERE table_name='tools' AND record_id=? ORDER BY id",(tool_id,))]}


@router.put('/tools/{tool_id}/lifecycle')
def tool_lifecycle(tool_id:int,body:dict,user:dict=Depends(tool_user)):
    action=body.get('action');reason=str(body.get('reason') or '').strip()
    if not reason:raise HTTPException(400,'A reason or repair reference is required')
    if user['role'] not in ('SupplyChainManager','WarehouseManager','WarehouseSupervisor'):raise HTTPException(403,'A warehouse supervisor or manager must authorize this action')
    if action=='transfer':
        if 'task.transfers' not in user.get('permission_keys',[]):raise HTTPException(403,'Warehouse transfer permission is required')
        with transaction() as c:
            row=scoped_tool(c,tool_id,user)
        if not row['source_grn_item_id']:raise HTTPException(409,'Legacy tools require stock reconciliation before transfer')
        from .warehouse import create_transfer
        return create_transfer({'tool_id':tool_id,'item_id':row['item_id'],'quantity':1,
            'transaction_uom':fetch_one('SELECT uom FROM items WHERE id=?',(row['item_id'],))['uom'],
            'from_warehouse_id':row['warehouse_id'],'from_location_id':row['location_id'],
            'to_warehouse_id':body.get('warehouse_id'),'to_location_id':body.get('location_id'),'remarks':reason},user)
    with transaction(immediate=True) as c:
        row=scoped_tool(c,tool_id,user)
        if row['transfer_pending_yn']:raise HTTPException(409,'Complete the warehouse transfer receipt first')
        if c.execute("SELECT 1 FROM transfer_shortages WHERE transfer_id=? AND status='OPEN'",(row['transfer_id'],)).fetchone():raise HTTPException(409,'Resolve the existing transfer shortage first')
        if row['employee_id'] or row['status'] in ('Assigned','Pending Tool Registration','Retired'):raise HTTPException(409,'Return and register this tool before changing its lifecycle; retired tools cannot be changed')
        if action=='repair_complete':
            if row['status'] not in ('Quarantined','Damaged','Under Repair'):raise HTTPException(409,'Tool is not awaiting repair')
            if row['source_grn_item_id'] and not row['location_id']:
                if not c.execute('SELECT 1 FROM inventory_quarantine WHERE tool_id=? AND released_at IS NULL',(tool_id,)).fetchone():raise HTTPException(409,'Complete receipt disposition and put-away first')
                from .warehouse import locations
                locations(row['warehouse_id'],body.get('location_id'))
                row['location_id']=body['location_id']
                c.execute('UPDATE tools SET location_id=? WHERE id=?',(row['location_id'],tool_id))
            tool_stock_in(c,row,user,'TOOL_REPAIR_RETURN')
            c.execute("UPDATE inventory_quarantine SET released_at=datetime('now'),released_by=? WHERE ((source_table='tools' AND source_id=?) OR tool_id=?) AND released_at IS NULL",(user['id'],tool_id,tool_id))
            c.execute("UPDATE tools SET status='Available',condition='Good' WHERE id=?",(tool_id,))
        elif action=='calibrate':
            values=registration_values(c,{**row,**body},tool_id)
            if not values[3]:raise HTTPException(400,'Enter the new calibration due date')
            c.execute('UPDATE tools SET calibration_due_date=?,calibration_required_yn=1 WHERE id=?',(values[3],tool_id))
        elif action in ('retire','lost'):
            if row['status']=='Available' and row['source_grn_item_id']:
                if not row['location_id']:raise HTTPException(409,'Complete receipt disposition first')
                tool_stock_out(c,row,user,'TOOL_RETIRE' if action=='retire' else 'TOOL_LOST')
            c.execute("UPDATE inventory_quarantine SET released_at=datetime('now'),released_by=? WHERE ((source_table='tools' AND source_id=?) OR tool_id=?) AND released_at IS NULL",(user['id'],tool_id,tool_id))
            c.execute('UPDATE tools SET status=?,condition=? WHERE id=?',('Retired' if action=='retire' else 'Lost','Retired' if action=='retire' else 'Lost',tool_id))
        else:raise HTTPException(400,'Select a valid tool lifecycle action')
        log_audit(c,'tools',tool_id,'UPDATE',user['id'],row,{**body,'event':action})
    return {'success':True}


@router.get('/vendor-scorecards')
def scorecards(_user:dict=Depends(roles('SupplyChainManager','PurchaseManager'))):
    return fetch_all("""SELECT s.id supplier_id,s.name supplier_name,strftime('%Y-%m','now') period,
      ROUND(CASE WHEN COUNT(DISTINCT g.id)=0 THEN 0 ELSE 5.0*SUM(CASE WHEN po.committed_delivery_date IS NULL OR date(g.grn_date)<=date(po.committed_delivery_date) THEN 1 ELSE 0 END)/COUNT(DISTINCT g.id) END,2) delivery_accuracy,
      NULL price_competitiveness,
      ROUND(CASE WHEN COALESCE(SUM(gi.quantity_received),0)=0 THEN 0 ELSE 5.0*SUM(gi.accepted_qty)/SUM(gi.quantity_received) END,2) quality,
      NULL response_time,
      ROUND(CASE WHEN COUNT(DISTINCT po.id)=0 THEN 0 ELSE 5.0*COUNT(DISTINCT g.id)/COUNT(DISTINCT po.id) END,2) reliability,
      ROUND(CASE WHEN COALESCE(SUM(gi.quantity_received),0)=0 OR COUNT(DISTINCT g.id)=0 THEN COALESCE(s.rating,0)
        ELSE (0.30*(5.0*SUM(CASE WHEN po.committed_delivery_date IS NULL OR date(g.grn_date)<=date(po.committed_delivery_date) THEN 1 ELSE 0 END)/COUNT(DISTINCT g.id)))+(0.70*(5.0*SUM(gi.accepted_qty)/SUM(gi.quantity_received))) END,2) overall_score,
      COUNT(DISTINCT po.id) purchase_orders,COUNT(DISTINCT g.id) receipts,COALESCE(SUM(gi.rejected_qty),0) rejected_quantity
      FROM suppliers s LEFT JOIN purchase_orders po ON po.supplier_id=s.id
      LEFT JOIN grns g ON g.po_id=po.id LEFT JOIN grn_items gi ON gi.grn_id=g.id
      WHERE s.deleted_at IS NULL GROUP BY s.id,s.name,s.rating ORDER BY overall_score DESC,s.name""")

@router.post('/vendor-scorecards',status_code=201)
def create_scorecard(body:dict,user:dict=Depends(roles('PurchaseManager','SupplyChainManager'))):
    raise HTTPException(405,'Vendor scorecards are calculated automatically from PO and GRN performance')
    if not isinstance(body.get('supplier_id'),int) or not str(body.get('period') or '').strip():raise HTTPException(400,'Supplier and period are required')
    fields=['delivery_accuracy','price_competitiveness','quality','response_time','reliability'];values=[body.get(k) for k in fields]
    if any(v is not None and (not isinstance(v,(int,float)) or v<0 or v>5) for v in values):raise HTTPException(400,'Scores must be between 0 and 5')
    scores=[float(v) for v in values if v is not None];overall=sum(scores)/len(scores) if scores else 0
    with transaction(immediate=True) as connection:
        cursor=connection.execute(f"INSERT INTO vendor_scorecards(supplier_id,period,{','.join(fields)},overall_score) VALUES({','.join('?' for _ in range(8))})",(body['supplier_id'],body['period'],*values,overall));log_audit(connection,'vendor_scorecards',cursor.lastrowid,'CREATE',user['id'],after=body)
    return {'id':cursor.lastrowid,'overall_score':overall}
