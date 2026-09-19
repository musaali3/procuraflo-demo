"""Shared PR visibility, genuine approval, allocation and lifecycle rules."""
from contextlib import closing
from fastapi import HTTPException
from .database import connect, fetch_one
from .audit import log_audit

WAREHOUSE_ROLES={'WarehouseManager','WarehouseSupervisor','Storekeeper'}
PROCUREMENT_ROLES={'SupplyChainManager','PurchaseManager','PurchaseOfficer'}
VALID_PO_STATUSES="('PendingApproval','Approved','Printed','Partially Received','Closed')"
APPROVED_STATUSES={'Approved','Partially Ordered','Closed'}


def warehouse_owned(row):
    # Retain warehouse access to historical records from the retired generator.
    return row.get('pr_source')=='WAREHOUSE_MANUAL' or bool(row.get('auto_generated'))


def warehouse_draft(row):
    return warehouse_owned(row) and row.get('status')=='Draft' and not row.get('warehouse_submitted_at')


def visibility_sql(user, alias='pr'):
    if user['role'] not in WAREHOUSE_ROLES:return '1=1'
    ids=','.join(str(int(wid)) for wid in user.get('warehouse_ids',[])) or 'NULL'
    # The PR warehouse is authoritative. Only legacy PRs without one fall back
    # to the warehouse stored on their item lines.
    return (f'({alias}.trigger_warehouse_id IN({ids}) OR '
            f'({alias}.trigger_warehouse_id IS NULL AND EXISTS('
            f'SELECT 1 FROM main.pr_items scope_line WHERE scope_line.pr_id={alias}.id '
            f'AND scope_line.source_warehouse_id IN({ids}))))')


def warehouse_matches_pr(row, user):
    authorized={int(wid) for wid in user.get('warehouse_ids',[])}
    assigned=row.get('trigger_warehouse_id')
    if assigned is not None:return int(assigned) in authorized
    return bool(authorized and fetch_one(
        f"SELECT 1 ok FROM pr_items WHERE pr_id=? AND source_warehouse_id IN({','.join('?' for _ in authorized)}) LIMIT 1",
        (row['id'],*authorized)))


def require_pr_access(row, user):
    if not row:raise HTTPException(404,'Purchase Requisition not found')
    if user['role'] in WAREHOUSE_ROLES and not warehouse_matches_pr(row,user):
        raise HTTPException(403,'Purchase Requisition is outside your authorized warehouse scope')
    return row


def can_manage_pr_draft(row, user):
    if row.get('status')!='Draft':return False
    if not row.get('auto_generated') and user['id']==row.get('requestor_id'):return True
    if warehouse_owned(row):
        return user['role'] in WAREHOUSE_ROLES and warehouse_matches_pr(row,user)
    return user['role']=='SupplyChainManager'


def require_pr_draft_management(row,user):
    if not can_manage_pr_draft(row,user):raise HTTPException(403,'Only the draft creator or authorized draft manager may change this PR')


def approval_valid(c, pr):
    if pr['status'] not in APPROVED_STATUSES or not pr.get('approved_by') or not pr.get('approved_at'):return False
    latest=c.execute("SELECT decision,decision_by,decision_date FROM approval_log WHERE document_type='PR' AND document_id=? ORDER BY id DESC LIMIT 1",(pr['id'],)).fetchone()
    return bool(latest and latest['decision']=='Approved' and latest['decision_by'] and latest['decision_date'])


def pr_lines(c, pr_id):
    return [dict(row) for row in c.execute(f'''SELECT x.*,i.item_code,i.description,i.uom,i.purchase_uom,i.issue_uom,
        COALESCE(x.warehouse_requested_quantity,x.quantity) requested_quantity,
        COALESCE(x.approved_quantity,x.quantity) procurement_quantity,
        COALESCE((SELECT SUM(a.quantity) FROM po_pr_item_allocations a JOIN purchase_orders po ON po.id=a.po_id
          WHERE a.pr_item_id=x.id AND po.status IN {VALID_PO_STATUSES}),0) ordered_quantity,
        MAX(0,COALESCE(x.approved_quantity,x.quantity)-COALESCE((SELECT SUM(a.quantity) FROM po_pr_item_allocations a JOIN purchase_orders po ON po.id=a.po_id
          WHERE a.pr_item_id=x.id AND po.status IN {VALID_PO_STATUSES}),0)) remaining_quantity
        FROM pr_items x JOIN items i ON i.id=x.item_id WHERE x.pr_id=? ORDER BY x.id''',(pr_id,))]


def pr_summary(c, pr):
    lines=pr_lines(c,pr['id']);valid=approval_valid(c,pr)
    remaining=sum(x['remaining_quantity'] for x in lines)
    source_label='Stock Replenishment Check' if pr.get('replenishment_draft_id') else ('Historical Replenishment' if pr.get('auto_generated') else 'Manual Request')
    return {'source_label':source_label,'approval_valid':valid,'eligible_for_rfq':valid and remaining>1e-8,'eligible_for_po':valid and remaining>1e-8,
            'remaining_quantity':remaining,'warehouse_owned':warehouse_owned(pr),'warehouse_draft':warehouse_draft(pr)}


def require_eligible(c,pr_id,user):
    row=c.execute('SELECT * FROM purchase_requisitions WHERE id=?',(pr_id,)).fetchone()
    pr=require_pr_access(dict(row) if row else None,user)
    if not pr_summary(c,pr)['eligible_for_po']:raise HTTPException(409,'PR must have a completed Procurement approval and remaining approved quantities')
    return pr


def refresh_pr_order_status(c,pr_id,user_id,related_po_id=None):
    row=c.execute('SELECT * FROM purchase_requisitions WHERE id=?',(pr_id,)).fetchone()
    if not row:return
    pr=dict(row)
    if not approval_valid(c,pr):return
    lines=pr_lines(c,pr_id)
    if not lines:return
    remaining=any(x['remaining_quantity']>1e-8 for x in lines);ordered=any(x['ordered_quantity']>1e-8 for x in lines)
    status=('Partially Ordered' if ordered else 'Approved') if remaining else 'Closed'
    if status!=pr['status']:
        c.execute("UPDATE purchase_requisitions SET status=?,closed_manually=0,closed_at=CASE WHEN ?='Closed' THEN datetime('now') ELSE NULL END WHERE id=?",(status,status,pr_id))
        log_audit(c,'purchase_requisitions',pr_id,'UPDATE',user_id,{'status':pr['status']},{'status':status,'related_po_id':related_po_id,'workflow_action':'PO_QUANTITY_RECONCILIATION'})


def allocation_candidates(c,pr_ids,item_id):
    return [dict(line,pr_item_id=line['id'],available=line['remaining_quantity']) for pr_id in pr_ids for line in pr_lines(c,pr_id) if line['item_id']==item_id and line['remaining_quantity']>1e-8]


def scoped_report(sql,user,parameters=()):
    # Connection-local views apply the same access predicate even to aggregate reports.
    with closing(connect()) as c:
        if user['role'] in WAREHOUSE_ROLES:
            ids=','.join(str(int(wid)) for wid in user.get('warehouse_ids',[])) or 'NULL'
            c.execute(f'CREATE TEMP VIEW replenishment_drafts AS SELECT * FROM main.replenishment_drafts WHERE warehouse_id IN({ids})')
            c.execute('CREATE TEMP VIEW replenishment_draft_lines AS SELECT * FROM main.replenishment_draft_lines WHERE draft_id IN(SELECT id FROM replenishment_drafts)')
        c.execute('CREATE TEMP VIEW purchase_requisitions AS SELECT pr.* FROM main.purchase_requisitions pr WHERE '+visibility_sql(user))
        c.execute('CREATE TEMP VIEW pr_items AS SELECT * FROM main.pr_items WHERE pr_id IN(SELECT id FROM purchase_requisitions)')
        c.execute('CREATE TEMP VIEW rfqs AS SELECT * FROM main.rfqs WHERE pr_id IS NULL OR pr_id IN(SELECT id FROM purchase_requisitions)')
        c.execute('CREATE TEMP VIEW supplier_quotations AS SELECT * FROM main.supplier_quotations WHERE rfq_id IN(SELECT id FROM rfqs)')
        c.execute('CREATE TEMP VIEW rfq_awards AS SELECT * FROM main.rfq_awards WHERE rfq_id IN(SELECT id FROM rfqs)')
        c.execute("CREATE TEMP VIEW approval_log AS SELECT * FROM main.approval_log WHERE document_type<>'PR' OR document_id IN(SELECT id FROM purchase_requisitions)")
        c.execute("CREATE TEMP VIEW audit_log AS SELECT * FROM main.audit_log WHERE (table_name<>'purchase_requisitions' OR record_id IN(SELECT id FROM purchase_requisitions)) AND (table_name<>'pr_items' OR record_id IN(SELECT id FROM pr_items))")
        c.execute("CREATE TEMP VIEW notifications AS SELECT n.* FROM main.notifications n WHERE NOT EXISTS(SELECT 1 FROM main.purchase_requisitions hidden WHERE hidden.id NOT IN(SELECT id FROM purchase_requisitions) AND instr(n.message,hidden.pr_number)>0)")
        return [dict(row) for row in c.execute(sql,parameters)]


def default_payment_terms():
    company=fetch_one('SELECT default_payment_terms FROM company WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 1') or {}
    if company.get('default_payment_terms') is not None:return company['default_payment_terms']
    row=fetch_one("SELECT value FROM settings WHERE key IN('default_payment_terms','payment_terms') ORDER BY CASE key WHEN 'default_payment_terms' THEN 0 ELSE 1 END LIMIT 1") or {}
    return row.get('value') or ''


def plan_allocations(c,pr_ids,item_id,base_quantity,reserved):
    remaining=base_quantity;result=[]
    for line in allocation_candidates(c,pr_ids,item_id):
        factor=float(line.get('base_quantity') or line['quantity'])/float(line['quantity'])
        available=max(0,line['available']-reserved.get(line['id'],0))
        assigned=min(remaining,available*factor)/factor
        if assigned>1e-8:
            result.append((line['pr_id'],line['id'],item_id,assigned))
            reserved[line['id']]=reserved.get(line['id'],0)+assigned
            remaining-=assigned*factor
        if remaining<=1e-8:break
    if remaining>1e-8:raise HTTPException(409,f'PO quantity exceeds remaining approved PR quantity for item {item_id}')
    return result
