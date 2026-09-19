import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app import database,tenancy
from app.main import app
from app.permissions import defaults_for_role


def setup_tenants(tmp_path,monkeypatch):
    source=tmp_path/'source.db'
    source.write_bytes(Path(database.DB_PATH).read_bytes())
    monkeypatch.setattr(database,'DB_PATH',source)
    monkeypatch.setattr(tenancy,'TENANT_ROOT',tmp_path/'tenants')
    monkeypatch.setattr(tenancy,'REGISTRY_PATH',tmp_path/'tenants'/'tenant-registry.db')
    monkeypatch.delenv('ALLOW_MULTIPLE_COMPANIES',raising=False)
    return TestClient(app)


def registration(key,name):
    return {'company_key':key,'company_name':name,'company_email':f'admin@{key}.test','admin_name':f'{name} Administrator','admin_email':f'admin@{key}.test','username':'admin','password':'Secure-Tenant-Password-123!'}


def test_company_registration_login_and_database_isolation(tmp_path,monkeypatch):
    client=setup_tenants(tmp_path,monkeypatch)
    for key,name in [('alpha-precast','Alpha Precast')]:
        created=client.post('/api/auth/register-company',json=registration(key,name))
        assert created.status_code==201,created.text
        assert client.get('/api/auth/registration-status').json()['registration_enabled'] is False
        signed_in=client.post('/api/auth/login',json={'company_key':key,'username':'admin','password':'Secure-Tenant-Password-123!'},headers={'X-Company-Key':key})
        assert signed_in.status_code==200,signed_in.text
        assert signed_in.json()['user']['tenant_key']==key
        token=signed_in.json()['token']
        headers={'Authorization':f'Bearer {token}','X-Company-Key':key}
        supply_chain=client.get('/api/masters/employees',headers=headers)
        assert supply_chain.status_code==200,supply_chain.text
        administrator=next(row for row in supply_chain.json()if row['employee_code']=='EMP-0001')
        assert administrator['department_name']=='Procurement'
        assert administrator['position']=='Supply Chain Manager'
        assert administrator['approval_role']=='SupplyChainManager'
        assert administrator['system_access_yn']==1
        assert set(json.loads(administrator['permission_keys']))==set(defaults_for_role('SupplyChainManager'))
        updated=client.put(f"/api/masters/employees/{administrator['id']}",headers=headers,json={
            'name':administrator['name'],'department_id':administrator['department_id'],
            'position':'Supply Chain Manager','approval_role':'SupplyChainManager',
            'approval_limit':250000,'permission_keys':administrator['permission_keys'],
            'system_access_yn':1,'status':'Active',
        })
        assert updated.status_code==200,updated.text
        assert updated.json()['approval_limit']==250000
        company_employees=client.get('/api/masters/general-employees',headers=headers)
        assert company_employees.status_code==200
        assert all(row['id']!=administrator['id']for row in company_employees.json())
        me=client.get('/api/auth/me',headers=headers)
        assert me.status_code==200 and me.json()['tenant_key']==key
        mismatch=client.get('/api/auth/me',headers={'Authorization':f'Bearer {token}','X-Company-Key':'beta-precast'})
        assert mismatch.status_code==401
    blocked=client.post('/api/auth/register-company',json=registration('beta-precast','Beta Precast'))
    assert blocked.status_code==403
    alpha=tenancy.tenant_record('alpha-precast')
    with sqlite3.connect(alpha['database_path'])as connection:
        assert connection.execute('SELECT name FROM company').fetchone()[0]=='Alpha Precast'
        connection.execute("INSERT INTO suppliers(supplier_code,name)VALUES('SUP-SECRET','Alpha Secret Supplier')");connection.commit()


def test_multiple_company_registration_requires_explicit_opt_in(tmp_path,monkeypatch):
    client=setup_tenants(tmp_path,monkeypatch)
    monkeypatch.setenv('ALLOW_MULTIPLE_COMPANIES','true')
    for key,name in [('alpha-precast','Alpha Precast'),('beta-precast','Beta Precast')]:
        created=client.post('/api/auth/register-company',json=registration(key,name))
        assert created.status_code==201,created.text
    assert client.get('/api/auth/registration-status').json()['registration_enabled'] is True
    alpha=tenancy.tenant_record('alpha-precast');beta=tenancy.tenant_record('beta-precast')
    with sqlite3.connect(alpha['database_path'])as connection:
        connection.execute("INSERT INTO suppliers(supplier_code,name)VALUES('SUP-SECRET','Alpha Secret Supplier')");connection.commit()
    with sqlite3.connect(beta['database_path'])as connection:
        assert connection.execute('SELECT name FROM company').fetchone()[0]=='Beta Precast'
        assert connection.execute("SELECT COUNT(*) FROM suppliers WHERE supplier_code='SUP-SECRET'").fetchone()[0]==0
