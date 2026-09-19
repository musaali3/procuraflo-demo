import shutil
import sqlite3
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi.testclient import TestClient

from app import database
from app.main import app
from app.security import JWT_ALGORITHM, JWT_SECRET


def _authenticated_client(tmp_path, monkeypatch):
    target = tmp_path / 'authentication-stability.db'
    shutil.copy2(database.DB_PATH, target)
    monkeypatch.setattr(database, 'DB_PATH', target)
    password = 'Authentication-Test-123!'
    with sqlite3.connect(target) as connection:
        employee_id = connection.execute(
            "INSERT INTO employees(employee_code,name,status,system_access_yn,approval_role) "
            "VALUES('AUTH-STABILITY','Authentication Test','Active',1,'SupplyChainManager')"
        ).lastrowid
        connection.execute(
            "INSERT INTO users(employee_id,username,password_hash,full_name,role,is_active) VALUES(?,?,?,?,?,1)",
            (employee_id, 'auth.stability', bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(), 'Authentication Test', 'SupplyChainManager'),
        )
    return TestClient(app), password


def test_login_returns_complete_context_and_supports_refresh(tmp_path, monkeypatch):
    client, password = _authenticated_client(tmp_path, monkeypatch)
    login = client.post('/api/auth/login', json={'company_key': 'default', 'username': 'auth.stability', 'password': password})
    assert login.status_code == 200
    body = login.json()
    assert body['user']['tenant_key'] == 'default'
    assert isinstance(body['user']['permission_keys'], list)
    assert isinstance(body['user']['warehouse_ids'], list)

    refreshed = client.get(
        '/api/auth/me',
        headers={'Authorization': f"Bearer {body['token']}", 'X-Company-Key': 'default'},
    )
    assert refreshed.status_code == 200
    assert refreshed.json()['id'] == body['user']['id']
    assert refreshed.json()['tenant_key'] == 'default'


def test_invalid_password_and_unknown_user_are_rejected(tmp_path, monkeypatch):
    client, _password = _authenticated_client(tmp_path, monkeypatch)
    invalid = client.post('/api/auth/login', json={'company_key': 'default', 'username': 'auth.stability', 'password': 'wrong'})
    unknown = client.post('/api/auth/login', json={'company_key': 'default', 'username': 'missing.user', 'password': 'wrong'})
    assert invalid.status_code == 401
    assert unknown.status_code == 401


def test_expired_modified_and_cross_tenant_tokens_are_rejected(tmp_path, monkeypatch):
    client, password = _authenticated_client(tmp_path, monkeypatch)
    token = client.post('/api/auth/login', json={'company_key': 'default', 'username': 'auth.stability', 'password': password}).json()['token']
    claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    expired_claims = {**claims, 'iat': datetime.now(timezone.utc) - timedelta(hours=2), 'exp': datetime.now(timezone.utc) - timedelta(hours=1)}
    expired = jwt.encode(expired_claims, JWT_SECRET, algorithm=JWT_ALGORITHM)
    header, payload, signature = token.split('.')
    # Changing the final base64 character can alter only unused padding bits.
    # Change the first signature character to guarantee different signed bytes.
    modified = '.'.join((header, payload, ('a' if signature[0] != 'a' else 'b') + signature[1:]))

    assert client.get('/api/auth/me', headers={'Authorization': f'Bearer {expired}', 'X-Company-Key': 'default'}).status_code == 401
    assert client.get('/api/auth/me', headers={'Authorization': f'Bearer {modified}', 'X-Company-Key': 'default'}).status_code == 401
    assert client.get('/api/auth/me', headers={'Authorization': f'Bearer {token}', 'X-Company-Key': 'another-company'}).status_code == 401
