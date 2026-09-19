import shutil
import sqlite3
import pytest
from fastapi.testclient import TestClient
from app import database
from app.main import app
from app.security import sign_token

@pytest.mark.parametrize('inspection,factor,delivered,accepted,damaged,short',[(False,1,10,8,2,0),(True,1,10,10,2,0),(True,1000,10,10,2,0),(False,1,6,6,0,4)])
def test_partial_receipt_stays_open_until_usable_replacements(tmp_path,monkeypatch,inspection,factor,delivered,accepted,damaged,short):
    path=tmp_path/'receipts.db';shutil.copy2(database.DB_PATH,path);monkeypatch.setattr(database,'DB_PATH',path)
    with database.transaction() as c:
        user=c.execute("SELECT id FROM users WHERE role='SupplyChainManager' LIMIT 1").fetchone()['id']
        supplier=c.execute('SELECT id FROM suppliers LIMIT 1').fetchone()['id']
        item=c.execute('SELECT id FROM items LIMIT 1').fetchone()['id']
        warehouse=c.execute('SELECT id FROM warehouses ORDER BY id LIMIT 1').fetchone()['id']
        employee=c.execute("SELECT id FROM employees WHERE warehouse_id=? AND status='Active' LIMIT 1",(warehouse,)).fetchone()['id']
        c.execute("UPDATE items SET inspection_required_yn=?,batch_control_yn=0,expiry_control_yn=0,uom=?,purchase_uom=?,issue_uom=?,conversion_factor=? WHERE id=?",(int(inspection),'KG' if factor>1 else 'EA','TON' if factor>1 else 'EA','KG' if factor>1 else 'EA',factor,item))
    client=TestClient(app);headers={'Authorization':'Bearer '+sign_token({'id':user})}
    def call(method,path,body=None):
        return client.request(method,'/api'+path,json=body,headers=headers)
    result=call('POST','/procurement/pos',{'supplier_id':supplier,'delivery_warehouse_id':warehouse,'items':[{'item_id':item,'quantity':10,'price':20,'tax':0}]})
    assert result.status_code==201,result.text
    pid=result.json()['id']
    def progress():
        result=call('GET',f'/procurement/pos/{pid}');assert result.status_code==200,result.text;return result.json()
    def receive(qty,accepted,rejected=0,damage=0,shortage=0):
        return call('POST','/warehouse/grns',{'po_id':pid,'warehouse_id':warehouse,'received_for_employee_id':employee,'items':[{'item_id':item,'quantity_received':qty,'accepted_qty':accepted,'rejected_qty':rejected,'damaged_qty':damage,'short_qty':shortage,'receiving_issue_reason':'Damaged goods' if damage else 'Supplier backorder' if shortage else '', 'receiving_notes':'Receipt QA evidence'}]})
    def pending():return [r for r in call('GET','/warehouse/receiving-queue').json() if r['item_id']==item]
    def putaway():
        for hold in pending():
            if hold['inventory_status']!='PUT_AWAY_PENDING':continue
            r=call('POST','/masters/putaway/recommend',{'item_id':item,'warehouse_id':warehouse,'quantity':hold['quantity'],'inventory_status':'AVAILABLE','source_table':'inventory_quarantine','source_id':hold['id']});assert r.status_code==200,r.text
            r=call('PUT',f"/masters/putaway/{r.json()['recommendation_id']}/confirm",{});assert r.status_code==200,r.text
    grn=receive(delivered,accepted,delivered-accepted,0 if inspection else damaged,short);assert grn.status_code==201,grn.text
    doc=progress();assert doc['status']=='Partially Received' and not doc['fully_received']
    assert doc['receipt_lines'][0]['accepted_usable_quantity']==0
    # Reconcile a historical PO incorrectly closed before usable put-away.
    with database.transaction() as c:
        c.execute("UPDATE purchase_orders SET status='Closed' WHERE id=?",(pid,))
        c.execute("DELETE FROM settings WHERE key='po_usable_receipt_status_v1'")
    from app.pr_schema import ensure_pr_workflow_schema
    ensure_pr_workflow_schema()
    with database.connect() as c:
        assert c.execute('SELECT status FROM purchase_orders WHERE id=?',(pid,)).fetchone()['status']=='Partially Received'
    printed=call('POST',f'/procurement/pos/{pid}/print',{})
    assert printed.status_code==200,printed.text
    assert progress()['status']=='Partially Received'
    if inspection:
        assert receive(1,1).status_code==409 # Stock awaiting inspection is reserved, not ordered twice.
        hold=next(r for r in pending() if r['inventory_status']=='INSPECTION_PENDING')
        r=call('POST','/warehouse/inspections',{'hold_id':hold['id'],'inspected_quantity':delivered*factor,'passed_quantity':(delivered-damaged)*factor,'failed_quantity':damaged*factor,'damaged_quantity':damaged*factor,'issue_reason':'Damaged goods','remarks':'Damage verified during inspection'});assert r.status_code==201,r.text
    putaway();doc=progress();line=doc['receipt_lines'][0];usable=delivered-damaged if inspection else accepted
    assert line['physically_delivered_quantity']==delivered
    assert line['accepted_usable_quantity']==usable
    assert line['outstanding_quantity']==10-usable
    assert line['receivable_quantity']==10-usable
    assert line['damaged_quantity']==damaged and line['rejected_quantity']==damaged
    assert line['short_quantity']==short
    assert doc['status']=='Partially Received'
    evidence=doc['receipts'][0];assert evidence['grn_number']==grn.json()['grn_number'] and evidence['warehouse'] and evidence['receipt_date'] and evidence['notes']
    listed=next(r for r in call('GET','/procurement/pos').json() if r['id']==pid);assert listed['status']=='Partially Received'
    # Reports must agree with the PO's usable receipt calculation.
    po_number=doc['po_number']
    for report in ['open-po-commitments','po-vs-grn','po-delivery-performance']:
        response=call('GET','/reports/'+report);assert response.status_code==200,response.text
        row=next(x for x in response.json() if x['po_number']==po_number)
        if report=='po-vs-grn':
            assert row['physically_delivered_quantity']==delivered
            assert row['accepted_usable_quantity']==usable
        else:assert row['received_quantity']==usable
        if report!='po-delivery-performance':assert row['outstanding_quantity']==10-usable
        if report=='open-po-commitments':assert row['outstanding_value']==(10-usable)*20
    replacement=receive(10-usable,10-usable);assert replacement.status_code==201,replacement.text
    if inspection:
        hold=next(r for r in pending() if r['inventory_status']=='INSPECTION_PENDING')
        r=call('POST','/warehouse/inspections',{'hold_id':hold['id'],'inspected_quantity':hold['quantity'],'passed_quantity':hold['quantity'],'failed_quantity':0});assert r.status_code==201,r.text
    putaway();doc=progress();assert doc['status']=='Closed' and doc['fully_received']
    assert doc['receipt_lines'][0]['outstanding_quantity']==0
    assert doc['receipt_lines'][0]['accepted_usable_quantity']==10
    with database.transaction() as c:
        assert c.execute('SELECT status FROM purchase_orders WHERE id=?',(pid,)).fetchone()['status']=='Closed'
        if damaged:assert c.execute("SELECT SUM(quantity) FROM inventory_quarantine WHERE item_id=? AND inventory_status='REJECTED' AND released_at IS NULL",(item,)).fetchone()[0]==damaged*factor
        # Consuming usable stock does not undo successful historical receipt.
        c.execute('UPDATE inventory_layers SET quantity_remaining=0 WHERE item_id=?',(item,))
    assert progress()['fully_received']
