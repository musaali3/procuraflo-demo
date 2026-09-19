import shutil
import sqlite3

from fastapi.testclient import TestClient

from app import database
from app.main import app
from app.security import sign_token


def test_editing_one_shift_never_changes_other_shift_times(tmp_path, monkeypatch):
    test_database = tmp_path / 'single-shift-update.db'
    shutil.copy2(database.DB_PATH, test_database)
    monkeypatch.setattr(database, 'DB_PATH', test_database)
    with sqlite3.connect(test_database) as connection:
        connection.row_factory = sqlite3.Row
        user_id = connection.execute("SELECT id FROM users WHERE role='SupplyChainManager' AND is_active=1 AND deleted_at IS NULL LIMIT 1").fetchone()['id']
        shifts = [dict(row) for row in connection.execute("SELECT * FROM shifts WHERE active_yn=1 ORDER BY id").fetchall()]
        assert len(shifts) >= 2
        selected, untouched = shifts[0], shifts[1:]
        untouched_before = {row['id']: (row['start_time'], row['end_time']) for row in untouched}

    response = TestClient(app).put(
        f"/api/workforce/shifts/{selected['id']}",
        headers={'Authorization': f"Bearer {sign_token({'id': user_id})}"},
        json={
            'shift_label': selected['shift_label'],
            'start_time': selected['start_time'],
            'end_time': selected['end_time'],
            'break_minutes': selected['break_minutes'],
            'effective_from': '2031-01-01',
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()['message'].startswith(f"{selected['shift_code']} updated. No other shift times were changed.")
    with sqlite3.connect(test_database) as connection:
        changed = connection.execute("SELECT start_time,end_time FROM shifts WHERE id=?", (selected['id'],)).fetchone()
        untouched_after = {row[0]: (row[1], row[2]) for row in connection.execute(
            f"SELECT id,start_time,end_time FROM shifts WHERE id IN({','.join('?' for _ in untouched)})", tuple(row['id'] for row in untouched)
        ).fetchall()}
        version = connection.execute("SELECT start_time,end_time FROM shift_versions WHERE shift_id=? AND effective_from='2031-01-01'", (selected['id'],)).fetchone()
    assert changed == (selected['start_time'], selected['end_time'])
    assert untouched_after == untouched_before
    assert version == changed

    rejected = TestClient(app).put(
        f"/api/workforce/shifts/{selected['id']}",
        headers={'Authorization': f"Bearer {sign_token({'id': user_id})}"},
            json={'start_time': '01:00', 'end_time': '09:30', 'break_minutes': selected['break_minutes']},
    )
    assert rejected.status_code == 409
    assert 'gap or overlap' in rejected.json()['error']
