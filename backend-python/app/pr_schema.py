"""Idempotent PR workflow migration; preserve records, keys, indexes and history."""
import re
import sqlite3
from .database import active_db_path, transaction


def _extend_statuses(table, values, column='status'):
    with sqlite3.connect(active_db_path()) as c:
        sql=c.execute('SELECT sql FROM sqlite_master WHERE name=?',(table,)).fetchone()[0]
        match=re.search(r'CHECK\s*\('+re.escape(column)+r'\s+IN\s*\(([^)]*)\)\)',sql,re.I)
        if not match or all("'"+v+"'" in match[1] for v in values):return
        extended=match[1]+''.join(",'%s'"%v for v in values if "'"+v+"'" not in match[1])
        replacement=sql[:match.start(1)]+extended+sql[match.end(1):]
        temporary=table+'__workflow_migration'
        replacement=re.sub(r'CREATE TABLE\s+"?'+table+r'"?', 'CREATE TABLE '+temporary,replacement,count=1,flags=re.I)
        extras=[row[0] for row in c.execute("SELECT sql FROM sqlite_master WHERE tbl_name=? AND type IN('index','trigger') AND sql IS NOT NULL",(table,))]
        columns=','.join('"'+row[1]+'"' for row in c.execute('PRAGMA table_info('+table+')'))
        c.execute('PRAGMA foreign_keys=OFF');c.execute('PRAGMA legacy_alter_table=ON');c.execute('BEGIN IMMEDIATE')
        try:
            c.execute(replacement);c.execute(f'INSERT INTO {temporary}({columns}) SELECT {columns} FROM {table}')
            c.execute('DROP TABLE '+table);c.execute(f'ALTER TABLE {temporary} RENAME TO {table}')
            for statement in extras:c.execute(statement)
            c.commit()
        except Exception:c.rollback();raise


def ensure_pr_workflow_schema():
    _extend_statuses('document_attachments',['RFQ','QUOTATION','AWARD','ADJUSTMENT'],column='document_type')
    _extend_statuses('purchase_requisitions',['Partially Ordered','Cancelled'])
    _extend_statuses('purchase_orders',['Cancelled','Voided','Partially Received'])
    with transaction(immediate=True) as c:
        additions={
            'purchase_orders':{'print_count':'INTEGER NOT NULL DEFAULT 0'},
            'grn_items':{'damaged_qty':'REAL NOT NULL DEFAULT 0','short_qty':'REAL NOT NULL DEFAULT 0','receiving_issue_reason':'TEXT','receiving_notes':'TEXT'},
            'goods_inspections':{'damaged_quantity':'REAL NOT NULL DEFAULT 0','issue_reason':'TEXT'},
            'purchase_requisitions':{'reviewed_by':'INTEGER REFERENCES users(id)','reviewed_at':'TEXT','approved_by':'INTEGER REFERENCES users(id)','approved_at':'TEXT','closed_at':'TEXT','legacy_procurement_handoff_yn':'INTEGER NOT NULL DEFAULT 0'},
            'pr_items':{'warehouse_requested_quantity':'REAL','approved_quantity':'REAL','approved_base_quantity':'REAL','procurement_quantity_variance':'REAL','procurement_adjustment_reason':'TEXT','procurement_adjusted_by':'INTEGER REFERENCES users(id)','procurement_adjusted_at':'TEXT'},
            'company':{'default_payment_terms':'TEXT'},
        }
        for table,columns in additions.items():
            existing={r['name'] for r in c.execute('PRAGMA table_info('+table+')')}
            for name,kind in columns.items():
                if name not in existing:c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {kind}')
        c.execute('''CREATE TABLE IF NOT EXISTS rfq_items(
            id INTEGER PRIMARY KEY,rfq_id INTEGER NOT NULL REFERENCES rfqs(id),
            pr_item_id INTEGER NOT NULL REFERENCES pr_items(id),item_id INTEGER NOT NULL REFERENCES items(id),
            quantity REAL NOT NULL,UNIQUE(rfq_id,pr_item_id))''')
        existing={r['name'] for r in c.execute('PRAGMA table_info(rfq_items)')}
        for column,kind in {'transaction_uom':'TEXT','base_uom':'TEXT','conversion_factor_used':'REAL'}.items():
            if column not in existing:c.execute(f'ALTER TABLE rfq_items ADD COLUMN {column} {kind}')
        if not c.execute("SELECT 1 FROM settings WHERE key='rfq_quantity_snapshot_v1'").fetchone():
            # Historical RFQs used the original request; preserve their issued quantities.
            c.execute('INSERT OR IGNORE INTO rfq_items(rfq_id,pr_item_id,item_id,quantity,transaction_uom,base_uom,conversion_factor_used) SELECT r.id,p.id,p.item_id,p.quantity,p.transaction_uom,p.base_uom,COALESCE(p.conversion_factor_used,1) FROM rfqs r JOIN pr_items p ON p.pr_id=r.pr_id')
            c.execute("INSERT INTO settings(key,value)VALUES('rfq_quantity_snapshot_v1','1')")
        if not c.execute("SELECT 1 FROM settings WHERE key='pr_review_workflow_v1'").fetchone():
            c.execute("""UPDATE purchase_requisitions SET pr_source='WAREHOUSE_MANUAL',trigger_warehouse_id=COALESCE(trigger_warehouse_id,
                (SELECT source_warehouse_id FROM pr_items WHERE pr_id=purchase_requisitions.id AND source_warehouse_id IS NOT NULL LIMIT 1),
                (SELECT warehouse_id FROM users WHERE id=purchase_requisitions.requestor_id))
                WHERE auto_generated=0 AND pr_source='MANUAL' AND requestor_id IN(SELECT id FROM users WHERE role IN('WarehouseManager','WarehouseSupervisor','Storekeeper'))""")
            c.execute("UPDATE purchase_requisitions SET pr_source='PROCUREMENT_MANUAL' WHERE auto_generated=0 AND pr_source='MANUAL'")
            c.execute('UPDATE pr_items SET warehouse_requested_quantity=quantity WHERE warehouse_requested_quantity IS NULL')
            # Only real historical approvals with an actor and timestamp are reconciled.
            for pr in c.execute("SELECT * FROM purchase_requisitions WHERE status IN('Submitted','Approved','Partially Ordered','Closed')").fetchall():
                approval=c.execute("SELECT * FROM approval_log WHERE document_type='PR' AND document_id=? ORDER BY id DESC LIMIT 1",(pr['id'],)).fetchone()
                if not approval or approval['decision']!='Approved' or not approval['decision_by'] or not approval['decision_date']:continue
                c.execute("UPDATE purchase_requisitions SET status=CASE WHEN status='Submitted' THEN 'Approved' ELSE status END,approved_by=?,approved_at=?,reviewed_by=?,reviewed_at=? WHERE id=?",(approval['decision_by'],approval['decision_date'],approval['decision_by'],approval['decision_date'],pr['id']))
                c.execute('UPDATE pr_items SET approved_quantity=quantity,approved_base_quantity=COALESCE(base_quantity,quantity),procurement_quantity_variance=0 WHERE pr_id=? AND approved_quantity IS NULL',(pr['id'],))
            c.execute("INSERT INTO settings(key,value)VALUES('pr_review_workflow_v1','1')")
        if not c.execute("SELECT 1 FROM settings WHERE key='pr_history_reconciliation_v2'").fetchone():
            from .pr_workflow import approval_valid,refresh_pr_order_status
            from .audit import log_audit
            for record in c.execute("SELECT * FROM purchase_requisitions WHERE status IN('Submitted','Approved','Partially Ordered','Closed')").fetchall():
                pr=dict(record)
                # Preserve access to historical manual records already processed by Procurement.
                # This explicit legacy flag does not invent a warehouse submission actor/date.
                if pr['pr_source']=='WAREHOUSE_MANUAL' and not pr['warehouse_submitted_at'] and c.execute("SELECT 1 FROM approval_log WHERE document_type='PR' AND document_id=?",(pr['id'],)).fetchone():
                    c.execute('UPDATE purchase_requisitions SET legacy_procurement_handoff_yn=1 WHERE id=?',(pr['id'],))
                    log_audit(c,'purchase_requisitions',pr['id'],'UPDATE',None,after={'workflow_action':'LEGACY_PROCUREMENT_HANDOFF_RECONCILIATION'})
                if approval_valid(c,pr):
                    refresh_pr_order_status(c,pr['id'],None)
                elif pr['status'] in ('Approved','Partially Ordered','Closed') and not pr.get('warehouse_closed_at'):
                    c.execute("UPDATE purchase_requisitions SET status='Submitted',approved_by=NULL,approved_at=NULL,reviewed_by=NULL,reviewed_at=NULL,closed_at=NULL WHERE id=?",(pr['id'],))
                    latest=c.execute("SELECT decision FROM approval_log WHERE document_type='PR' AND document_id=? ORDER BY id DESC LIMIT 1",(pr['id'],)).fetchone()
                    if not latest or latest['decision']!='Pending':
                        c.execute("INSERT INTO approval_log(document_type,document_id,document_number,required_role,requested_by,decision,comments)VALUES('PR',?,?,'SupplyChainManager',?,'Pending','Legacy status lacks verified approval; Procurement review required')",(pr['id'],pr['pr_number'],pr['requestor_id']))
                    log_audit(c,'purchase_requisitions',pr['id'],'UPDATE',None,{'status':pr['status']},{'status':'Submitted','workflow_action':'LEGACY_APPROVAL_REVIEW_REQUIRED'})
            c.execute("INSERT INTO settings(key,value)VALUES('pr_history_reconciliation_v2','1')")

        if not c.execute("SELECT 1 FROM settings WHERE key='po_usable_receipt_status_v1'").fetchone():
            from .receiving import refresh_receipt_status
            from .audit import log_audit
            for po in c.execute("SELECT id,status FROM purchase_orders WHERE status IN('Approved','Printed','Partially Received','Closed') AND EXISTS(SELECT 1 FROM grns WHERE po_id=purchase_orders.id)").fetchall():
                refresh_receipt_status(c,po['id'])
                status=c.execute('SELECT status FROM purchase_orders WHERE id=?',(po['id'],)).fetchone()['status']
                if status!=po['status']:log_audit(c,'purchase_orders',po['id'],'UPDATE',None,{'status':po['status']},{'status':status,'workflow_action':'USABLE_RECEIPT_STATUS_RECONCILIATION'})
            c.execute("INSERT INTO settings(key,value)VALUES('po_usable_receipt_status_v1','1')")
