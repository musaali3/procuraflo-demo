import os
from pathlib import Path

os.environ.setdefault('DB_PATH', str(Path(__file__).resolve().parents[1] / 'test-parity.db'))
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health():
    assert client.get('/api/health').json() == {
        'status': 'ok',
        'system': 'Procuraflo',
        'description': 'Supply Chain Control System',
    }

def test_auth_contract():
    response=client.get('/api/inventory/stock')
    assert response.status_code==401
    assert response.json()=={'error':'Missing or invalid Authorization header'}

def test_login_validation_contract():
    response=client.post('/api/auth/login',json={})
    assert response.status_code==400
    assert response.json()=={'error':'Username and password required'}
