import shutil
import sqlite3
from datetime import date,timedelta

from app import database
from app.approval_engine import evaluate_authority
from app.three_way_match import allowed_variance,classify,compare_component
from app.main import app
from app.security import sign_token
from fastapi.testclient import TestClient


def test_tolerance_uses_more_restrictive_percentage_or_absolute_limit():
    assert allowed_variance('80000',percentage='.5',absolute='250') == 250
    failed=compare_component('unit_price','80000','80300',{'percentage_tolerance':.5,'absolute_tolerance':250})
    assert failed['passed'] is False
    assert failed['failure_code']=='EXCEEDS_PRICE_TOLERANCE'
    passed=compare_component('rounding','100','100.01',{'absolute_tolerance':.01})
    assert classify([passed])=='MATCHED_WITHIN_TOLERANCE'


def test_employee_authority_is_effective_dated_and_employee_specific(tmp_path,monkeypatch):
    path=tmp_path/'authority.db';shutil.copy2(database.DB_PATH,path);monkeypatch.setattr(database,'DB_PATH',path)
    today=date.today();yesterday=today-timedelta(days=1);tomorrow=today+timedelta(days=1)
    with sqlite3.connect(path)as c:
        user=c.execute("SELECT u.id,u.employee_id FROM users u WHERE u.role='PurchaseOfficer' LIMIT 1").fetchone()
        c.execute("INSERT INTO approval_limit_history(employee_id,approval_type,new_limit,currency,effective_from,expiry_date,approved_by,status)VALUES(?,'PO',100,'SAR',?,?,?,'ACTIVE')",(user[1],yesterday.isoformat(),tomorrow.isoformat(),user[0]))
    within=evaluate_authority({'id':user[0]},'100','PO')
    assert within.outcome=='AUTO_APPROVED_WITHIN_AUTHORITY'
    assert within.authority_reference.startswith('APPROVAL_LIMIT_HISTORY:')
    above=evaluate_authority({'id':user[0]},'101','PO')
    assert above.outcome in('PENDING_APPROVAL','PENDING_EXTERNAL_APPROVAL')
    with sqlite3.connect(path)as c:c.execute("UPDATE approval_limit_history SET expiry_date=? WHERE employee_id=? AND approval_type='PO'",(yesterday.isoformat(),user[1]))
    expired=evaluate_authority({'id':user[0]},'1','PO')
    assert expired.outcome!='AUTO_APPROVED_WITHIN_AUTHORITY'


def test_po_amendment_invalidates_old_approval_and_escalates(tmp_path,monkeypatch):
    path=tmp_path/'po-amendment.db';shutil.copy2(database.DB_PATH,path);monkeypatch.setattr(database,'DB_PATH',path)
    with sqlite3.connect(path)as c:
        user=c.execute("SELECT id FROM users WHERE role='SupplyChainManager' LIMIT 1").fetchone()[0]
        supplier=c.execute('SELECT id FROM suppliers LIMIT 1').fetchone()[0];item=c.execute('SELECT id FROM items LIMIT 1').fetchone()[0];warehouse=c.execute('SELECT id FROM warehouses LIMIT 1').fetchone()[0]
    client=TestClient(app);headers={'Authorization':f'Bearer {sign_token({"id":user})}'}
    created=client.post('/api/procurement/pos',headers=headers,json={'supplier_id':supplier,'delivery_warehouse_id':warehouse,'items':[{'item_id':item,'quantity':1,'price':100,'tax':0}]})
    assert created.status_code==201,created.text;assert created.json()['status']=='Approved'
    amended=client.put(f"/api/procurement/pos/{created.json()['id']}/amend",headers=headers,json={'revision_reason':'Quantity and commercial value increase','supplier_id':supplier,'delivery_warehouse_id':warehouse,'items':[{'item_id':item,'quantity':2,'price':600000,'tax':0}]})
    assert amended.status_code==200,amended.text;assert amended.json()['status']=='PendingApproval'
    with sqlite3.connect(path)as c:
        events=[row[0]for row in c.execute("SELECT event_type FROM approval_log WHERE document_type='PO' AND document_id=? ORDER BY id",(created.json()['id'],))]
    assert 'APPROVAL_INVALIDATED_BY_AMENDMENT' in events and 'PENDING_EXTERNAL_APPROVAL' in events


def test_adjustment_records_financial_before_after_and_rejects_negative_stock(tmp_path,monkeypatch):
    path=tmp_path/'adjustment.db';shutil.copy2(database.DB_PATH,path);monkeypatch.setattr(database,'DB_PATH',path)
    with sqlite3.connect(path)as c:
        user=c.execute("SELECT id FROM users WHERE role='SupplyChainManager' LIMIT 1").fetchone()[0];item=c.execute('SELECT id FROM items LIMIT 1').fetchone()[0];warehouse,location=c.execute('SELECT warehouse_id,id FROM locations WHERE type=\'Bin\' LIMIT 1').fetchone()
    client=TestClient(app);headers={'Authorization':f'Bearer {sign_token({"id":user})}'}
    created=client.post('/api/warehouse/adjustments',headers=headers,json={'item_id':item,'warehouse_id':warehouse,'location_id':location,'quantity_change':2,'reason':'Count correction','detailed_remarks':'Verified physical count increase.'})
    assert created.status_code==201,created.text;assert created.json()['status']=='Approved'
    with sqlite3.connect(path)as c:
        row=c.execute('SELECT quantity_before,quantity_after,unit_cost,total_value_impact,approved_at,authority_reference FROM stock_adjustments WHERE id=?',(created.json()['id'],)).fetchone()
    assert row[:4]==(0,2,12.5,25) and row[4] and row[5]
    rejected=client.post('/api/warehouse/adjustments',headers=headers,json={'item_id':item,'warehouse_id':warehouse,'location_id':location,'quantity_change':-3,'reason':'Count correction','detailed_remarks':'Verified physical count decrease.'})
    assert rejected.status_code==400
