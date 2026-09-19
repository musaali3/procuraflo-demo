"""RFQ line selection in purchasing units, bounded by approved PR balances."""
from fastapi import HTTPException
from .calculations import uom_snapshot,decimal_value
from .pr_workflow import pr_lines,require_eligible


def source_items(c,pr_id,user):
    pr=require_eligible(c,pr_id,user)
    result=[]
    for line in pr_lines(c,pr_id):
        if line['remaining_quantity']<=1e-8:continue
        item=dict(c.execute('SELECT * FROM items WHERE id=?',(line['item_id'],)).fetchone())
        unit=uom_snapshot(item,1,purpose='purchase')
        factor=float(line.get('base_quantity') or line['quantity'])/float(line['quantity'])
        available=line['remaining_quantity']*factor/float(unit['conversion_factor_used'])
        result.append({**line,'source_warehouse_id':pr.get('trigger_warehouse_id') or line.get('source_warehouse_id'),'pr_item_id':line['id'],'pr_uom':line['transaction_uom'],'transaction_uom':unit['transaction_uom'],
                       'base_uom':unit['base_uom'],'conversion_factor_used':float(unit['conversion_factor_used']),
                       'available_quantity':available,'quantity':available})
    return result


def save_items(c,rfq_id,pr_id,user,selection=None):
    available={x['pr_item_id']:x for x in source_items(c,pr_id,user)}
    chosen=list(available.values()) if selection is None else selection
    if not isinstance(chosen,list) or not chosen:raise HTTPException(400,'Select at least one approved PR item for the RFQ')
    seen=set();prepared=[]
    for line in chosen:
        if not isinstance(line,dict):raise HTTPException(400,'Invalid RFQ item selection')
        key=line.get('pr_item_id')
        if key not in available or key in seen:raise HTTPException(400,'Select each available PR line at most once')
        seen.add(key);source=available[key];qty=decimal_value(line.get('quantity'),'RFQ quantity',positive=True)
        if not qty.is_finite() or float(qty)>source['available_quantity']+1e-8:raise HTTPException(409,'RFQ quantity exceeds the remaining approved PR balance')
        prepared.append((rfq_id,key,source['item_id'],float(qty),source['transaction_uom'],source['base_uom'],source['conversion_factor_used']))
    c.execute('DELETE FROM rfq_items WHERE rfq_id=?',(rfq_id,))
    c.executemany('INSERT INTO rfq_items(rfq_id,pr_item_id,item_id,quantity,transaction_uom,base_uom,conversion_factor_used)VALUES(?,?,?,?,?,?,?)',prepared)


def save_suppliers(c,rfq_id,supplier_ids):
    if not isinstance(supplier_ids,list) or not supplier_ids or any(type(x) is not int for x in supplier_ids):raise HTTPException(400,'Select at least one valid supplier')
    ids=set(supplier_ids)
    valid={r['id'] for r in c.execute('SELECT id FROM suppliers WHERE deleted_at IS NULL AND active_yn=1 AND blocked_yn=0')}
    if not ids<=valid:raise HTTPException(409,'Inactive, blocked, or unknown suppliers cannot be invited')
    for row in c.execute('SELECT supplier_id FROM rfq_suppliers WHERE rfq_id=?',(rfq_id,)).fetchall():
        if row['supplier_id'] not in ids:c.execute('DELETE FROM rfq_suppliers WHERE rfq_id=? AND supplier_id=?',(rfq_id,row['supplier_id']))
    for supplier in ids:
        c.execute('INSERT OR IGNORE INTO rfq_suppliers(rfq_id,supplier_id,contact_person,email)SELECT ?,id,contact_person,email FROM suppliers WHERE id=?',(rfq_id,supplier))
