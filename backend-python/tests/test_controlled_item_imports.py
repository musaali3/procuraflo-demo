import csv
import io
import shutil
import sqlite3
from openpyxl import load_workbook

from fastapi.testclient import TestClient

from app import database
from app.main import app
from app.security import sign_token


FIELDS = [
    'description','category','subcategory','uom','purchase_uom','issue_uom',
    'conversion_factor','consumable_returnable','high_value_flag','always_approval_yn',
    'tool_control_yn','batch_control_yn','expiry_control_yn','inspection_required_yn',
    'min_stock','max_stock','reorder_level','standard_cost',
]


def setup_copy(tmp_path, monkeypatch, name):
    path=tmp_path/name
    shutil.copy2(database.DB_PATH,path)
    monkeypatch.setattr(database,'DB_PATH',path)
    with sqlite3.connect(path) as connection:
        user_id=connection.execute("SELECT id FROM users WHERE role='SupplyChainManager' AND is_active=1 AND deleted_at IS NULL LIMIT 1").fetchone()[0]
    return path,TestClient(app),{'Authorization':f"Bearer {sign_token({'id':user_id})}"}


def csv_file(rows, fields=FIELDS):
    output=io.StringIO()
    writer=csv.DictWriter(output,fieldnames=fields)
    writer.writeheader();writer.writerows(rows)
    return {'file':('controlled.csv',output.getvalue().encode(),'text/csv')}


def item(description='Controlled Import Item'):
    return {'description':description,'category':'Controlled Test Category','subcategory':'Controlled Test Subcategory','uom':'EA','purchase_uom':'BOX','issue_uom':'EA','conversion_factor':10,'consumable_returnable':'Consumable','high_value_flag':0,'always_approval_yn':0,'tool_control_yn':0,'batch_control_yn':1,'expiry_control_yn':0,'inspection_required_yn':1,'min_stock':5,'max_stock':100,'reorder_level':20,'standard_cost':12.5}


def test_excel_templates_download_as_valid_workbooks(tmp_path,monkeypatch):
    _path,client,headers=setup_copy(tmp_path,monkeypatch,'excel-template.db')
    for template_type in ('vendors','items','opening-balances'):
        response=client.get(f'/api/settings/imports/{template_type}/template',headers=headers)
        assert response.status_code==200,response.text
        assert response.headers['content-type'].startswith('application/vnd.openxmlformats')
        workbook=load_workbook(io.BytesIO(response.content),read_only=True,data_only=True)
        rows=list(workbook.active.values)
        assert len(rows)>=4
        assert rows[0][0]=='Procuraflo - Supply Chain Control System'
        header=next(row for row in rows if sum(value not in(None,'')for value in row)>=2)
        assert all(header)


def test_codes_taxonomy_and_item_updates_are_controlled(tmp_path,monkeypatch):
    path,client,headers=setup_copy(tmp_path,monkeypatch,'controlled-master.db')
    manual=client.post('/api/masters/items',headers=headers,json={**item(),'item_code':'ITM-MANUAL'})
    assert manual.status_code==400 and 'generated automatically' in manual.json()['error']
    category=client.post('/api/masters/item-taxonomy/categories',headers=headers,json={'name':'Controlled Test Category'})
    assert category.status_code==201,category.text
    subcategory=client.post('/api/masters/item-taxonomy/subcategories',headers=headers,json={'category_id':category.json()['id'],'name':'Controlled Test Subcategory'})
    assert subcategory.status_code==201,subcategory.text
    created=client.post('/api/masters/items',headers=headers,json=item())
    assert created.status_code==201,created.text
    assert created.json()['item_code'].startswith('ITM-')
    invalid=client.put(f"/api/masters/items/{created.json()['id']}",headers=headers,json={'conversion_factor':0})
    assert invalid.status_code==400
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT conversion_factor FROM items WHERE id=?',(created.json()['id'],)).fetchone()[0]==10


def test_item_import_is_complete_generated_and_atomic(tmp_path,monkeypatch):
    path,client,headers=setup_copy(tmp_path,monkeypatch,'controlled-import.db')
    response=client.post('/api/settings/imports/items',headers=headers,files=csv_file([item('Imported Complete Item')]))
    assert response.status_code==200,response.text
    with sqlite3.connect(path) as connection:
        row=connection.execute("SELECT item_code,category,subcategory,conversion_factor FROM items WHERE description='Imported Complete Item'").fetchone()
    assert row and row[0].startswith('ITM-') and row[1:] == ('Controlled Test Category','Controlled Test Subcategory',10)
    bad=item('Atomic Valid Row');bad2=item('Atomic Invalid Row');bad2['subcategory']=''
    rejected=client.post('/api/settings/imports/items',headers=headers,files=csv_file([bad,bad2]))
    assert rejected.status_code==400
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM items WHERE description LIKE 'Atomic % Row'").fetchone()[0]==0


def test_opening_balance_creates_item_and_permanent_stock_records(tmp_path,monkeypatch):
    path,client,headers=setup_copy(tmp_path,monkeypatch,'controlled-opening.db')
    with sqlite3.connect(path) as connection:
        warehouse=connection.execute("SELECT id,warehouse_code FROM warehouses WHERE deleted_at IS NULL ORDER BY id LIMIT 1").fetchone()
        location=connection.execute("SELECT code FROM locations WHERE warehouse_id=? AND type='Bin' AND deleted_at IS NULL ORDER BY id LIMIT 1",(warehouse[0],)).fetchone()
    assert location
    row={**item('Opening Balance New Item'),'warehouse':warehouse[1],'location':location[0],'quantity':17,'unit_cost':9.25,'received_date':'2025-01-15'}
    fields=FIELDS+['warehouse','location','quantity','unit_cost','received_date']
    response=client.post('/api/settings/imports/opening-balances',headers=headers,files=csv_file([row],fields))
    assert response.status_code==200,response.text
    assert response.json()['new_items_created']==1
    with sqlite3.connect(path) as connection:
        item_id=connection.execute("SELECT id FROM items WHERE description='Opening Balance New Item'").fetchone()[0]
        stock=connection.execute('SELECT quantity FROM inventory_stock WHERE item_id=?',(item_id,)).fetchone()[0]
        layer=connection.execute('SELECT quantity_remaining,received_date FROM inventory_layers WHERE item_id=?',(item_id,)).fetchone()
        ledger=connection.execute("SELECT quantity_change FROM stock_ledger WHERE item_id=? AND transaction_type='OPENING_BALANCE'",(item_id,)).fetchone()[0]
    assert stock==17 and layer==(17,'2025-01-15') and ledger==17
