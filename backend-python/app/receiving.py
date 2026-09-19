"""Receipt progress separates delivery, restricted stock and completed put-away."""
from contextlib import closing
from .database import connect

def receipt_progress(po_id,c=None):
    if c is None:
        with closing(connect()) as connection:return receipt_progress(po_id,connection)
    po=c.execute('SELECT status FROM purchase_orders WHERE id=?',(po_id,)).fetchone()
    lines=[];receipts=[]
    ordered=c.execute('SELECT pi.item_id,SUM(pi.quantity) ordered_quantity,i.item_code,i.description,COALESCE(pi.transaction_uom,i.purchase_uom,i.uom) uom FROM po_items pi JOIN items i ON i.id=pi.item_id WHERE pi.po_id=? GROUP BY pi.item_id',(po_id,)).fetchall()
    for item in ordered:
        line=dict(item);physical=usable=pending=rejected=damaged=short=0
        for raw in c.execute('SELECT gi.*,g.grn_number,g.grn_date,w.name warehouse_name FROM grn_items gi JOIN grns g ON g.id=gi.grn_id JOIN warehouses w ON w.id=gi.warehouse_id WHERE g.po_id=? AND gi.item_id=? ORDER BY g.id,gi.id',(po_id,item['item_id'])):
            gi=dict(raw);factor=float(gi.get('conversion_factor_used') or 1)
            inspections=[dict(x) for x in c.execute('SELECT * FROM goods_inspections WHERE grn_item_id=?',(gi['id'],))]
            holds=[dict(x) for x in c.execute('SELECT * FROM inventory_quarantine WHERE source_grn_item_id=?',(gi['id'],))]
            failed=sum(x['failed_quantity'] for x in inspections)/factor
            accepted=float(gi['accepted_qty'] or 0)
            if holds:
                released=float(c.execute("SELECT COALESCE(SUM(p.quantity),0) FROM putaway_recommendations p JOIN inventory_quarantine q ON q.id=p.source_id WHERE p.source_table='inventory_quarantine' AND p.status='CONFIRMED' AND q.source_grn_item_id=?",(gi['id'],)).fetchone()[0])/factor
                waiting=0
                for hold in holds:
                    if hold['released_at'] or hold['inventory_status'] not in ('INSPECTION_PENDING','PUT_AWAY_PENDING'):continue
                    qty=float(hold['quantity'])
                    if hold['inventory_status']=='INSPECTION_PENDING':qty-=sum(x['inspected_quantity'] for x in inspections if x['hold_id']==hold['id'])
                    waiting+=max(0,qty)/factor
            else:released=max(0,accepted-failed);waiting=0 # Historical direct-to-stock receipts.
            rejected_qty=float(gi['rejected_qty'] or 0)+failed
            damaged_qty=float(gi.get('damaged_qty') or 0)+sum(float(x.get('damaged_quantity') or 0) for x in inspections)/factor
            missing=float(gi.get('short_qty') or 0)
            reasons=[gi.get('receiving_issue_reason'),gi.get('rejection_reason')]+[x.get('issue_reason') for x in inspections]
            notes=[gi.get('receiving_notes')]+[x.get('remarks') for x in inspections]
            receipts.append({'item_id':item['item_id'],'item_code':item['item_code'],'description':item['description'],'uom':item['uom'],'grn_id':gi['grn_id'],'grn_number':gi['grn_number'],'receipt_date':gi['grn_date'],'warehouse':gi['warehouse_name'],'ordered_quantity':item['ordered_quantity'],'physically_delivered_quantity':gi['quantity_received'],'accepted_usable_quantity':released,'pending_quantity':waiting,'damaged_quantity':damaged_qty,'rejected_quantity':rejected_qty,'short_quantity':missing,'issue_reason':'; '.join(dict.fromkeys(x for x in reasons if x)),'notes':'; '.join(x for x in notes if x)})
            physical+=float(gi['quantity_received']);usable+=released;pending+=waiting;rejected+=rejected_qty;damaged+=damaged_qty;short+=missing
        line.update(physically_delivered_quantity=physical,accepted_usable_quantity=usable,pending_quantity=pending,rejected_quantity=rejected,damaged_quantity=damaged,short_quantity=short,outstanding_quantity=max(0,float(item['ordered_quantity'])-usable),receivable_quantity=max(0,float(item['ordered_quantity'])-usable-pending))
        lines.append(line)
    has_receipts=bool(receipts);complete=bool(lines) and all(x['outstanding_quantity']<1e-8 for x in lines)
    status=('Fully Received' if complete else 'Partially Received') if has_receipts else 'Not Received'
    return {'receiving_status':status,'fully_received':complete,'has_receipts':has_receipts,'receipt_lines':lines,'receipts':receipts}

def refresh_receipt_status(c,po_id):
    row=c.execute('SELECT status FROM purchase_orders WHERE id=?',(po_id,)).fetchone()
    if not row or row['status'] not in ('Approved','Printed','Partially Received','Closed'):return
    progress=receipt_progress(po_id,c)
    if progress['has_receipts']:
        c.execute('UPDATE purchase_orders SET status=? WHERE id=?',('Closed' if progress['fully_received'] else 'Partially Received',po_id))
