"""PR/RFQ/PO requirements: exercise real routes on disposable company databases."""
import shutil
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from app import database
from app.main import app
from app.security import sign_token
from app.replenishment import run_replenishment, _due


@pytest.fixture
def ctx(tmp_path,monkeypatch):
    path=tmp_path/'workflow.db';shutil.copy2(database.DB_PATH,path)
    monkeypatch.setattr(database,'DB_PATH',path)
    database.ensure_company_employee_schema()
    with database.transaction() as c:
        users={r['role']:dict(r) for r in c.execute('SELECT * FROM users ORDER BY id DESC')}
        item=c.execute("SELECT id FROM items WHERE item_code='TEST-ITEM-002'").fetchone()['id']
        supplier=c.execute('SELECT id FROM suppliers LIMIT 1').fetchone()['id']
        warehouses=[r['id'] for r in c.execute('SELECT id FROM warehouses ORDER BY id')]
    client=TestClient(app)
    def call(role,method,url,body=None):
        return client.request(method,'/api'+url,headers={'Authorization':'Bearer '+sign_token({'id':users[role]['id']})},json=body)
    return SimpleNamespace(path=path,users=users,item=item,supplier=supplier,warehouses=warehouses,call=call)


def new_pr(ctx,role='Storekeeper',qty=100,item=None,warehouse=None):
    user=ctx.users[role]
    response=ctx.call(role,'POST','/procurement/prs',{'requestor_employee_id':user['employee_id'],'department_id':1,'warehouse_id':warehouse or ctx.warehouses[0],'items':[{'item_id':item or ctx.item,'quantity':qty,'required_date':'2026-10-01','reason':'Production need'}]})
    assert response.status_code==201,response.text
    assert response.json()['status']=='Draft'
    return response.json()['id']


def submit(ctx,pid,role='Storekeeper'):
    r=ctx.call(role,'POST',f'/procurement/prs/{pid}/submit-to-procurement');assert r.status_code==200,r.text
    assert r.json()['status']=='Submitted'


def approve(ctx,pid,qty=None,role='SupplyChainManager'):
    doc=ctx.call(role,'GET',f'/procurement/prs/{pid}').json()
    lines=[{'id':line['id'],'approved_quantity':line['quantity'] if qty is None else qty,'adjustment_reason':'Demand reviewed' if qty is not None else ''} for line in doc['items']]
    response=ctx.call(role,'PUT',f'/procurement/prs/{pid}/review',{'items':lines});assert response.status_code==200,response.text
    response=ctx.call(role,'PUT',f'/procurement/prs/{pid}/status',{'status':'Approved'});assert response.status_code==200,response.text


def po(ctx,pid,qty,**extra):
    return ctx.call('SupplyChainManager','POST','/procurement/pos',{'supplier_id':ctx.supplier,'delivery_warehouse_id':ctx.warehouses[0],'pr_ids':[pid],'items':[{'item_id':ctx.item,'quantity':qty,'price':1,'tax':0}],**extra})


def test_companywide_draft_visibility_submission_and_quantity_lock(ctx):
    pid=new_pr(ctx)
    with database.transaction() as c:
        number=c.execute('SELECT pr_number FROM purchase_requisitions WHERE id=?',(pid,)).fetchone()['pr_number']
        c.execute("INSERT INTO notifications(type,message)VALUES('PR',?)",('Please review '+number,))
        assert c.execute("SELECT COUNT(*) FROM approval_log WHERE document_type='PR' AND document_id=?",(pid,)).fetchone()[0]==0
    for role in ['PurchaseOfficer','PurchaseManager','SupplyChainManager']:
        assert pid in [x['id'] for x in ctx.call(role,'GET','/procurement/prs').json()]
        for url in [f'/procurement/prs/{pid}',f'/procurement/prs/{pid}/approval-history',f'/attachments/PR/{pid}']:
            assert ctx.call(role,'GET',url).status_code==200
        for url in ['/reports/pr-register','/dashboard/tasks','/dashboard/notifications','/reports/approval-governance']:
            response=ctx.call(role,'GET',url)
            assert response.status_code in (200,403),response.text
            if url=='/reports/pr-register' and response.status_code==200:assert number in response.text
        assert po(ctx,pid,1).status_code in (404,409)
    submit(ctx,pid)
    doc=ctx.call('PurchaseOfficer','GET',f'/procurement/prs/{pid}').json()
    assert doc['warehouse_submitted_by']==ctx.users['Storekeeper']['id'] and doc['warehouse_submitted_at']
    assert doc['status']=='Submitted' and not doc['eligible_for_po']
    response=ctx.call('Storekeeper','PUT',f'/procurement/prs/{pid}',{'items':[{'item_id':ctx.item,'quantity':3}]})
    assert response.status_code==409
    assert ctx.call('Storekeeper','PUT',f'/procurement/prs/{pid}/status',{'status':'Approved'}).status_code==403
    assert ctx.call('SupplyChainManager','PUT',f'/procurement/prs/{pid}/status',{'status':'Approved'}).status_code==409


def test_review_preserves_request_and_enables_both_routes(ctx):
    pid=new_pr(ctx);submit(ctx,pid)
    approve(ctx,pid,80)
    doc=ctx.call('PurchaseOfficer','GET',f'/procurement/prs/{pid}').json();line=doc['items'][0]
    assert (line['quantity'],line['warehouse_requested_quantity'],line['approved_quantity'],line['procurement_quantity_variance'],line['remaining_quantity'])==(100,100,80,-20,80)
    assert line['procurement_adjustment_reason']=='Demand reviewed' and line['procurement_adjusted_by'] and line['procurement_adjusted_at']
    assert doc['approved_by'] and doc['approved_at'] and doc['reviewed_at']
    assert doc['eligible_for_rfq'] and doc['eligible_for_po'] and doc['approval_valid']
    assert pid in [x['id'] for x in ctx.call('PurchaseOfficer','GET','/procurement/eligible-prs').json()]
    rfq=ctx.call('PurchaseOfficer','POST','/procurement/rfqs',{'pr_id':pid,'supplier_ids':[ctx.supplier]});assert rfq.status_code==201,rfq.text
    assert ctx.call('PurchaseOfficer','GET',f'/procurement/prs/{pid}').json()['items'][0]['remaining_quantity']==80
    assert po(ctx,pid,81).status_code==409
    assert po(ctx,pid,30).status_code==201
    doc=ctx.call('PurchaseOfficer','GET',f'/procurement/prs/{pid}').json()
    assert doc['status']=='Partially Ordered' and doc['eligible_for_rfq'] and doc['items'][0]['remaining_quantity']==50
    assert ctx.call('SupplyChainManager','PUT',f'/procurement/prs/{pid}/status',{'status':'Closed'}).status_code==409
    assert po(ctx,pid,50).status_code==201
    doc=ctx.call('PurchaseOfficer','GET',f'/procurement/prs/{pid}').json()
    assert doc['status']=='Closed' and doc['closed_at'] and not doc['eligible_for_po']


def test_cancelled_po_reopens_approved_balance(ctx):
    pid=new_pr(ctx,qty=10);submit(ctx,pid);approve(ctx,pid)
    order=po(ctx,pid,10);assert order.status_code==201,order.text
    cancelled=ctx.call('SupplyChainManager','PUT',f"/procurement/pos/{order.json()['id']}/cancel",{'reason':'Supplier cannot deliver'})
    assert cancelled.status_code==200,cancelled.text
    doc=ctx.call('PurchaseOfficer','GET',f'/procurement/prs/{pid}').json()
    assert doc['status']=='Approved' and doc['eligible_for_po'] and doc['items'][0]['remaining_quantity']==10 and doc['closed_at'] is None


def test_procurement_creation_requires_review_and_separate_approver(ctx):
    pid=new_pr(ctx,'PurchaseOfficer',10);submit(ctx,pid,'PurchaseOfficer')
    doc=ctx.call('PurchaseOfficer','GET',f'/procurement/prs/{pid}').json()
    assert not doc['eligible_for_po']
    reviewed=ctx.call('PurchaseOfficer','PUT',f'/procurement/prs/{pid}/review',{'items':[{'id':doc['items'][0]['id'],'approved_quantity':10}]})
    assert reviewed.status_code==200,reviewed.text
    assert ctx.call('PurchaseOfficer','PUT',f'/procurement/prs/{pid}/status',{'status':'Approved'}).status_code==403
    approve(ctx,pid,role='PurchaseManager')


def test_quantity_adjustment_reason_and_line_coverage_required(ctx):
    pid=new_pr(ctx);submit(ctx,pid)
    line=ctx.call('PurchaseManager','GET',f'/procurement/prs/{pid}').json()['items'][0]
    for items in [[],[{'id':line['id'],'approved_quantity':80}],[{'id':line['id'],'approved_quantity':-1,'adjustment_reason':'Invalid'}]]:
        assert ctx.call('PurchaseManager','PUT',f'/procurement/prs/{pid}/review',{'items':items}).status_code==400


def test_multiwarehouse_access_and_po_delivery_match(ctx):
    pid=new_pr(ctx)
    with database.transaction(immediate=True) as c:
        other=ctx.users['WarehouseSupervisor']['id'];c.execute('UPDATE users SET warehouse_id=? WHERE id=?',(ctx.warehouses[1],other));c.execute('DELETE FROM user_warehouse_assignments WHERE user_id=?',(other,))
    assert pid not in {row['id'] for row in ctx.call('WarehouseSupervisor','GET','/procurement/prs').json()}
    assert ctx.call('WarehouseSupervisor','GET',f'/procurement/prs/{pid}').status_code==403
    assert ctx.call('WarehouseSupervisor','GET',f'/attachments/PR/{pid}').status_code==403
    assert new_pr(ctx,warehouse=ctx.warehouses[0])
    response=ctx.call('Storekeeper','POST','/procurement/prs',{'warehouse_id':ctx.warehouses[1],'items':[{'item_id':ctx.item,'quantity':1}]})
    assert response.status_code==403
    submit(ctx,pid);approve(ctx,pid)
    assert ctx.call('WarehouseSupervisor','GET',f'/procurement/prs/{pid}').status_code==403
    assert ctx.call('WarehouseSupervisor','PUT',f'/procurement/prs/{pid}/status',{'status':'Closed'}).status_code==403
    assert po(ctx,pid,1,delivery_warehouse_id=ctx.warehouses[1]).status_code==409


def test_rfq_defaults_are_tenant_settings_and_existing_snapshot(ctx):
    pid=new_pr(ctx);submit(ctx,pid);approve(ctx,pid)
    assert ctx.call('SupplyChainManager','PUT','/settings/company',{'default_payment_terms':'Net 45 days'}).status_code==200
    assert ctx.call('PurchaseOfficer','GET','/procurement/rfq-defaults').json()['payment_terms']=='Net 45 days'
    response=ctx.call('PurchaseOfficer','POST','/procurement/rfqs',{'pr_id':pid,'supplier_ids':[ctx.supplier]});assert response.status_code==201,response.text
    rid=response.json()['id']
    detail=ctx.call('PurchaseOfficer','GET',f'/procurement/rfqs/{rid}').json()
    assert detail['company']['default_payment_terms']=='Net 45 days'
    assert detail['company']['name']
    assert 'delivery_warehouse_name' in detail
    assert ctx.call('SupplyChainManager','PUT','/settings/company',{'default_payment_terms':'Net 60 days'}).status_code==200
    assert ctx.call('PurchaseOfficer','GET',f'/procurement/rfqs/{rid}').json()['payment_terms']=='Net 45 days'
    edited=ctx.call('PurchaseOfficer','PUT',f'/procurement/rfqs/{rid}',{'notes':'Existing commercial terms preserved'})
    assert edited.status_code==200,edited.text
    assert ctx.call('PurchaseOfficer','GET',f'/procurement/rfqs/{rid}').json()['payment_terms']=='Net 45 days'


def test_automatic_review_keeps_cycle_and_independent_warehouse(ctx):
    with database.transaction(immediate=True) as c:
        c.execute('UPDATE items SET min_stock=5,max_stock=20,reorder_level=20,default_warehouse_id=? WHERE id=?',(ctx.warehouses[0],ctx.item))
        c.execute('INSERT OR IGNORE INTO item_warehouse_settings(item_id,warehouse_id)VALUES(?,?)',(ctx.item,ctx.warehouses[1]))
    draft=ctx.call('Storekeeper','POST','/warehouse/replenishment/check',{'warehouse_id':ctx.warehouses[0]})
    assert draft.status_code==201,draft.text
    detail=ctx.call('Storekeeper','GET',f"/warehouse/replenishment/drafts/{draft.json()['id']}").json()
    line=next(x for x in detail['lines'] if x['item_id']==ctx.item)
    payload=[{**row,'reviewed_qty':8,'adjustment_reason':'Reduced demand'} if row['id']==line['id'] else row for row in detail['lines']]
    reviewed=ctx.call('Storekeeper','PUT',f"/warehouse/replenishment/drafts/{detail['id']}/review",{'lines':payload})
    assert reviewed.status_code==200,reviewed.text
    created=ctx.call('Storekeeper','POST',f"/warehouse/replenishment/drafts/{detail['id']}/create-pr")
    assert created.status_code==201,created.text
    pid=created.json()['id']
    assert ctx.call('PurchaseOfficer','GET',f'/procurement/prs/{pid}').status_code==200
    doc=ctx.call('Storekeeper','GET',f'/procurement/prs/{pid}').json();line=doc['items'][0]
    doc=ctx.call('Storekeeper','GET',f'/procurement/prs/{pid}').json();assert doc['items'][0]['recommended_base_quantity']==20
    submit(ctx,pid);approve(ctx,pid)


def test_automatic_pr_allows_audited_zero_line_and_excludes_from_sourcing(ctx):
    with database.transaction(immediate=True) as c:
        c.execute('UPDATE items SET min_stock=5,max_stock=20,reorder_level=20,default_warehouse_id=? WHERE id=?',(ctx.warehouses[0],ctx.item))
        second=c.execute("""INSERT INTO items(item_code,description,uom,purchase_uom,conversion_factor,min_stock,max_stock,reorder_level,standard_cost,default_warehouse_id,active_yn)
          VALUES('AUTO-ZERO-2','Second auto replenishment item','EA','EA',1,5,12,12,3,?,1)""",(ctx.warehouses[0],)).lastrowid
    draft=ctx.call('Storekeeper','POST','/warehouse/replenishment/check',{'warehouse_id':ctx.warehouses[0]})
    assert draft.status_code==201,draft.text
    detail=ctx.call('Storekeeper','GET',f"/warehouse/replenishment/drafts/{draft.json()['id']}").json()
    zero_line=next(line for line in detail['lines'] if line['item_id']==ctx.item)
    positive_line=next(line for line in detail['lines'] if line['item_id']==second)
    missing_payload=[
        {**line,'reviewed_qty':0,'adjustment_reason':''} if line['id']==zero_line['id']
        else ({**line,'reviewed_qty':line['reviewed_qty'],'adjustment_reason':line.get('adjustment_reason') or ''} if line['id']==positive_line['id'] else {**line,'reviewed_qty':0,'adjustment_reason':'Not required for this PR'})
        for line in detail['lines']
    ]
    missing_reason=ctx.call('Storekeeper','PUT',f"/warehouse/replenishment/drafts/{detail['id']}/review",{'lines':missing_payload})
    assert missing_reason.status_code==400
    edited_payload=[
        {**line,'reviewed_qty':0,'adjustment_reason':'Stock found'} if line['id']==zero_line['id']
        else ({**line,'reviewed_qty':line['reviewed_qty'],'adjustment_reason':line.get('adjustment_reason') or ''} if line['id']==positive_line['id'] else {**line,'reviewed_qty':0,'adjustment_reason':'Not required for this PR'})
        for line in detail['lines']
    ]
    edited=ctx.call('Storekeeper','PUT',f"/warehouse/replenishment/drafts/{detail['id']}/review",{'lines':edited_payload})
    assert edited.status_code==200,edited.text
    created=ctx.call('Storekeeper','POST',f"/warehouse/replenishment/drafts/{detail['id']}/create-pr")
    assert created.status_code==201,created.text
    pid=created.json()['id']
    doc=ctx.call('Storekeeper','GET',f'/procurement/prs/{pid}').json()
    assert {line['item_id'] for line in doc['items']}=={second}
    submit(ctx,pid)
    doc=ctx.call('SupplyChainManager','GET',f'/procurement/prs/{pid}').json()
    review=[{'id':line['id'],'approved_quantity':line['quantity'],'adjustment_reason':''} for line in doc['items']]
    assert ctx.call('SupplyChainManager','PUT',f'/procurement/prs/{pid}/review',{'items':review}).status_code==200
    assert ctx.call('SupplyChainManager','PUT',f'/procurement/prs/{pid}/status',{'status':'Approved'}).status_code==200
    source=ctx.call('PurchaseOfficer','GET',f'/procurement/prs/{pid}/rfq-items').json()
    assert [line['item_id'] for line in source]==[second]
    assert ctx.call('PurchaseOfficer','POST','/procurement/rfqs',{'pr_id':pid,'supplier_ids':[ctx.supplier]}).status_code==201


def test_duplicate_po_lines_cannot_overallocate(ctx):
    pid=new_pr(ctx,qty=10);submit(ctx,pid);approve(ctx,pid)
    response=po(ctx,pid,1,items=[{'item_id':ctx.item,'quantity':6,'price':1},{'item_id':ctx.item,'quantity':6,'price':1}])
    assert response.status_code==409
    assert ctx.call('PurchaseOfficer','GET',f'/procurement/prs/{pid}').json()['items'][0]['remaining_quantity']==10


def test_schedule_respects_operating_end_and_configured_days():
    wh={'time_zone':'Asia/Riyadh','replenishment_days_json':'[0,3]','operating_days_json':'[0,1,2,3,4]','operation_24h_yn':0,'operating_start_time':'06:00','operating_end_time':'17:00'}
    assert _due(wh,datetime(2026,9,7,3,0,tzinfo=timezone.utc))[0]
    assert not _due(wh,datetime(2026,9,7,15,0,tzinfo=timezone.utc))[0]
    assert not _due(wh,datetime(2026,9,8,3,0,tzinfo=timezone.utc))[0]
    assert _due({**wh,'operation_24h_yn':1},datetime(2026,9,6,21,0,tzinfo=timezone.utc))[0]


def test_migration_is_idempotent_and_preserves_foreign_keys(ctx):
    pid=new_pr(ctx)
    database.ensure_company_employee_schema();database.ensure_company_employee_schema()
    with sqlite3.connect(ctx.path) as c:
        assert c.execute('SELECT status FROM purchase_requisitions WHERE id=?',(pid,)).fetchone()[0]=='Draft'
        assert c.execute('PRAGMA foreign_key_check').fetchall()==[]


def test_rfq_snapshots_only_remaining_balance_and_converts_award(ctx):
    pid=new_pr(ctx,qty=100);submit(ctx,pid);approve(ctx,pid,80)
    assert po(ctx,pid,30).status_code==201
    response=ctx.call('PurchaseOfficer','POST','/procurement/rfqs',{'pr_id':pid,'supplier_ids':[ctx.supplier],'closing_date':'2099-12-01'})
    assert response.status_code==201,response.text
    rid=response.json()['id']
    assert ctx.call('PurchaseOfficer','PUT',f'/procurement/rfqs/{rid}',{'delivery_warehouse_id':ctx.warehouses[1]}).status_code==409
    assert ctx.call('PurchaseOfficer','GET',f'/procurement/rfqs/{rid}').json()['items'][0]['quantity']==50
    assert ctx.call('PurchaseOfficer','PUT',f'/procurement/rfqs/{rid}/issue',{}).status_code==200
    payload={'supplier_id':ctx.supplier,'item_id':ctx.item,'quoted_quantity':51,'price':1}
    assert ctx.call('PurchaseOfficer','POST',f'/procurement/rfqs/{rid}/quotations',payload).status_code==409
    quote=ctx.call('PurchaseOfficer','POST',f'/procurement/rfqs/{rid}/quotations',{**payload,'quoted_quantity':50})
    assert quote.status_code==201,quote.text
    comparison=ctx.call('PurchaseOfficer','GET',f'/procurement/rfqs/{rid}/comparison')
    assert comparison.status_code==200,comparison.text
    assert comparison.json()[0]['requested_quantity']==50
    award=ctx.call('PurchaseOfficer','POST',f'/procurement/rfqs/{rid}/awards',{'quotation_id':quote.json()['id'],'awarded_quantity':50,'recommendation_reason':'Meets requirements'})
    assert award.status_code==201,award.text
    decision=ctx.call('SupplyChainManager','PUT',f"/procurement/rfq-awards/{award.json()['id']}/decision",{'decision':'Approved'})
    assert decision.status_code==200,decision.text
    converted=ctx.call('SupplyChainManager','POST',f'/procurement/rfqs/{rid}/create-purchase-orders')
    assert converted.status_code==201,converted.text
    assert ctx.call('PurchaseOfficer','GET',f'/procurement/prs/{pid}').json()['status']=='Closed'
    assert ctx.call('PurchaseOfficer','GET',f'/procurement/rfqs/{rid}').json()['items'][0]['quantity']==50


def test_multi_line_and_uom_allocations(ctx):
    with database.transaction() as c:
        cement=c.execute("SELECT id FROM items WHERE item_code='TEST-ITEM-001'").fetchone()['id']
    pid=new_pr(ctx,qty=100,item=cement)
    edited=ctx.call('Storekeeper','PUT',f'/procurement/prs/{pid}',{'items':[{'item_id':cement,'quantity':100,'transaction_uom':'KG'},{'item_id':ctx.item,'quantity':5}]})
    assert edited.status_code==200,edited.text
    submit(ctx,pid);approve(ctx,pid)
    first=po(ctx,pid,1,items=[{'item_id':cement,'quantity':1,'transaction_uom':'BAG','price':1}])
    assert first.status_code==201,first.text
    doc=ctx.call('PurchaseOfficer','GET',f'/procurement/prs/{pid}').json()
    assert doc['status']=='Partially Ordered'
    assert [x['remaining_quantity'] for x in doc['items']]==[50,5]
    rfq=ctx.call('PurchaseOfficer','POST','/procurement/rfqs',{'pr_id':pid,'supplier_ids':[ctx.supplier]})
    assert rfq.status_code==201,rfq.text
    line=ctx.call('PurchaseOfficer','GET',f"/procurement/rfqs/{rfq.json()['id']}").json()['items'][0]
    assert line['quantity']==1 and line['transaction_uom']=='BAG' and line['conversion_factor_used']==50
    assert po(ctx,pid,5).status_code==201
    assert ctx.call('PurchaseOfficer','GET',f'/procurement/prs/{pid}').json()['status']=='Partially Ordered'
    last=po(ctx,pid,1,items=[{'item_id':cement,'quantity':1,'price':1}])
    assert last.status_code==201,last.text
    assert ctx.call('PurchaseOfficer','GET',f'/procurement/prs/{pid}').json()['status']=='Closed'


def test_historical_status_reconciliation_preserves_evidence(ctx):
    pid=new_pr(ctx,qty=10);submit(ctx,pid);approve(ctx,pid)
    assert po(ctx,pid,4).status_code==201
    stale=new_pr(ctx,'PurchaseOfficer',10)
    with database.transaction() as c:
        c.execute("DELETE FROM settings WHERE key='pr_history_reconciliation_v2'")
        c.execute("UPDATE purchase_requisitions SET status='Closed',warehouse_submitted_by=NULL,warehouse_submitted_at=NULL WHERE id=?",(pid,))
        c.execute("UPDATE purchase_requisitions SET status='Approved' WHERE id=?",(stale,))
    database.ensure_company_employee_schema()
    doc=ctx.call('PurchaseOfficer','GET',f'/procurement/prs/{pid}').json()
    assert doc['status']=='Partially Ordered' and doc['eligible_for_po']
    assert doc['legacy_procurement_handoff_yn']==1 and doc['warehouse_submitted_at'] is None
    doc=ctx.call('PurchaseOfficer','GET',f'/procurement/prs/{stale}').json()
    assert doc['status']=='Submitted' and not doc['eligible_for_po'] and doc['approved_at'] is None
    approve(ctx,stale)
    assert ctx.call('PurchaseOfficer','GET',f'/procurement/prs/{stale}').json()['eligible_for_po']


def test_rfq_item_selection_and_draft_revision(ctx):
    with database.transaction() as c:
        second=c.execute("SELECT id FROM items WHERE item_code='TEST-ITEM-001'").fetchone()['id']
        supplier2=c.execute("INSERT INTO suppliers(supplier_code,name,active_yn,blocked_yn)VALUES('RFQ-SECOND','Second RFQ Supplier',1,0)").lastrowid
    pid=new_pr(ctx,qty=10)
    edited=ctx.call('Storekeeper','PUT',f'/procurement/prs/{pid}',{'items':[{'item_id':ctx.item,'quantity':10},{'item_id':second,'quantity':2}]})
    assert edited.status_code==200,edited.text
    submit(ctx,pid);approve(ctx,pid)
    source=ctx.call('PurchaseOfficer','GET',f'/procurement/prs/{pid}/rfq-items')
    assert source.status_code==200,source.text
    first=next(x for x in source.json() if x['item_id']==ctx.item)
    other=next(x for x in source.json() if x['item_id']==second)
    payload={'pr_id':pid,'supplier_ids':[ctx.supplier],'items':[{'pr_item_id':first['pr_item_id'],'quantity':4}]}
    for invalid in ([],[{'pr_item_id':first['pr_item_id'],'quantity':11}],[{'pr_item_id':999999,'quantity':1}]):
        response=ctx.call('PurchaseOfficer','POST','/procurement/rfqs',{**payload,'items':invalid})
        assert response.status_code in (400,409),response.text
    created=ctx.call('PurchaseOfficer','POST','/procurement/rfqs',payload);assert created.status_code==201,created.text
    rid=created.json()['id'];url=f'/procurement/rfqs/{rid}'
    doc=ctx.call('PurchaseOfficer','GET',url).json()
    assert len(doc['items'])==1 and doc['items'][0]['quantity']==4
    changed=ctx.call('PurchaseOfficer','PUT',url,{'supplier_ids':[supplier2],'closing_date':'2099-12-01','items':[{'pr_item_id':other['pr_item_id'],'quantity':1}]})
    assert changed.status_code==200,changed.text
    assert changed.json()['items'][0]['item_id']==second and changed.json()['items'][0]['quantity']==1
    assert [x['supplier_id'] for x in changed.json()['suppliers']]==[supplier2]
    assert ctx.call('PurchaseOfficer','PUT',url+'/issue',{}).status_code==200
    assert ctx.call('PurchaseOfficer','PUT',url,{'items':payload['items']}).status_code==409
    excluded=ctx.call('PurchaseOfficer','POST',url+'/quotations',{'supplier_id':supplier2,'item_id':ctx.item,'quoted_quantity':1,'price':1})
    assert excluded.status_code in (400,409),excluded.text
    valid=ctx.call('PurchaseOfficer','POST',url+'/quotations',{'supplier_id':supplier2,'item_id':second,'quoted_quantity':1,'price':1})
    assert valid.status_code==201,valid.text


def test_rfq_issue_rechecks_live_pr_balance(ctx):
    pid=new_pr(ctx,qty=10);submit(ctx,pid);approve(ctx,pid)
    rfq=ctx.call('PurchaseOfficer','POST','/procurement/rfqs',{'pr_id':pid,'supplier_ids':[ctx.supplier],'closing_date':'2099-12-01'})
    assert rfq.status_code==201,rfq.text
    assert po(ctx,pid,5).status_code==201
    issued=ctx.call('PurchaseOfficer','PUT',f"/procurement/rfqs/{rfq.json()['id']}/issue",{})
    assert issued.status_code==409 and 'review the draft' in issued.text


def test_award_evidence_upload_enables_controlled_self_approval(ctx,tmp_path,monkeypatch):
    from app.routes import attachments
    documents=tmp_path/'documents';documents.mkdir();monkeypatch.setattr(attachments,'DOCS',documents)
    pid=new_pr(ctx,qty=10);submit(ctx,pid);approve(ctx,pid)
    rfq=ctx.call('SupplyChainManager','POST','/procurement/rfqs',{'pr_id':pid,'supplier_ids':[ctx.supplier],'closing_date':'2099-12-01'}).json()
    rid=rfq['id']
    assert ctx.call('SupplyChainManager','PUT',f'/procurement/rfqs/{rid}/issue',{}).status_code==200
    quote=ctx.call('SupplyChainManager','POST',f'/procurement/rfqs/{rid}/quotations',{'supplier_id':ctx.supplier,'item_id':ctx.item,'quoted_quantity':10,'price':1})
    assert quote.status_code==201,quote.text
    qid=quote.json()['id']
    award=ctx.call('SupplyChainManager','POST',f'/procurement/rfqs/{rid}/awards',{'quotation_id':qid,'awarded_quantity':10,'recommendation_reason':'Lowest evaluated cost'})
    assert award.status_code==201,award.text
    aid=award.json()['id'];decision={'decision':'Approved','external_approval_reference':'TEST-APPROVAL','external_approved_by':'Test Management','external_approval_date':'2026-09-07'}
    blocked=ctx.call('SupplyChainManager','PUT',f'/procurement/rfq-awards/{aid}/decision',decision)
    assert blocked.status_code==409 and 'Upload' in blocked.text
    client=TestClient(app);headers={'Authorization':'Bearer '+sign_token({'id':ctx.users['SupplyChainManager']['id']})}
    from pypdf import PdfWriter
    from io import BytesIO
    output=BytesIO();writer=PdfWriter();writer.add_blank_page(width=300,height=300);writer.write(output);pdf=output.getvalue()
    ids=[]
    for kind,document_id in [('RFQ',rid),('QUOTATION',qid),('AWARD',aid)]:
        uploaded=client.post(f'/api/attachments/{kind}/{document_id}',headers=headers,files={'file':('approval.pdf',pdf,'application/pdf')})
        assert uploaded.status_code==201,uploaded.text
        attachment_id=uploaded.json()['id'];ids.append(attachment_id)
        assert ctx.call('SupplyChainManager','GET',f'/attachments/{kind}/{document_id}').json()[0]['id']==attachment_id
        downloaded=client.get(f'/api/attachments/file/{attachment_id}',headers=headers)
        assert downloaded.status_code==200 and downloaded.content==pdf
    approved=ctx.call('SupplyChainManager','PUT',f'/procurement/rfq-awards/{aid}/decision',decision)
    assert approved.status_code==200,approved.text
    denied=client.post(f'/api/attachments/AWARD/{aid}',headers={'Authorization':'Bearer '+sign_token({'id':ctx.users['Storekeeper']['id']})},files={'file':('approval.pdf',pdf,'application/pdf')})
    assert denied.status_code==403
    database.ensure_company_employee_schema();database.ensure_company_employee_schema()
    with database.transaction() as c:
        assert c.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert c.execute('SELECT COUNT(*) FROM document_attachments WHERE id IN (?,?,?)',ids).fetchone()[0]==3


@pytest.mark.parametrize('currency,rate,price,external',[('SAR',1,20,True),('USD',4,5,True),('SAR',1,5,False)])
def test_rfq_po_uses_external_approval_above_scm_limit(ctx,tmp_path,monkeypatch,currency,rate,price,external):
    from app.routes import attachments
    docs=tmp_path/'evidence';docs.mkdir();monkeypatch.setattr(attachments,'DOCS',docs)
    pid=new_pr(ctx,qty=10);submit(ctx,pid);approve(ctx,pid)
    rfq=ctx.call('PurchaseOfficer','POST','/procurement/rfqs',{'pr_id':pid,'supplier_ids':[ctx.supplier],'closing_date':'2099-12-01'}).json();rid=rfq['id']
    assert ctx.call('PurchaseOfficer','PUT',f'/procurement/rfqs/{rid}/issue',{}).status_code==200
    quote=ctx.call('PurchaseOfficer','POST',f'/procurement/rfqs/{rid}/quotations',{'supplier_id':ctx.supplier,'item_id':ctx.item,'quoted_quantity':10,'price':price,'currency':currency})
    assert quote.status_code==201,quote.text
    award=ctx.call('PurchaseOfficer','POST',f'/procurement/rfqs/{rid}/awards',{'quotation_id':quote.json()['id'],'awarded_quantity':10,'recommendation_reason':'Lowest evaluated cost'})
    assert award.status_code==201,award.text
    assert ctx.call('SupplyChainManager','PUT',f"/procurement/rfq-awards/{award.json()['id']}/decision",{'decision':'Approved'}).status_code==200
    with database.transaction() as c:
        c.execute('UPDATE employees SET approval_limit=100 WHERE id=?',(ctx.users['SupplyChainManager']['employee_id'],))
        if currency!='SAR':c.execute("INSERT INTO exchange_rates(from_currency,to_currency,rate,source,effective_date,active_yn)VALUES(?,'SAR',?,'Test verified rate',date('now'),1)",(currency,rate))
    created=ctx.call('SupplyChainManager','POST',f'/procurement/rfqs/{rid}/create-purchase-orders')
    assert created.status_code==201,created.text
    order=created.json()['purchase_orders'][0];poid=order['id']
    assert order['status']=='PendingApproval' and order['external_approval_required']==external
    doc=ctx.call('SupplyChainManager','GET',f'/procurement/pos/{poid}').json()
    assert doc['status']=='PendingApproval' and doc['base_currency_amount']==10*price*rate
    assert bool(doc['management_approval_request_number'])==external
    printable=ctx.call('SupplyChainManager','GET',f'/procurement/pos/{poid}/document')
    assert printable.status_code==200,printable.text
    history=ctx.call('SupplyChainManager','GET',f'/procurement/pos/{poid}/approval-history').json()
    assert history[-1]['decision']=='Pending'
    assert history[-1]['approval_method']==('PENDING_EXTERNAL_APPROVAL' if external else 'PENDING_APPROVAL')
    if external:
        decision={'approval_ref_number':'TEST-MGMT','approval_person_name':'Test Management'}
        assert ctx.call('SupplyChainManager','PUT',f'/procurement/pos/{poid}/approve',decision).status_code==409
        client=TestClient(app);headers={'Authorization':'Bearer '+sign_token({'id':ctx.users['SupplyChainManager']['id']})}
        uploaded=client.post(f'/api/attachments/MANUAL_APPROVAL/{poid}',headers=headers,files={'file':('signed.pdf',b'%PDF-1.4\nTest signed evidence','application/pdf')})
        assert uploaded.status_code==201,uploaded.text
        approved=ctx.call('SupplyChainManager','PUT',f'/procurement/pos/{poid}/approve',decision)
        assert approved.status_code==200,approved.text
    duplicate=ctx.call('SupplyChainManager','POST',f'/procurement/rfqs/{rid}/create-purchase-orders')
    assert duplicate.status_code==409


def test_supplier_identity_flows_to_all_supplier_documents(ctx):
    with database.transaction() as c:
        c.execute("UPDATE suppliers SET name=?,address=?,contact_person=?,phone=?,email=? WHERE id=?",
                  ('Supplier Identity QA','42 Vendor Road','Vendor Contact','555-0199','vendor@example.test',ctx.supplier))
    pid=new_pr(ctx);submit(ctx,pid);approve(ctx,pid)
    created=po(ctx,pid,2);assert created.status_code==201,created.text
    poid=created.json()['id']
    rfq=ctx.call('SupplyChainManager','POST','/procurement/rfqs',{'pr_id':pid,'supplier_ids':[ctx.supplier]})
    assert rfq.status_code==201,rfq.text
    vendor=ctx.call('SupplyChainManager','GET',f"/procurement/rfqs/{rfq.json()['id']}").json()['suppliers'][0]
    assert vendor['name']=='Supplier Identity QA' and vendor['address']=='42 Vendor Road' and vendor['phone']=='555-0199'
    with database.transaction() as c:
        c.execute("UPDATE purchase_orders SET status='Approved' WHERE id=?",(poid,))
        gid=c.execute('INSERT INTO grns(grn_number,po_id,supplier_id,created_by)VALUES(?,?,?,?)',('GRN-SUPPLIER-QA',poid,ctx.supplier,ctx.users['Storekeeper']['id'])).lastrowid
        c.execute('INSERT INTO grn_items(grn_id,item_id,warehouse_id,quantity_received,accepted_qty,rejected_qty,unit_cost)VALUES(?,?,?,?,?,?,?)',(gid,ctx.item,ctx.warehouses[0],1,1,0,1))
        iid=c.execute('INSERT INTO invoices(invoice_number,po_id,supplier_id,invoice_total,created_by)VALUES(?,?,?,?,?)',('INV-SUPPLIER-QA',poid,ctx.supplier,2,ctx.users['SupplyChainManager']['id'])).lastrowid
    for path,key in [(f'/procurement/pos/{poid}/document','po'),(f'/procurement/pos/{poid}',None),(f'/warehouse/grns/{gid}',None),(f'/procurement/invoices/{iid}/payment-pack','invoice'),(f'/procurement/invoices/{iid}/three-way-match','invoice')]:
        response=ctx.call('SupplyChainManager','GET',path);assert response.status_code==200,response.text
        doc=response.json();doc=doc[key] if key else doc
        assert doc['supplier_name']=='Supplier Identity QA',path
        assert doc['supplier_address']=='42 Vendor Road',path
        assert doc['supplier_phone']=='555-0199',path
        assert doc['supplier_email']=='vendor@example.test',path
        assert doc['supplier_contact_person']=='Vendor Contact',path
        assert doc['supplier']['id']==ctx.supplier,path
    with database.transaction() as c:
        c.execute("UPDATE suppliers SET active_yn=0,deleted_at=datetime('now') WHERE id=?",(ctx.supplier,))
    historical=ctx.call('SupplyChainManager','GET',f'/procurement/pos/{poid}/document')
    assert historical.status_code==200
    assert historical.json()['po']['supplier_name']=='Supplier Identity QA'


def test_every_login_role_can_create_and_read_all_pr_sources(ctx):
    created={role:new_pr(ctx,role,qty=2) for role in ctx.users}
    with database.transaction() as c:
        c.execute('UPDATE items SET min_stock=5,max_stock=20,reorder_level=20,default_warehouse_id=? WHERE id=?',(ctx.warehouses[0],ctx.item))
    draft=ctx.call('Storekeeper','POST','/warehouse/replenishment/check',{'warehouse_id':ctx.warehouses[0]})
    detail=ctx.call('Storekeeper','GET',f"/warehouse/replenishment/drafts/{draft.json()['id']}").json()
    assert ctx.call('Storekeeper','PUT',f"/warehouse/replenishment/drafts/{detail['id']}/review",{'lines':detail['lines']}).status_code==200
    replenishment_pr=ctx.call('Storekeeper','POST',f"/warehouse/replenishment/drafts/{detail['id']}/create-pr").json()
    automatic=[replenishment_pr]
    expected=set(created.values())|{replenishment_pr['id']}
    report=ctx.call('SupplyChainManager','GET','/reports/pr-register')
    assert report.status_code==200,report.text
    for row in automatic:
        detail=ctx.call('SupplyChainManager','GET',f"/procurement/prs/{row['id']}").json()
        assert detail['pr_number'] in report.text
    for role in ctx.users:
        listed=ctx.call(role,'GET','/procurement/prs');assert listed.status_code==200,listed.text
        assert expected.issubset({row['id'] for row in listed.json()}),role
        for pid in expected:
            assert ctx.call(role,'GET',f'/procurement/prs/{pid}').status_code==200,role
            assert ctx.call(role,'GET',f'/attachments/PR/{pid}').status_code==200,role
    supervisor_pr=created['WarehouseSupervisor'];submit(ctx,supervisor_pr,'WarehouseSupervisor')
    assert ctx.call('WarehouseSupervisor','PUT',f'/procurement/prs/{supervisor_pr}/status',{'status':'Approved'}).status_code==403
    warehouse_pr=created['Storekeeper']
    assert ctx.call('PurchaseOfficer','PUT',f'/procurement/prs/{warehouse_pr}',{'items':[{'item_id':ctx.item,'quantity':2}]}).status_code==403
    assert ctx.call('PurchaseOfficer','POST',f'/procurement/prs/{warehouse_pr}/submit-to-procurement').status_code==403
    assert ctx.call('PurchaseOfficer','PUT',f'/procurement/prs/{warehouse_pr}/status',{'status':'Closed'}).status_code==403


def test_po_print_counter_migration_and_reprints(ctx):
    pid=new_pr(ctx);submit(ctx,pid);approve(ctx,pid)
    created=po(ctx,pid,2);assert created.status_code==201,created.text
    poid=created.json()['id']
    with database.transaction() as c:
        c.execute('ALTER TABLE purchase_orders DROP COLUMN print_count')
    from app.pr_schema import ensure_pr_workflow_schema
    ensure_pr_workflow_schema();ensure_pr_workflow_schema()
    for status,expected,count in [('PendingApproval',409,0),('Approved',200,1),('Printed',200,2),('Closed',200,3),('Cancelled',409,3)]:
        with database.transaction() as c:c.execute('UPDATE purchase_orders SET status=? WHERE id=?',(status,poid))
        response=ctx.call('SupplyChainManager','POST',f'/procurement/pos/{poid}/print')
        assert response.status_code==expected,response.text
        with database.transaction() as c:
            row=c.execute('SELECT status,print_count FROM purchase_orders WHERE id=?',(poid,)).fetchone()
            assert row['print_count']==count
            assert row['status']==('Printed' if status=='Approved' else status)
