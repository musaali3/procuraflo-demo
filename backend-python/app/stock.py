from fastapi import HTTPException

TERMINAL_TYPES={'AISLE_RACK_SHELF_BIN':'Bin','RACK_SHELF_BIN':'Bin','RACK':'Rack','BAY':'Bay','YARD_SLOT':'Yard Slot','GROUND_STACK':'Ground Stack','BIN_ONLY':'Bin','STAGING':'Staging'}

def is_terminal_storage_location(location):
    structure=str(location.get('structure_type')or'').upper();kind=location.get('type')
    if structure in ('OPEN_AREA','QUARANTINE_AREA','REPAIR_AREA'):return kind in('Zone','Open Area')
    if structure in TERMINAL_TYPES:return kind==TERMINAL_TYPES[structure]
    return kind=='Bin'

def _validate_context(c,item_id,warehouse_id,location_id):
    if not isinstance(item_id,int) or not isinstance(warehouse_id,int):
        raise HTTPException(400,'A valid item and warehouse are required for every inventory posting')
    if not c.execute('SELECT 1 FROM items WHERE id=? AND deleted_at IS NULL',(item_id,)).fetchone():
        raise HTTPException(400,'Inventory posting item is invalid or inactive')
    if not c.execute('SELECT 1 FROM warehouses WHERE id=? AND deleted_at IS NULL',(warehouse_id,)).fetchone():
        raise HTTPException(400,'Inventory posting warehouse is invalid or inactive')
    if location_id is not None:
        row=c.execute("SELECT * FROM locations WHERE id=? AND warehouse_id=? AND COALESCE(active_yn,1)=1 AND status NOT IN('Inactive','Blocked','Maintenance','Full') AND deleted_at IS NULL",(location_id,warehouse_id)).fetchone()
        if not row or not is_terminal_storage_location(dict(row)):raise HTTPException(400,'Select an active terminal storage location valid for the configured Zone structure')

def receive(c,*,item_id,warehouse_id,location_id,quantity,unit_cost,batch=None,expiry_date=None,received_date=None,transaction_type='RECEIPT',reference_number=None,reference_table=None,reference_id=None,created_by=None,source_grn_item_id=None):
    _validate_context(c,item_id,warehouse_id,location_id)
    if not isinstance(quantity,(int,float)) or quantity<=0:raise HTTPException(400,'Receipt quantity must be greater than zero')
    c.execute('INSERT INTO inventory_layers(item_id,warehouse_id,location_id,batch,expiry_date,received_date,quantity_remaining,unit_cost,source_grn_item_id)VALUES(?,?,?,?,?,COALESCE(?,date(\'now\')),?,?,?)',(item_id,warehouse_id,location_id,batch,expiry_date,received_date,quantity,unit_cost,source_grn_item_id))
    row=c.execute('SELECT id FROM inventory_stock WHERE item_id=? AND warehouse_id=? AND location_id IS ?',(item_id,warehouse_id,location_id)).fetchone()
    if row:c.execute('UPDATE inventory_stock SET quantity=quantity+? WHERE id=?',(quantity,row['id']))
    else:c.execute('INSERT INTO inventory_stock(item_id,warehouse_id,location_id,quantity)VALUES(?,?,?,?)',(item_id,warehouse_id,location_id,quantity))
    c.execute('INSERT INTO stock_ledger(transaction_type,item_id,warehouse_id,location_id,quantity_change,unit_cost,reference_number,reference_table,reference_id,created_by)VALUES(?,?,?,?,?,?,?,?,?,?)',(transaction_type,item_id,warehouse_id,location_id,quantity,unit_cost,reference_number,reference_table,reference_id,created_by))
def consume(c,*,item_id,warehouse_id,location_id,quantity,transaction_type='ISSUE',reference_number=None,reference_table=None,reference_id=None,created_by=None,source_grn_item_id=None):
    _validate_context(c,item_id,warehouse_id,location_id)
    if not transaction_type.startswith('TOOL_') and c.execute('SELECT 1 FROM tools WHERE item_id=? AND warehouse_id=? AND source_grn_item_id IS NOT NULL',(item_id,warehouse_id)).fetchone():
        raise HTTPException(409,'This item has individually controlled tools. Use Tool Management and select a Tool Code for issue or movement')
    if quantity<=0:raise HTTPException(400,'Issue quantity must be greater than zero')
    layers=c.execute('SELECT id,quantity_remaining,unit_cost FROM inventory_layers WHERE item_id=? AND warehouse_id=? AND location_id IS ? AND quantity_remaining>0 AND (? IS NULL OR source_grn_item_id=?) ORDER BY received_date,id',(item_id,warehouse_id,location_id,source_grn_item_id,source_grn_item_id)).fetchall();available=sum(x['quantity_remaining']for x in layers)
    if available<quantity:raise HTTPException(400,f'Insufficient stock: requested {quantity}, available {available} for item {item_id} at the selected storage location')
    left=quantity;cost=0;used=[]
    for layer in layers:
        if left<=0:break
        take=min(layer['quantity_remaining'],left);c.execute('UPDATE inventory_layers SET quantity_remaining=quantity_remaining-? WHERE id=?',(take,layer['id']));c.execute('INSERT INTO stock_ledger(transaction_type,item_id,warehouse_id,location_id,quantity_change,unit_cost,inventory_layer_id,reference_number,reference_table,reference_id,created_by)VALUES(?,?,?,?,?,?,?,?,?,?,?)',(transaction_type,item_id,warehouse_id,location_id,-take,layer['unit_cost'],layer['id'],reference_number,reference_table,reference_id,created_by));cost+=take*layer['unit_cost'];used.append((layer['id'],take,layer['unit_cost']));left-=take
    c.execute('UPDATE inventory_stock SET quantity=quantity-? WHERE item_id=? AND warehouse_id=? AND location_id IS ?',(quantity,item_id,warehouse_id,location_id));return cost,used
