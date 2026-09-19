import shutil,sqlite3
from datetime import date,timedelta
import httpx,pytest
from fastapi.testclient import TestClient
from app import database
from app.main import app
from app.routes import workforce
from app.security import sign_token

def test_authenticated_exchange_rate_sync_stores_source_and_denies_unauthorized_role(tmp_path,monkeypatch):
    path=tmp_path/'exchange-rate.db';shutil.copy2(database.DB_PATH,path);monkeypatch.setattr(database,'DB_PATH',path);monkeypatch.setenv('EXCHANGE_RATE_API_KEY','test-key')
    with sqlite3.connect(path)as c:
        manager=c.execute("SELECT id FROM users WHERE role='SupplyChainManager' AND is_active=1 AND deleted_at IS NULL LIMIT 1").fetchone()[0]
        officer=c.execute("SELECT id FROM users WHERE role='PurchaseOfficer' AND is_active=1 AND deleted_at IS NULL LIMIT 1").fetchone()[0]
        currencies=[row[0]for row in c.execute('SELECT currency_code FROM currencies WHERE active_yn=1 ORDER BY currency_code LIMIT 2').fetchall()]
        if len(currencies)<2:
            c.execute("INSERT OR IGNORE INTO currencies(currency_code,currency_name,currency_symbol)VALUES('USD','US Dollar','$'),('SAR','Saudi Riyal','SAR')");currencies=['USD','SAR']
    class Response:
        def raise_for_status(self):return None
        def json(self):return {'result':'success','base_code':currencies[0],'target_code':currencies[1],'conversion_rate':3.75}
    monkeypatch.setattr(workforce.httpx,'get',lambda *args,**kwargs:Response())
    client=TestClient(app);manager_headers={'Authorization':f"Bearer {sign_token({'id':manager})}"};officer_headers={'Authorization':f"Bearer {sign_token({'id':officer})}"};payload={'from_currency':currencies[0],'to_currency':currencies[1],'effective_date':date.today().isoformat()}
    assert client.post('/api/workforce/exchange-rates/synchronize',headers=officer_headers,json=payload).status_code==403
    preview=client.post('/api/workforce/exchange-rates/synchronize',headers=manager_headers,json=payload)
    assert preview.status_code==200 and preview.json()['preview']is True
    with sqlite3.connect(path)as c:assert c.execute('SELECT COUNT(*) FROM exchange_rates WHERE from_currency=? AND to_currency=? AND effective_date=?',(*currencies,date.today().isoformat())).fetchone()[0]==0
    result=client.post('/api/workforce/exchange-rates/synchronize',headers=manager_headers,json={**payload,'confirm':True,'expected_rate':preview.json()['rate']})
    assert result.status_code==200,result.text;assert result.json()['rate']==3.75;assert result.json()['source']=='ExchangeRate-API v6 (authenticated)'
    with sqlite3.connect(path)as c:
        row=c.execute('SELECT rate,source,manual_yn,synchronized_at,synchronized_by FROM exchange_rates WHERE from_currency=? AND to_currency=? AND effective_date=?',(*currencies,date.today().isoformat())).fetchone()
        audit=c.execute("SELECT COUNT(*) FROM audit_log WHERE table_name='exchange_rates' AND record_id=(SELECT id FROM exchange_rates WHERE from_currency=? AND to_currency=? AND effective_date=?)",(*currencies,date.today().isoformat())).fetchone()[0]
    assert row[:3]==(3.75,'ExchangeRate-API v6 (authenticated)',0);assert row[3]and row[4]==manager;assert audit==1

@pytest.mark.parametrize('failure', ['missing-key','timeout','invalid-response','zero-rate','malformed-json'])
def test_provider_failures_preserve_existing_rate(tmp_path,monkeypatch,failure):
    path=tmp_path/f'failure-{failure}.db';shutil.copy2(database.DB_PATH,path);monkeypatch.setattr(database,'DB_PATH',path)
    with sqlite3.connect(path)as c:
        manager=c.execute("SELECT id FROM users WHERE role='SupplyChainManager' AND is_active=1 AND deleted_at IS NULL LIMIT 1").fetchone()[0]
        currencies=[row[0]for row in c.execute('SELECT currency_code FROM currencies WHERE active_yn=1 ORDER BY currency_code LIMIT 2').fetchall()]
        c.execute("INSERT OR REPLACE INTO exchange_rates(from_currency,to_currency,rate,effective_date,source,manual_yn,active_yn)VALUES(?,?,2.5,?,'Prior Valid Rate',1,1)",(*currencies,date.today().isoformat()))
    if failure!='missing-key':monkeypatch.setenv('EXCHANGE_RATE_API_KEY','invalid-or-test-key')
    else:monkeypatch.delenv('EXCHANGE_RATE_API_KEY',raising=False)
    class Response:
        def raise_for_status(self):return None
        def json(self):
            if failure=='malformed-json':raise ValueError('malformed')
            return {'result':'success','conversion_rate':0}if failure=='zero-rate'else{'result':'error','error-type':'invalid-key'}
    def provider(*args,**kwargs):
        if failure=='timeout':raise httpx.TimeoutException('timeout')
        return Response()
    monkeypatch.setattr(workforce.httpx,'get',provider)
    response=TestClient(app).post('/api/workforce/exchange-rates/synchronize',headers={'Authorization':f"Bearer {sign_token({'id':manager})}"},json={'from_currency':currencies[0],'to_currency':currencies[1]})
    assert response.status_code in(502,503)
    with sqlite3.connect(path)as c:assert c.execute('SELECT rate,source FROM exchange_rates WHERE from_currency=? AND to_currency=? AND effective_date=?',(*currencies,date.today().isoformat())).fetchone()==(2.5,'Prior Valid Rate')

def test_manual_rate_is_validated_labeled_and_audited(tmp_path,monkeypatch):
    path=tmp_path/'manual-rate.db';shutil.copy2(database.DB_PATH,path);monkeypatch.setattr(database,'DB_PATH',path)
    with sqlite3.connect(path)as c:
        manager=c.execute("SELECT id FROM users WHERE role='SupplyChainManager' AND is_active=1 AND deleted_at IS NULL LIMIT 1").fetchone()[0];currencies=[row[0]for row in c.execute('SELECT currency_code FROM currencies WHERE active_yn=1 ORDER BY currency_code LIMIT 2').fetchall()]
    client=TestClient(app);headers={'Authorization':f"Bearer {sign_token({'id':manager})}"};payload={'from_currency':currencies[0],'to_currency':currencies[1],'rate':1.25,'effective_date':(date.today()+timedelta(days=1)).isoformat(),'expiry_date':(date.today()+timedelta(days=30)).isoformat(),'source':'Manager verified bulletin'}
    assert client.post('/api/workforce/exchange-rates',headers=headers,json={**payload,'rate':0}).status_code==400
    created=client.post('/api/workforce/exchange-rates',headers=headers,json=payload);assert created.status_code==201,created.text
    with sqlite3.connect(path)as c:
        row=c.execute('SELECT id,source,manual_yn,created_by,created_at,expiry_date FROM exchange_rates WHERE from_currency=? AND to_currency=? AND effective_date=?',(*currencies,payload['effective_date'])).fetchone();audit=c.execute("SELECT COUNT(*) FROM audit_log WHERE table_name='exchange_rates' AND record_id=?",(row[0],)).fetchone()[0]
    assert row[1].startswith('Manual Rate —')and row[2]==1 and row[3]==manager and row[4]and audit==1

    assert row[5]==payload['expiry_date']
    deleted=client.delete(f'/api/workforce/exchange-rates/{row[0]}',headers=headers);assert deleted.status_code==200,deleted.text
    with sqlite3.connect(path)as c:
        active=c.execute('SELECT active_yn FROM exchange_rates WHERE id=?',(row[0],)).fetchone()[0];delete_audit=c.execute("SELECT COUNT(*) FROM audit_log WHERE table_name='exchange_rates' AND record_id=? AND action='DELETE'",(row[0],)).fetchone()[0]
    assert active==0 and delete_audit==1

def test_po_rate_snapshot_is_immutable_and_invoice_inherits_it(tmp_path,monkeypatch):
    path=tmp_path/'rate-snapshot.db';shutil.copy2(database.DB_PATH,path);monkeypatch.setattr(database,'DB_PATH',path)
    with sqlite3.connect(path)as c:
        manager=c.execute("SELECT id FROM users WHERE role='SupplyChainManager' AND is_active=1 AND deleted_at IS NULL LIMIT 1").fetchone()[0];base=c.execute("SELECT COALESCE(base_currency,currency,'SAR') FROM company WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()[0];foreign=c.execute('SELECT currency_code FROM currencies WHERE active_yn=1 AND currency_code<>? ORDER BY currency_code LIMIT 1',(base,)).fetchone()[0];supplier=c.execute('SELECT id FROM suppliers WHERE deleted_at IS NULL ORDER BY id LIMIT 1').fetchone()[0];item=c.execute('SELECT id FROM items WHERE deleted_at IS NULL ORDER BY id LIMIT 1').fetchone()[0];delivery_warehouse=c.execute('SELECT id FROM warehouses WHERE deleted_at IS NULL ORDER BY id LIMIT 1').fetchone()[0]
        c.execute("INSERT OR REPLACE INTO exchange_rates(from_currency,to_currency,rate,effective_date,source,manual_yn,active_yn)VALUES(?,?,3.75,?,'Rate A',0,1)",(foreign,base,(date.today()-timedelta(days=1)).isoformat()))
    client=TestClient(app);headers={'Authorization':f"Bearer {sign_token({'id':manager})}"};po_response=client.post('/api/procurement/pos',headers=headers,json={'supplier_id':supplier,'delivery_warehouse_id':delivery_warehouse,'transaction_currency':foreign,'items':[{'item_id':item,'quantity':10,'price':12.34,'tax':0}]})
    assert po_response.status_code==201,po_response.text;po_id=po_response.json()['id'];assert po_response.json()['base_currency_amount']==462.75
    with sqlite3.connect(path)as c:
        c.execute("INSERT OR REPLACE INTO exchange_rates(from_currency,to_currency,rate,effective_date,source,manual_yn,active_yn)VALUES(?,?,4.0,?,'Rate B',0,1)",(foreign,base,date.today().isoformat()));c.execute("UPDATE purchase_orders SET status='Closed' WHERE id=?",(po_id,));warehouse=c.execute('SELECT id FROM warehouses WHERE deleted_at IS NULL ORDER BY id LIMIT 1').fetchone()[0];grn=c.execute("INSERT INTO grns(grn_number,po_id,supplier_id,created_by)VALUES('FX-GRN-TEST',?,?,?)",(po_id,supplier,manager)).lastrowid;c.execute('INSERT INTO grn_items(grn_id,item_id,quantity_received,accepted_qty,rejected_qty,unit_cost,warehouse_id)VALUES(?,?,?,?,?,?,?)',(grn,item,10,10,0,12.34,warehouse));stored_po=c.execute('SELECT exchange_rate,base_currency_amount FROM purchase_orders WHERE id=?',(po_id,)).fetchone()
    assert stored_po==(3.75,462.75)
    invoice=client.post('/api/procurement/invoices',headers=headers,json={'invoice_number':'FX-INVOICE-TEST','supplier_id':supplier,'po_id':po_id,'invoice_total':123.4,'tax':0,'transaction_currency':foreign});assert invoice.status_code==201,invoice.text
    match=client.get(f"/api/procurement/invoices/{invoice.json()['id']}/three-way-match",headers=headers);assert match.status_code==200,match.text
    with sqlite3.connect(path)as c:stored_invoice=c.execute('SELECT transaction_currency,exchange_rate,base_currency,base_currency_amount FROM invoices WHERE id=?',(invoice.json()['id'],)).fetchone()
    assert stored_invoice==(foreign,3.75,base,462.75);assert match.json()['invoice']['exchange_rate']==3.75 and match.json()['po']['exchange_rate']==3.75
