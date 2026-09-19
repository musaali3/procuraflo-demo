import os
import re
import sqlite3
import stat
from contextlib import contextmanager
from pathlib import Path

from . import database

TENANT_ROOT = Path(os.getenv('TENANT_DATA_DIR', str(database.RUNTIME_DATA_DIR / 'tenants'))).resolve()
REGISTRY_PATH = TENANT_ROOT / 'tenant-registry.db'
TENANT_KEY = re.compile(r'^[a-z0-9][a-z0-9-]{2,47}$')
REFERENCE_TABLES = ('countries','cities','currencies','item_categories','item_subcategories','settings','role_shift_requirements')
TRUTHY = {'1','true','yes','on'}


def normalize_tenant_key(value: str) -> str:
    key=re.sub(r'[^a-z0-9]+','-',str(value or'').strip().lower()).strip('-')
    if not TENANT_KEY.fullmatch(key):raise ValueError('Company login ID must contain 3-48 lowercase letters, numbers, or hyphens')
    return key


def ensure_registry():
    TENANT_ROOT.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(REGISTRY_PATH)as c:
        c.execute('''CREATE TABLE IF NOT EXISTS tenants(
          tenant_key TEXT PRIMARY KEY,company_name TEXT NOT NULL COLLATE NOCASE UNIQUE,database_path TEXT NOT NULL UNIQUE,
          status TEXT NOT NULL DEFAULT 'Active',created_at TEXT NOT NULL DEFAULT(datetime('now')))''')
        c.execute("INSERT OR IGNORE INTO tenants(tenant_key,company_name,database_path)VALUES('default','Existing Procuraflo Company',?)",(str(database.DB_PATH),))


def allow_multiple_companies() -> bool:
    return str(os.getenv('ALLOW_MULTIPLE_COMPANIES','')).strip().lower() in TRUTHY


def registered_company_count(include_default: bool = False) -> int:
    ensure_registry()
    condition = "status='Active'" if include_default else "status='Active' AND tenant_key<>'default'"
    with sqlite3.connect(REGISTRY_PATH)as c:
        return int(c.execute(f'SELECT COUNT(*) FROM tenants WHERE {condition}').fetchone()[0])


def company_registration_status() -> dict:
    count = registered_company_count(include_default=False)
    multiple = allow_multiple_companies()
    return {
        'registration_enabled': multiple or count == 0,
        'registered_company_count': count,
        'multiple_company_registration': multiple,
    }


def tenant_record(key: str):
    if str(key or'').lower()=='default':return {'tenant_key':'default','company_name':'Existing Procuraflo Company','database_path':str(database.DB_PATH),'status':'Active'}
    ensure_registry()
    with sqlite3.connect(REGISTRY_PATH)as c:
        c.row_factory=sqlite3.Row;row=c.execute("SELECT * FROM tenants WHERE tenant_key=? AND status='Active'",(str(key or'').lower(),)).fetchone()
        return dict(row)if row else None


@contextmanager
def tenant_database(key: str):
    row=tenant_record(key)
    if not row:raise LookupError('Company login ID was not found')
    token=database.use_database(Path(row['database_path']))
    try:yield row
    finally:database.reset_database(token)


@contextmanager
def tenant_database_for_registration(path: Path):
    token=database.use_database(path)
    try:yield
    finally:database.reset_database(token)


def _create_schema(target: Path):
    source=sqlite3.connect(database.DB_PATH);source.row_factory=sqlite3.Row
    target_connection=sqlite3.connect(target)
    try:
        target_connection.execute('PRAGMA foreign_keys=OFF')
        objects=source.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'view' THEN 1 WHEN 'index' THEN 2 ELSE 3 END").fetchall()
        for row in objects:
            try:target_connection.execute(row['sql'])
            except sqlite3.OperationalError as error:
                if 'already exists'not in str(error).lower():raise
        for table in REFERENCE_TABLES:
            exists=source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
            if not exists:continue
            columns=[row['name']for row in source.execute(f'PRAGMA table_info({table})')]
            rows=source.execute(f'SELECT * FROM {table}').fetchall()
            if rows:
                placeholders=','.join('?'for _ in columns)
                target_connection.executemany(f"INSERT INTO {table}({','.join(columns)})VALUES({placeholders})",([row[column]for column in columns]for row in rows))
        target_connection.execute("INSERT OR IGNORE INTO system_maintenance(id,active_yn,session_epoch)VALUES(1,0,1)")
        target_connection.commit()
    finally:target_connection.close();source.close()


def provision_tenant(key: str, company_name: str) -> Path:
    ensure_registry();key=normalize_tenant_key(key);target=(TENANT_ROOT/f'{key}.db').resolve()
    if not allow_multiple_companies() and registered_company_count(include_default=False)>0:raise FileExistsError('Company registration is closed for this installation')
    try:target.relative_to(TENANT_ROOT)
    except ValueError:raise ValueError('Company database path must stay inside the tenant data directory')
    if target.exists():raise FileExistsError('Company database already exists')
    with sqlite3.connect(REGISTRY_PATH)as registry:
        if registry.execute('SELECT 1 FROM tenants WHERE tenant_key=? OR lower(company_name)=lower(?)',(key,company_name)).fetchone():raise FileExistsError('Company name or login ID is already registered')
    _create_schema(target)
    try:target.chmod(stat.S_IRUSR|stat.S_IWUSR)
    except OSError:pass
    return target


def register_tenant(key: str, company_name: str, target: Path):
    with sqlite3.connect(REGISTRY_PATH)as c:
        c.execute('BEGIN IMMEDIATE')
        if not allow_multiple_companies() and c.execute("SELECT 1 FROM tenants WHERE tenant_key<>'default' AND status='Active' LIMIT 1").fetchone():
            raise FileExistsError('Company registration is closed for this installation')
        c.execute('INSERT INTO tenants(tenant_key,company_name,database_path)VALUES(?,?,?)',(key,company_name,str(target)))


def migrate_registered_tenants() -> None:
    """Apply idempotent compatibility migrations inside every tenant boundary."""
    ensure_registry()
    with sqlite3.connect(REGISTRY_PATH) as registry:
        paths=[Path(row[0]).resolve() for row in registry.execute("SELECT database_path FROM tenants WHERE status='Active'")]
    for path in paths:
        if not path.is_file() or path==database.DB_PATH:continue
        token=database.use_database(path)
        try:database.ensure_company_employee_schema()
        finally:database.reset_database(token)
