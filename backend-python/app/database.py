import json
import os
import shutil
import sqlite3
from contextvars import ContextVar
from contextlib import contextmanager
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = BACKEND_ROOT / "procuraflow.db"
BOOTSTRAP_DB = Path(__file__).resolve().parent / "bootstrap.db"
DB_PATH = Path(os.getenv("DB_PATH", str(DEFAULT_DB))).resolve()
ACTIVE_DB_PATH: ContextVar[Path | None] = ContextVar('active_tenant_db_path', default=None)


def initialize_database() -> None:
    """Create a new installation from the bundled schema-only database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        with sqlite3.connect(DB_PATH) as connection:
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            if any(row[0] == 'invoices' for row in tables):
                return
            if tables:
                raise RuntimeError(
                    f'Database at {DB_PATH} has an incomplete schema; restore it from backup before starting Procuraflo'
                )
        DB_PATH.unlink()
    if not BOOTSTRAP_DB.is_file():
        raise RuntimeError(f'Procuraflo bootstrap database is missing: {BOOTSTRAP_DB}')
    shutil.copy2(BOOTSTRAP_DB, DB_PATH)


def active_db_path() -> Path:
    return ACTIVE_DB_PATH.get() or DB_PATH


def use_database(path: Path):
    return ACTIVE_DB_PATH.set(Path(path).resolve())


def reset_database(token):
    ACTIVE_DB_PATH.reset(token)


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(active_db_path(), timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def transaction(immediate: bool = False):
    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def fetch_one(sql: str, parameters=()):
    with connect() as connection:
        row = connection.execute(sql, parameters).fetchone()
        return dict(row) if row else None


def fetch_all(sql: str, parameters=()):
    with connect() as connection:
        return [dict(row) for row in connection.execute(sql, parameters).fetchall()]


def company_base_currency(default: str = 'SAR') -> str:
    row = fetch_one(
        "SELECT COALESCE(NULLIF(trim(base_currency),''),NULLIF(trim(currency),''),?) value "
        "FROM company WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 1",
        (default,),
    ) or {}
    return str(row.get('value') or default).strip().upper()

def _widen_location_type_constraint() -> None:
    """Replace the legacy indoor-only CHECK while preserving location IDs and references."""
    path=active_db_path()
    with sqlite3.connect(path) as connection:
        sql=(connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='locations'").fetchone()or[None])[0]
        legacy="CHECK(type IN ('Zone','Aisle','Rack','Shelf','Bin'))"
        if not sql or legacy not in sql:return
        allowed="CHECK(type IN ('Zone','Aisle','Rack','Shelf','Bin','Bay','Yard Slot','Ground Stack','Open Area','Staging'))"
        replacement=sql.replace('CREATE TABLE locations','CREATE TABLE locations__type_migration',1).replace(legacy,allowed)
        columns=[row[1]for row in connection.execute('PRAGMA table_info(locations)')]
        names=','.join(f'"{name}"'for name in columns)
        connection.execute('PRAGMA foreign_keys=OFF')
        connection.execute('PRAGMA legacy_alter_table=ON')
        connection.execute('BEGIN IMMEDIATE')
        try:
            connection.execute(replacement)
            connection.execute(f'INSERT INTO locations__type_migration({names}) SELECT {names} FROM locations')
            connection.execute('DROP TABLE locations')
            connection.execute('ALTER TABLE locations__type_migration RENAME TO locations')
            connection.commit()
        except Exception:
            connection.rollback();raise

def _widen_quarantine_status_constraint() -> None:
    path=active_db_path()
    with sqlite3.connect(path) as connection:
        sql=(connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='inventory_quarantine'").fetchone()or[None])[0]
        legacy="CHECK(inventory_status IN('DAMAGED','REPAIR_PENDING','INSPECTION_PENDING','REJECTED'))"
        if not sql or legacy not in sql:return
        replacement=sql.replace('CREATE TABLE inventory_quarantine','CREATE TABLE inventory_quarantine__status_migration',1).replace(legacy,"CHECK(inventory_status IN('DAMAGED','REPAIR_PENDING','INSPECTION_PENDING','PUT_AWAY_PENDING','REJECTED'))")
        columns=[row[1]for row in connection.execute('PRAGMA table_info(inventory_quarantine)')];names=','.join(f'"{name}"'for name in columns)
        connection.execute('PRAGMA foreign_keys=OFF');connection.execute('PRAGMA legacy_alter_table=ON');connection.execute('BEGIN IMMEDIATE')
        try:
            connection.execute(replacement);connection.execute(f'INSERT INTO inventory_quarantine__status_migration({names}) SELECT {names} FROM inventory_quarantine');connection.execute('DROP TABLE inventory_quarantine');connection.execute('ALTER TABLE inventory_quarantine__status_migration RENAME TO inventory_quarantine');connection.commit()
        except Exception:connection.rollback();raise


def _allow_multiple_transfer_receipts():
    """Preserve existing receipt IDs while allowing later partial receipts."""
    connection=sqlite3.connect(active_db_path(),timeout=30)
    try:
        definition=connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='transfer_receipts'").fetchone()
        if not definition or 'transfer_id INTEGER UNIQUE' not in definition[0]:return
        connection.execute('PRAGMA foreign_keys=OFF')
        connection.execute('BEGIN IMMEDIATE')
        try:
            connection.execute('''CREATE TABLE transfer_receipts__multi(
                id INTEGER PRIMARY KEY AUTOINCREMENT,receipt_number TEXT UNIQUE NOT NULL,
                transfer_id INTEGER NOT NULL REFERENCES transfers(id),
                warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
                location_id INTEGER NOT NULL REFERENCES locations(id),
                item_id INTEGER NOT NULL REFERENCES items(id),
                quantity_received REAL NOT NULL CHECK(quantity_received>0),receiving_note TEXT,
                received_by INTEGER NOT NULL REFERENCES users(id),received_at TEXT NOT NULL DEFAULT(datetime('now')),
                physical_quantity REAL NOT NULL DEFAULT 0,good_quantity REAL NOT NULL DEFAULT 0,
                damaged_quantity REAL NOT NULL DEFAULT 0,rejected_quantity REAL NOT NULL DEFAULT 0,
                shortage_quantity REAL NOT NULL DEFAULT 0,unit_cost REAL NOT NULL DEFAULT 0,
                total_value REAL NOT NULL DEFAULT 0,receipt_status TEXT,remarks TEXT)''')
            old_columns={row[1] for row in connection.execute('PRAGMA table_info(transfer_receipts)')}
            new_columns={row[1] for row in connection.execute('PRAGMA table_info(transfer_receipts__multi)')}
            shared=[column for column in new_columns if column in old_columns]
            names=','.join(shared)
            connection.execute(f'INSERT INTO transfer_receipts__multi({names}) SELECT {names} FROM transfer_receipts')
            connection.execute('DROP TABLE transfer_receipts')
            connection.execute('ALTER TABLE transfer_receipts__multi RENAME TO transfer_receipts')
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.execute('PRAGMA foreign_keys=ON')
        errors=connection.execute('PRAGMA foreign_key_check').fetchall()
        if errors:raise RuntimeError('Transfer receipt migration found broken foreign-key references')
    finally:
        connection.close()

def _allow_unassigned_transfer_destination_bins():
    """Keep existing transfer lines while allowing receipt staff to choose the bin."""
    connection=sqlite3.connect(active_db_path(),timeout=30)
    try:
        columns=connection.execute('PRAGMA table_info(transfer_items)').fetchall()
        if not columns or not next(column[3] for column in columns if column[1]=='to_location_id'):return
        definition=connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='transfer_items'").fetchone()[0]
        replacement=definition.replace('CREATE TABLE transfer_items(', 'CREATE TABLE transfer_items__receiving_bin(').replace('CREATE TABLE IF NOT EXISTS transfer_items(', 'CREATE TABLE transfer_items__receiving_bin(').replace('to_location_id INTEGER NOT NULL REFERENCES locations(id)','to_location_id INTEGER REFERENCES locations(id)')
        names=','.join(column[1] for column in columns)
        connection.execute('PRAGMA foreign_keys=OFF')
        connection.execute('BEGIN IMMEDIATE')
        try:
            connection.execute(replacement)
            connection.execute(f'INSERT INTO transfer_items__receiving_bin({names}) SELECT {names} FROM transfer_items')
            connection.execute('DROP TABLE transfer_items')
            connection.execute('ALTER TABLE transfer_items__receiving_bin RENAME TO transfer_items')
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.execute('PRAGMA foreign_keys=ON')
        if connection.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('Transfer item migration found broken foreign-key references')
    finally:
        connection.close()

def _allow_transfer_goods_inspections():
    """Existing GRN inspections remain intact; transfer receipts need no GRN link."""
    connection=sqlite3.connect(active_db_path(),timeout=30)
    try:
        columns=connection.execute('PRAGMA table_info(goods_inspections)').fetchall()
        if not columns or not any(column[1] in ('grn_id','grn_item_id') and column[3] for column in columns):return
        definition=connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='goods_inspections'").fetchone()[0]
        replacement=definition.replace('CREATE TABLE goods_inspections(', 'CREATE TABLE goods_inspections__transfer_receipts(').replace('CREATE TABLE IF NOT EXISTS goods_inspections(', 'CREATE TABLE goods_inspections__transfer_receipts(')
        for column in ('grn_id','grn_item_id'):
            replacement=replacement.replace(f'{column} INTEGER NOT NULL REFERENCES',f'{column} INTEGER REFERENCES')
        names=','.join(column[1] for column in columns)
        connection.execute('PRAGMA foreign_keys=OFF')
        connection.execute('BEGIN IMMEDIATE')
        try:
            connection.execute(replacement)
            connection.execute(f'INSERT INTO goods_inspections__transfer_receipts({names}) SELECT {names} FROM goods_inspections')
            connection.execute('DROP TABLE goods_inspections')
            connection.execute('ALTER TABLE goods_inspections__transfer_receipts RENAME TO goods_inspections')
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.execute('PRAGMA foreign_keys=ON')
        if connection.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('Inspection migration found broken foreign-key references')
    finally:
        connection.close()

def ensure_company_employee_schema():
    """Apply small, idempotent compatibility changes to existing installations."""
    _widen_location_type_constraint()
    _widen_quarantine_status_constraint()
    _allow_multiple_transfer_receipts()
    _allow_unassigned_transfer_destination_bins()
    _allow_transfer_goods_inspections()
    with transaction(immediate=True) as connection:
        for column,definition in {'source_warehouse_id':'INTEGER REFERENCES warehouses(id)','stock_quantity_snapshot':'REAL','min_stock_snapshot':'REAL','target_stock_snapshot':'REAL','auto_replenishment':'INTEGER NOT NULL DEFAULT 0'}.items():
            if column not in {row['name']for row in connection.execute('PRAGMA table_info(pr_items)')}:connection.execute(f'ALTER TABLE pr_items ADD COLUMN {column} {definition}')
        pr_item_columns={row['name']for row in connection.execute('PRAGMA table_info(pr_items)')}
        for column,definition in {'recommended_base_quantity':'REAL','quantity_variance':'REAL NOT NULL DEFAULT 0','adjustment_reason':'TEXT','adjustment_note':'TEXT','adjusted_by':'INTEGER REFERENCES users(id)','adjusted_at':'TEXT','replenishment_cycle_id':'INTEGER REFERENCES replenishment_cycles(id)'}.items():
            if column not in pr_item_columns:connection.execute(f'ALTER TABLE pr_items ADD COLUMN {column} {definition}')
        pr_columns={row['name']for row in connection.execute('PRAGMA table_info(purchase_requisitions)')}
        for column,definition in {'pr_source':"TEXT NOT NULL DEFAULT 'MANUAL'",'trigger_warehouse_id':'INTEGER REFERENCES warehouses(id)','warehouse_submitted_by':'INTEGER REFERENCES users(id)','warehouse_submitted_at':'TEXT','warehouse_closed_by':'INTEGER REFERENCES users(id)','warehouse_closed_at':'TEXT','warehouse_closure_reason':'TEXT'}.items():
            if column not in pr_columns:connection.execute(f'ALTER TABLE purchase_requisitions ADD COLUMN {column} {definition}')
        warehouse_columns={row['name']for row in connection.execute('PRAGMA table_info(warehouses)')}
        for column,definition in {'auto_replenishment_enabled':'INTEGER NOT NULL DEFAULT 0','replenishment_days_json':"TEXT NOT NULL DEFAULT '[0,3]'"}.items():
            if column not in warehouse_columns:connection.execute(f'ALTER TABLE warehouses ADD COLUMN {column} {definition}')
        connection.execute("""CREATE TABLE IF NOT EXISTS replenishment_cycles(
            id INTEGER PRIMARY KEY AUTOINCREMENT,cycle_reference TEXT NOT NULL UNIQUE,warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
            item_id INTEGER NOT NULL REFERENCES items(id),status TEXT NOT NULL DEFAULT 'ACTIVE',pr_id INTEGER REFERENCES purchase_requisitions(id),
            recommended_base_quantity REAL NOT NULL,stock_quantity_snapshot REAL NOT NULL,min_stock_snapshot REAL NOT NULL,max_stock_snapshot REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT(datetime('now')),closed_at TEXT,closure_reason TEXT)""")
        connection.execute("""CREATE TABLE IF NOT EXISTS replenishment_drafts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,draft_number TEXT NOT NULL UNIQUE,warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
            status TEXT NOT NULL DEFAULT 'Draft' CHECK(status IN('Draft','Review In Progress','Review Complete','Re-Review Required','Converted to PR','Cancelled')),
            checked_by INTEGER REFERENCES users(id),reviewed_by INTEGER REFERENCES users(id),resulting_pr_id INTEGER REFERENCES purchase_requisitions(id),
            created_at TEXT NOT NULL DEFAULT(datetime('now')),reviewed_at TEXT,revalidated_at TEXT,converted_at TEXT,cancelled_at TEXT,cancel_reason TEXT)""")
        connection.execute("""CREATE TABLE IF NOT EXISTS replenishment_draft_lines(
            id INTEGER PRIMARY KEY AUTOINCREMENT,draft_id INTEGER NOT NULL REFERENCES replenishment_drafts(id),item_id INTEGER NOT NULL REFERENCES items(id),
            item_code_snapshot TEXT,description_snapshot TEXT,uom TEXT,reorder_level REAL NOT NULL DEFAULT 0,available_qty REAL NOT NULL DEFAULT 0,
            active_pr_qty REAL NOT NULL DEFAULT 0,outstanding_po_qty REAL NOT NULL DEFAULT 0,inspection_putaway_qty REAL NOT NULL DEFAULT 0,
            effective_stock_qty REAL NOT NULL DEFAULT 0,system_recommended_qty REAL NOT NULL DEFAULT 0,reviewed_qty REAL NOT NULL DEFAULT 0,
            adjustment_reason TEXT,status_labels TEXT NOT NULL DEFAULT '',line_status TEXT NOT NULL DEFAULT 'Draft',
            last_checked_at TEXT NOT NULL DEFAULT(datetime('now')),reviewed_by INTEGER REFERENCES users(id),reviewed_at TEXT,
            revalidated_at TEXT,revalidation_changes_json TEXT)""")
        connection.execute("""CREATE TABLE IF NOT EXISTS replenishment_draft_sources(
            id INTEGER PRIMARY KEY AUTOINCREMENT,line_id INTEGER NOT NULL REFERENCES replenishment_draft_lines(id),
            source_type TEXT NOT NULL,source_id INTEGER,source_number TEXT,status TEXT,quantity REAL NOT NULL DEFAULT 0,
            detail_json TEXT,created_at TEXT NOT NULL DEFAULT(datetime('now')))""")
        pr_columns={row['name']for row in connection.execute('PRAGMA table_info(purchase_requisitions)')}
        if 'replenishment_draft_id' not in pr_columns:connection.execute('ALTER TABLE purchase_requisitions ADD COLUMN replenishment_draft_id INTEGER REFERENCES replenishment_drafts(id)')
        connection.execute('CREATE INDEX IF NOT EXISTS idx_replenishment_drafts_warehouse_status ON replenishment_drafts(warehouse_id,status)')
        connection.execute('CREATE INDEX IF NOT EXISTS idx_replenishment_lines_draft_item ON replenishment_draft_lines(draft_id,item_id)')
        connection.execute('CREATE INDEX IF NOT EXISTS idx_replenishment_sources_line ON replenishment_draft_sources(line_id,source_type)')
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_replenishment_active_scope ON replenishment_cycles(warehouse_id,item_id) WHERE status='ACTIVE'")
        connection.execute("""CREATE TABLE IF NOT EXISTS replenishment_runs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),scheduled_date TEXT NOT NULL,
            scheduled_run_time TEXT NOT NULL,actual_run_at TEXT NOT NULL DEFAULT(datetime('now')),run_type TEXT NOT NULL,status TEXT NOT NULL,
            items_checked INTEGER NOT NULL DEFAULT 0,prs_generated INTEGER NOT NULL DEFAULT 0,items_skipped_active INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,run_by INTEGER REFERENCES users(id),UNIQUE(warehouse_id,scheduled_date,run_type))""")
        # Retired automation tables/columns remain only for historical references.
        connection.execute('UPDATE warehouses SET auto_replenishment_enabled=0 WHERE auto_replenishment_enabled<>0')
        connection.execute("""CREATE TRIGGER IF NOT EXISTS retired_auto_pr_insert BEFORE INSERT ON purchase_requisitions
            WHEN NEW.auto_generated<>0 OR NEW.pr_source='AUTO_REPLENISHMENT'
            BEGIN SELECT RAISE(ABORT,'Use Stock Replenishment Check to create a reviewed PR'); END""")
        connection.execute("""CREATE TRIGGER IF NOT EXISTS retired_auto_pr_update BEFORE UPDATE OF auto_generated,pr_source ON purchase_requisitions
            WHEN (NEW.auto_generated<>0 AND OLD.auto_generated=0) OR (NEW.pr_source='AUTO_REPLENISHMENT' AND OLD.pr_source<>'AUTO_REPLENISHMENT')
            BEGIN SELECT RAISE(ABORT,'Automatic PR generation is retired'); END""")
        connection.execute("""CREATE TRIGGER IF NOT EXISTS retired_warehouse_auto_pr_insert AFTER INSERT ON warehouses
            WHEN NEW.auto_replenishment_enabled<>0 BEGIN UPDATE warehouses SET auto_replenishment_enabled=0 WHERE id=NEW.id; END""")
        connection.execute("""CREATE TRIGGER IF NOT EXISTS retired_warehouse_auto_pr_update BEFORE UPDATE OF auto_replenishment_enabled ON warehouses
            WHEN NEW.auto_replenishment_enabled<>0 BEGIN SELECT RAISE(ABORT,'Automatic PR scheduling is retired'); END""")
        for table in ('replenishment_cycles','replenishment_runs'):
            connection.execute(f"""CREATE TRIGGER IF NOT EXISTS retired_{table}_insert BEFORE INSERT ON {table}
                BEGIN SELECT RAISE(ABORT,'Use Stock Replenishment Check'); END""")
        company_columns = {row['name'] for row in connection.execute('PRAGMA table_info(company)')}
        if {'currency', 'base_currency'} <= company_columns:
            connection.execute(
                "UPDATE company SET currency=upper(trim(base_currency)) "
                "WHERE trim(COALESCE(base_currency,''))<>'' "
                "AND upper(trim(COALESCE(currency,'')))<>upper(trim(base_currency))"
            )
        connection.execute("""CREATE TABLE IF NOT EXISTS delegated_authorities(
            id INTEGER PRIMARY KEY AUTOINCREMENT,delegation_number TEXT NOT NULL UNIQUE,
            delegator_employee_id INTEGER NOT NULL REFERENCES employees(id),delegate_employee_id INTEGER NOT NULL REFERENCES employees(id),
            delegate_role TEXT NOT NULL,authority_type TEXT NOT NULL,scope_type TEXT NOT NULL,scope_id INTEGER,
            effective_from TEXT NOT NULL,effective_until TEXT NOT NULL,reason TEXT NOT NULL,business_justification TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE',created_by INTEGER NOT NULL REFERENCES users(id),created_at TEXT NOT NULL DEFAULT(datetime('now')),
            revoked_by INTEGER REFERENCES users(id),revoked_at TEXT,revocation_reason TEXT)""")
        delegation_sql=(connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='delegated_authorities'").fetchone()or{'sql':''})['sql']or''
        if "authority_type='FINANCE_EXTERNAL_HANDOFF'" in delegation_sql:
            connection.execute('ALTER TABLE delegated_authorities RENAME TO delegated_authorities_legacy')
            connection.execute("""CREATE TABLE delegated_authorities(
                id INTEGER PRIMARY KEY AUTOINCREMENT,delegation_number TEXT NOT NULL UNIQUE,
                delegator_employee_id INTEGER NOT NULL REFERENCES employees(id),delegate_employee_id INTEGER NOT NULL REFERENCES employees(id),
                delegate_role TEXT NOT NULL,authority_type TEXT NOT NULL,scope_type TEXT NOT NULL,scope_id INTEGER,
                effective_from TEXT NOT NULL,effective_until TEXT NOT NULL,reason TEXT NOT NULL,business_justification TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE',created_by INTEGER NOT NULL REFERENCES users(id),created_at TEXT NOT NULL DEFAULT(datetime('now')),
                revoked_by INTEGER REFERENCES users(id),revoked_at TEXT,revocation_reason TEXT)""")
            connection.execute("""INSERT INTO delegated_authorities(id,delegation_number,delegator_employee_id,delegate_employee_id,delegate_role,authority_type,scope_type,scope_id,effective_from,effective_until,reason,business_justification,status,created_by,created_at,revoked_by,revoked_at,revocation_reason)
              SELECT id,delegation_number,delegator_employee_id,delegate_employee_id,delegate_role,authority_type,scope_type,scope_id,effective_from,effective_until,reason,business_justification,status,created_by,created_at,revoked_by,revoked_at,revocation_reason FROM delegated_authorities_legacy""")
            connection.execute('DROP TABLE delegated_authorities_legacy')
        delegation_columns={row['name'] for row in connection.execute('PRAGMA table_info(delegated_authorities)')}
        for column,definition in {
            'employee_role_snapshot':'TEXT','department':'TEXT','reason_code':'TEXT','reason_other':'TEXT','updated_at':'TEXT',
        }.items():
            if column not in delegation_columns:connection.execute(f'ALTER TABLE delegated_authorities ADD COLUMN {column} {definition}')
        connection.execute("""CREATE TABLE IF NOT EXISTS delegated_authority_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,delegation_id INTEGER NOT NULL REFERENCES delegated_authorities(id),
            event_type TEXT NOT NULL,previous_expiry TEXT,new_expiry TEXT,reason TEXT,changed_by INTEGER NOT NULL REFERENCES users(id),
            changed_at TEXT NOT NULL DEFAULT(datetime('now')),details_json TEXT)""")
        connection.execute("""CREATE TABLE IF NOT EXISTS delegated_authority_uses(
            id INTEGER PRIMARY KEY AUTOINCREMENT,delegation_id INTEGER NOT NULL REFERENCES delegated_authorities(id),
            authority_code TEXT NOT NULL,performed_by INTEGER NOT NULL REFERENCES users(id),table_name TEXT NOT NULL,record_id INTEGER,
            action TEXT NOT NULL,normal_role TEXT,delegated_by_employee_id INTEGER REFERENCES employees(id),used_at TEXT NOT NULL DEFAULT(datetime('now')),
            context_json TEXT)""")
        history_sql=(connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='delegated_authority_history'").fetchone()or{'sql':''})['sql']or''
        if 'delegated_authorities_legacy' in history_sql:
            connection.execute('ALTER TABLE delegated_authority_history RENAME TO delegated_authority_history_broken')
            connection.execute("""CREATE TABLE delegated_authority_history(id INTEGER PRIMARY KEY AUTOINCREMENT,delegation_id INTEGER NOT NULL REFERENCES delegated_authorities(id),event_type TEXT NOT NULL,previous_expiry TEXT,new_expiry TEXT,reason TEXT,changed_by INTEGER NOT NULL REFERENCES users(id),changed_at TEXT NOT NULL DEFAULT(datetime('now')),details_json TEXT)""")
            connection.execute('INSERT INTO delegated_authority_history SELECT * FROM delegated_authority_history_broken');connection.execute('DROP TABLE delegated_authority_history_broken')
        uses_sql=(connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='delegated_authority_uses'").fetchone()or{'sql':''})['sql']or''
        if 'delegated_authorities_legacy' in uses_sql:
            connection.execute('ALTER TABLE delegated_authority_uses RENAME TO delegated_authority_uses_broken')
            connection.execute("""CREATE TABLE delegated_authority_uses(id INTEGER PRIMARY KEY AUTOINCREMENT,delegation_id INTEGER NOT NULL REFERENCES delegated_authorities(id),authority_code TEXT NOT NULL,performed_by INTEGER NOT NULL REFERENCES users(id),table_name TEXT NOT NULL,record_id INTEGER,action TEXT NOT NULL,normal_role TEXT,delegated_by_employee_id INTEGER REFERENCES employees(id),used_at TEXT NOT NULL DEFAULT(datetime('now')),context_json TEXT)""")
            connection.execute('INSERT INTO delegated_authority_uses SELECT * FROM delegated_authority_uses_broken');connection.execute('DROP TABLE delegated_authority_uses_broken')
        connection.execute('CREATE INDEX IF NOT EXISTS idx_delegation_delegate_period ON delegated_authorities(delegate_employee_id,authority_type,effective_from,effective_until)')
        connection.execute("""CREATE TRIGGER IF NOT EXISTS prevent_duplicate_supplier_invoice
            BEFORE INSERT ON invoices WHEN EXISTS(
              SELECT 1 FROM invoices WHERE supplier_id=NEW.supplier_id
              AND lower(trim(invoice_number))=lower(trim(NEW.invoice_number)))
            BEGIN SELECT RAISE(ABORT,'duplicate supplier invoice number'); END""")
        pr_columns = {row["name"] for row in connection.execute("PRAGMA table_info(purchase_requisitions)")}
        if "business_requestor_employee_id" not in pr_columns:
            connection.execute(
                "ALTER TABLE purchase_requisitions ADD COLUMN business_requestor_employee_id INTEGER REFERENCES employees(id)"
            )
        grn_columns = {row["name"] for row in connection.execute("PRAGMA table_info(grns)")}
        if "received_for_employee_id" not in grn_columns:
            connection.execute(
                "ALTER TABLE grns ADD COLUMN received_for_employee_id INTEGER REFERENCES employees(id)"
            )
        rfq_columns = {row["name"] for row in connection.execute("PRAGMA table_info(rfqs)")}
        for column, definition in {
            "workflow_status": "TEXT NOT NULL DEFAULT 'Draft'", "issue_date": "TEXT", "closing_date": "TEXT",
            "required_delivery_date": "TEXT", "delivery_warehouse_id": "INTEGER REFERENCES warehouses(id)",
            "delivery_location_id": "INTEGER REFERENCES locations(id)", "currency": "TEXT", "payment_terms": "TEXT",
            "incoterms": "TEXT", "contact_person": "TEXT", "notes": "TEXT", "commercial_terms": "TEXT",
            "technical_requirements": "TEXT", "created_by": "INTEGER REFERENCES users(id)", "updated_at": "TEXT",
        }.items():
            if column not in rfq_columns: connection.execute(f"ALTER TABLE rfqs ADD COLUMN {column} {definition}")
        invitation_columns = {row["name"] for row in connection.execute("PRAGMA table_info(rfq_suppliers)")}
        for column, definition in {"issued_at":"TEXT", "sent_method":"TEXT", "contact_person":"TEXT", "email":"TEXT", "response_status":"TEXT NOT NULL DEFAULT 'Invited'", "quotation_received_at":"TEXT"}.items():
            if column not in invitation_columns: connection.execute(f"ALTER TABLE rfq_suppliers ADD COLUMN {column} {definition}")
        quotation_columns = {row["name"] for row in connection.execute("PRAGMA table_info(supplier_quotations)")}
        for column, definition in {
            "quotation_number":"TEXT", "quotation_date":"TEXT", "validity_date":"TEXT", "quoted_quantity":"REAL",
            "discount":"REAL NOT NULL DEFAULT 0", "other_charges":"REAL NOT NULL DEFAULT 0", "delivery_date":"TEXT",
            "technical_compliance":"TEXT", "commercial_compliance":"TEXT", "country_of_origin":"TEXT", "remarks":"TEXT",
            "revision_number":"INTEGER NOT NULL DEFAULT 1", "superseded_by_id":"INTEGER REFERENCES supplier_quotations(id)",
            "active_yn":"INTEGER NOT NULL DEFAULT 1", "created_by":"INTEGER REFERENCES users(id)", "created_at":"TEXT",
        }.items():
            if column not in quotation_columns: connection.execute(f"ALTER TABLE supplier_quotations ADD COLUMN {column} {definition}")
        connection.execute("""CREATE TABLE IF NOT EXISTS rfq_awards(
            id INTEGER PRIMARY KEY AUTOINCREMENT,rfq_id INTEGER NOT NULL REFERENCES rfqs(id),quotation_id INTEGER NOT NULL REFERENCES supplier_quotations(id),
            supplier_id INTEGER NOT NULL REFERENCES suppliers(id),item_id INTEGER NOT NULL REFERENCES items(id),awarded_quantity REAL NOT NULL CHECK(awarded_quantity>0),
            recommendation_reason TEXT NOT NULL,non_lowest_justification TEXT,status TEXT NOT NULL DEFAULT 'Awaiting Approval',recommended_by INTEGER NOT NULL REFERENCES users(id),
            recommended_at TEXT NOT NULL DEFAULT(datetime('now')),approved_by INTEGER REFERENCES users(id),approved_at TEXT,rejection_reason TEXT,po_id INTEGER REFERENCES purchase_orders(id),
            UNIQUE(rfq_id,item_id,supplier_id))""")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_rfq_awards_status ON rfq_awards(rfq_id,status)")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_active_supplier_quote_line ON supplier_quotations(rfq_id,supplier_id,item_id) WHERE active_yn=1")
        supplier_columns = {row["name"] for row in connection.execute("PRAGMA table_info(suppliers)")}
        for column, definition in {"active_yn":"INTEGER NOT NULL DEFAULT 1", "blocked_yn":"INTEGER NOT NULL DEFAULT 0", "vendor_category":"TEXT"}.items():
            if column not in supplier_columns: connection.execute(f"ALTER TABLE suppliers ADD COLUMN {column} {definition}")
        award_columns = {row["name"] for row in connection.execute("PRAGMA table_info(rfq_awards)")}
        for column, definition in {
            "approval_limit_snapshot":"REAL", "effective_limit_source":"TEXT", "external_approval_required":"INTEGER NOT NULL DEFAULT 0",
            "external_approved_by":"TEXT", "external_approval_reference":"TEXT", "external_approval_date":"TEXT", "external_approval_notes":"TEXT"
        }.items():
            if column not in award_columns: connection.execute(f"ALTER TABLE rfq_awards ADD COLUMN {column} {definition}")
        po_item_columns = {row["name"] for row in connection.execute("PRAGMA table_info(po_items)")}
        for column, definition in {
            "quotation_id":"INTEGER REFERENCES supplier_quotations(id)", "discount":"REAL NOT NULL DEFAULT 0", "freight":"REAL NOT NULL DEFAULT 0",
            "other_charges":"REAL NOT NULL DEFAULT 0", "delivery_date":"TEXT", "warranty":"TEXT", "technical_specifications":"TEXT"
        }.items():
            if column not in po_item_columns: connection.execute(f"ALTER TABLE po_items ADD COLUMN {column} {definition}")
        po_columns = {row["name"] for row in connection.execute("PRAGMA table_info(purchase_orders)")}
        if "delivery_warehouse_id" not in po_columns:
            connection.execute("ALTER TABLE purchase_orders ADD COLUMN delivery_warehouse_id INTEGER REFERENCES warehouses(id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_purchase_orders_delivery_warehouse ON purchase_orders(delivery_warehouse_id,status)")
        quantity_snapshots = {
            'pr_items': {'transaction_quantity':'REAL','transaction_uom':'TEXT','conversion_factor_used':'REAL','base_quantity':'REAL','base_uom':'TEXT'},
            'po_items': {'transaction_quantity':'REAL','transaction_uom':'TEXT','conversion_factor_used':'REAL','base_quantity':'REAL','base_uom':'TEXT','line_amount':'REAL','tax_amount':'REAL','line_total':'REAL'},
            'grn_items': {'transaction_uom':'TEXT','conversion_factor_used':'REAL','received_base_quantity':'REAL','accepted_base_quantity':'REAL','rejected_base_quantity':'REAL','base_uom':'TEXT','inventory_unit_cost':'REAL','inventory_value':'REAL'},
            'material_issue_items': {'transaction_quantity':'REAL','transaction_uom':'TEXT','conversion_factor_used':'REAL','base_quantity':'REAL','base_uom':'TEXT'},
            'returns': {'transaction_quantity':'REAL','transaction_uom':'TEXT','conversion_factor_used':'REAL','base_quantity':'REAL','base_uom':'TEXT','unit_cost':'REAL','return_value':'REAL','inventory_status':'TEXT'},
        }
        for table, definitions in quantity_snapshots.items():
            existing = {row['name'] for row in connection.execute(f'PRAGMA table_info({table})')}
            for column, definition in definitions.items():
                if column not in existing:connection.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
        connection.execute("""CREATE TABLE IF NOT EXISTS employee_return_allocations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,return_id INTEGER NOT NULL REFERENCES returns(id),
            issue_item_id INTEGER NOT NULL REFERENCES material_issue_items(id),transaction_quantity REAL NOT NULL,
            base_quantity REAL NOT NULL,unit_cost REAL NOT NULL,value REAL NOT NULL,
            UNIQUE(return_id,issue_item_id))""")
        connection.execute('CREATE INDEX IF NOT EXISTS idx_return_allocations_issue ON employee_return_allocations(issue_item_id)')
        for name in (
            "Production", "Laboratory", "Quality", "Engineering", "Maintenance",
            "HSE", "Planning", "Finance", "Human Resources", "Administration",
            "Logistics", "Sales & Commercial", "Information Technology", "Management",
        ):
            connection.execute(
                "INSERT INTO departments(name) SELECT ? WHERE NOT EXISTS "
                "(SELECT 1 FROM departments WHERE lower(trim(name))=lower(trim(?)) AND deleted_at IS NULL)",
                (name, name),
            )
        warehouse_columns = {row["name"] for row in connection.execute("PRAGMA table_info(warehouses)")}
        if "operating_start_time" not in warehouse_columns:
            connection.execute("ALTER TABLE warehouses ADD COLUMN operating_start_time TEXT NOT NULL DEFAULT '03:00'")
        if "operating_end_time" not in warehouse_columns:
            connection.execute("ALTER TABLE warehouses ADD COLUMN operating_end_time TEXT NOT NULL DEFAULT '03:00'")
        if "time_zone" not in warehouse_columns:
            connection.execute("ALTER TABLE warehouses ADD COLUMN time_zone TEXT NOT NULL DEFAULT 'Asia/Riyadh'")
        if "operating_days_json" not in warehouse_columns:
            connection.execute("ALTER TABLE warehouses ADD COLUMN operating_days_json TEXT NOT NULL DEFAULT '[0,1,2,3,4,5,6]'")
        if "operation_24h_yn" not in warehouse_columns:
            connection.execute("ALTER TABLE warehouses ADD COLUMN operation_24h_yn INTEGER NOT NULL DEFAULT 0")
        if "shifts_enabled_yn" not in warehouse_columns:
            connection.execute("ALTER TABLE warehouses ADD COLUMN shifts_enabled_yn INTEGER NOT NULL DEFAULT 1")
        shift_columns = {row["name"] for row in connection.execute("PRAGMA table_info(shifts)")}
        if "warehouse_id" not in shift_columns:
            connection.execute("ALTER TABLE shifts ADD COLUMN warehouse_id INTEGER REFERENCES warehouses(id)")
        if "schedule_mode" not in shift_columns:
            connection.execute("ALTER TABLE shifts ADD COLUMN schedule_mode TEXT NOT NULL DEFAULT 'MULTI'")
        connection.execute("""CREATE TABLE IF NOT EXISTS warehouse_deactivation_reports(
            id INTEGER PRIMARY KEY AUTOINCREMENT,report_number TEXT NOT NULL UNIQUE,warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
            warehouse_code TEXT NOT NULL,warehouse_name TEXT NOT NULL,deactivation_reason TEXT NOT NULL,stock_quantity REAL NOT NULL DEFAULT 0,
            fifo_quantity REAL NOT NULL DEFAULT 0,open_task_count INTEGER NOT NULL DEFAULT 0,snapshot_json TEXT NOT NULL,
            deactivated_by INTEGER NOT NULL REFERENCES users(id),deactivated_at TEXT NOT NULL DEFAULT(datetime('now')),
            created_at TEXT NOT NULL DEFAULT(datetime('now')))""")
        connection.execute('CREATE INDEX IF NOT EXISTS idx_warehouse_deactivation_reports_warehouse ON warehouse_deactivation_reports(warehouse_id,deactivated_at)')
        templates = connection.execute("SELECT * FROM shifts WHERE warehouse_id IS NULL AND active_yn=1 ORDER BY start_time,id").fetchall()
        for warehouse in connection.execute("SELECT id FROM warehouses WHERE deleted_at IS NULL").fetchall():
            if connection.execute("SELECT 1 FROM shifts WHERE warehouse_id=? LIMIT 1", (warehouse["id"],)).fetchone():
                continue
            for sequence, template in enumerate(templates, 1):
                connection.execute("""INSERT INTO shifts(shift_code,shift_label,start_time,end_time,cross_midnight_yn,break_minutes,
                    department_scope,active_yn,warehouse_id) VALUES(?,?,?,?,?,?,?,1,?)""",
                    (f"WH{warehouse['id']}-{template['shift_code']}", template['shift_label'], template['start_time'], template['end_time'],
                     template['cross_midnight_yn'], template['break_minutes'], 'Warehouse', warehouse['id']))
        connection.execute("""CREATE TABLE IF NOT EXISTS item_categories(
            id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL COLLATE NOCASE UNIQUE,active_yn INTEGER NOT NULL DEFAULT 1,
            created_by INTEGER REFERENCES users(id),created_at TEXT NOT NULL DEFAULT(datetime('now')))""")
        connection.execute("""CREATE TABLE IF NOT EXISTS item_subcategories(
            id INTEGER PRIMARY KEY AUTOINCREMENT,category_id INTEGER NOT NULL REFERENCES item_categories(id),
            name TEXT NOT NULL COLLATE NOCASE,active_yn INTEGER NOT NULL DEFAULT 1,created_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT(datetime('now')),UNIQUE(category_id,name))""")
        connection.execute("""CREATE TABLE IF NOT EXISTS warehouse_operating_schedules(
            id INTEGER PRIMARY KEY AUTOINCREMENT,warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 6),
            is_open INTEGER NOT NULL DEFAULT 1,open_time TEXT,close_time TEXT,cross_midnight_yn INTEGER NOT NULL DEFAULT 0,
            created_by INTEGER REFERENCES users(id),created_at TEXT NOT NULL DEFAULT(datetime('now')),updated_by INTEGER REFERENCES users(id),updated_at TEXT,
            UNIQUE(warehouse_id,weekday))""")
        for warehouse in connection.execute('SELECT id,operating_start_time,operating_end_time,operating_days_json,operation_24h_yn FROM warehouses WHERE deleted_at IS NULL').fetchall():
            try:operating_days={int(value)for value in __import__('json').loads(warehouse['operating_days_json']or'[]')}
            except (TypeError,ValueError):operating_days=set(range(7))
            for weekday in range(7):
                is_open=int(bool(weekday in operating_days));opening='00:00'if warehouse['operation_24h_yn']else warehouse['operating_start_time']if is_open else None;closing='00:00'if warehouse['operation_24h_yn']else warehouse['operating_end_time']if is_open else None
                connection.execute('INSERT OR IGNORE INTO warehouse_operating_schedules(warehouse_id,weekday,is_open,open_time,close_time,cross_midnight_yn)VALUES(?,?,?,?,?,?)',(warehouse['id'],weekday,is_open,opening,closing,int(bool(is_open and closing<=opening))))
        calendar_columns={row['name'] for row in connection.execute('PRAGMA table_info(employee_work_calendar)')}
        for column,definition in {'warehouse_time_zone':'TEXT','warehouse_open_time':'TEXT','warehouse_close_time':'TEXT'}.items():
            if column not in calendar_columns:connection.execute(f'ALTER TABLE employee_work_calendar ADD COLUMN {column} {definition}')
        holiday_columns={row['name'] for row in connection.execute('PRAGMA table_info(holidays)')}
        holiday_additions={'region':'TEXT','observed_date':'TEXT','calendar_year':'INTEGER','day_scope':'TEXT NOT NULL DEFAULT \'FULL_DAY\'','start_time':'TEXT','end_time':'TEXT','applicability':'TEXT NOT NULL DEFAULT \'WAREHOUSE\'','notes':'TEXT'}
        for column,definition in holiday_additions.items():
            if column not in holiday_columns:connection.execute(f'ALTER TABLE holidays ADD COLUMN {column} {definition}')
        for column,definition in {'holiday_end_date':'TEXT','procurement_work_required':'INTEGER NOT NULL DEFAULT 0','procurement_work_reason':'TEXT','warehouse_id':'INTEGER REFERENCES warehouses(id)'}.items():
            if column not in holiday_columns:connection.execute(f'ALTER TABLE holidays ADD COLUMN {column} {definition}')
        exchange_columns={row['name'] for row in connection.execute('PRAGMA table_info(exchange_rates)')}
        for column,definition in {'synchronized_at':'TEXT','synchronized_by':'INTEGER REFERENCES users(id)'}.items():
            if column not in exchange_columns:connection.execute(f'ALTER TABLE exchange_rates ADD COLUMN {column} {definition}')
        connection.execute("""CREATE TABLE IF NOT EXISTS holiday_work_exceptions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,holiday_id INTEGER NOT NULL REFERENCES holidays(id),warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
            employee_id INTEGER REFERENCES employees(id),shift_id INTEGER REFERENCES shifts(id),work_required INTEGER NOT NULL DEFAULT 1,reason TEXT NOT NULL,
            approved_by INTEGER NOT NULL REFERENCES users(id),approved_at TEXT NOT NULL DEFAULT(datetime('now')),created_at TEXT NOT NULL DEFAULT(datetime('now')),
            UNIQUE(holiday_id,warehouse_id,employee_id,shift_id))""")
        connection.execute("""CREATE TABLE IF NOT EXISTS system_maintenance(
            id INTEGER PRIMARY KEY CHECK(id=1),active_yn INTEGER NOT NULL DEFAULT 0,reason TEXT,cycle_id TEXT,scheduled_at_utc TEXT,
            started_at TEXT,completed_at TEXT,result TEXT,session_epoch INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL DEFAULT(datetime('now')))""")
        connection.execute("INSERT OR IGNORE INTO system_maintenance(id)VALUES(1)")
        connection.execute("""CREATE TABLE IF NOT EXISTS backup_cycles(
            id INTEGER PRIMARY KEY AUTOINCREMENT,cycle_id TEXT NOT NULL UNIQUE,scheduled_at_utc TEXT NOT NULL,backup_time_zone TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'SCHEDULED',warning_30_at TEXT,warning_20_at TEXT,warning_10_at TEXT,started_at TEXT,completed_at TEXT,
            backup_reference TEXT,verification_result TEXT,error_message TEXT,created_at TEXT NOT NULL DEFAULT(datetime('now')),updated_at TEXT NOT NULL DEFAULT(datetime('now')))""")
        notification_columns={row['name'] for row in connection.execute('PRAGMA table_info(notifications)')}
        if 'event_key' not in notification_columns:connection.execute('ALTER TABLE notifications ADD COLUMN event_key TEXT')
        if 'expires_at' not in notification_columns:connection.execute('ALTER TABLE notifications ADD COLUMN expires_at TEXT')
        connection.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_event_user ON notifications(event_key,user_id) WHERE event_key IS NOT NULL')
        defaults={'automatic_month_end_backup':'1','backup_time':'16:00','backup_time_zone':'Asia/Riyadh','backup_warning_minutes':'30','backup_reminder_minutes':'10',
            'procurement_shifts_enabled':'1','procurement_operating_start_time':'08:00','procurement_operating_end_time':'17:00','procurement_operating_days':'[0,1,2,3,4]'}
        for key,value in defaults.items():connection.execute('INSERT OR IGNORE INTO settings(key,value)VALUES(?,?)',(key,value))
        shift_mode_initialized=connection.execute("SELECT 1 FROM settings WHERE key='shift_mode_initialized'").fetchone()
        if not shift_mode_initialized:
            connection.execute("INSERT INTO settings(key,value)VALUES('procurement_shifts_enabled','1')ON CONFLICT(key)DO UPDATE SET value='1'")
        procurement_start=(connection.execute("SELECT value FROM settings WHERE key='procurement_operating_start_time'").fetchone()or{'value':'08:00'})['value'];procurement_end=(connection.execute("SELECT value FROM settings WHERE key='procurement_operating_end_time'").fetchone()or{'value':'17:00'})['value'];procurement_enabled=(connection.execute("SELECT value FROM settings WHERE key='procurement_shifts_enabled'").fetchone()or{'value':'0'})['value']=='1'
        psh,psm=map(int,procurement_start[:5].split(':'));peh,pem=map(int,procurement_end[:5].split(':'));procurement_duration=((peh*60+pem)-(psh*60+psm))%1440 or 1440;procurement_break=30 if procurement_duration>=360 else(15 if procurement_duration>=240 else 0);procurement_finish=(peh*60+pem)%1440;procurement_scheduled_end=f'{procurement_finish//60:02d}:{procurement_finish%60:02d}'
        connection.execute("""INSERT OR IGNORE INTO shifts(shift_code,shift_label,start_time,end_time,cross_midnight_yn,break_minutes,department_scope,active_yn,warehouse_id,schedule_mode)
          VALUES('PROC-STANDARD','Procurement Standard Hours',?,?,?,?,'Procurement',?,NULL,'STANDARD')""",(procurement_start,procurement_scheduled_end,int(psh*60+psm+procurement_duration>=1440),procurement_break,int(not procurement_enabled)))
        connection.execute("UPDATE shifts SET active_yn=? WHERE warehouse_id IS NULL AND schedule_mode='MULTI'",(int(procurement_enabled),))
        connection.execute("UPDATE shifts SET start_time=?,end_time=?,cross_midnight_yn=?,break_minutes=?,active_yn=? WHERE warehouse_id IS NULL AND schedule_mode='STANDARD'",(procurement_start,procurement_scheduled_end,int(psh*60+psm+procurement_duration>=1440),procurement_break,int(not procurement_enabled)))
        for warehouse in connection.execute('SELECT id,operating_start_time,operating_end_time,shifts_enabled_yn FROM warehouses WHERE deleted_at IS NULL').fetchall():
            start=warehouse['operating_start_time'];end=warehouse['operating_end_time'];enabled=bool(warehouse['shifts_enabled_yn'])
            sh,sm=map(int,start[:5].split(':'));eh,em=map(int,end[:5].split(':'));duration=((eh*60+em)-(sh*60+sm))%1440 or 1440
            standard_break=30 if duration>=360 else(15 if duration>=240 else 0);scheduled_finish=(eh*60+em)%1440;scheduled_end=f'{scheduled_finish//60:02d}:{scheduled_finish%60:02d}'
            connection.execute("""INSERT OR IGNORE INTO shifts(shift_code,shift_label,start_time,end_time,cross_midnight_yn,break_minutes,department_scope,active_yn,warehouse_id,schedule_mode)
              VALUES(?,?,?, ?,?,?,'Warehouse',?,?,'STANDARD')""",(f"WH{warehouse['id']}-STANDARD",'Standard Operating Hours',start,scheduled_end,int(sh*60+sm+duration>=1440),standard_break,int(not enabled),warehouse['id']))
            connection.execute("UPDATE shifts SET start_time=?,end_time=?,cross_midnight_yn=?,break_minutes=?,active_yn=? WHERE warehouse_id=? AND schedule_mode='STANDARD'",(start,scheduled_end,int(sh*60+sm+duration>=1440),standard_break,int(not enabled),warehouse['id']))
            if not shift_mode_initialized:
                rows=list(connection.execute("SELECT id FROM shifts WHERE warehouse_id=? AND schedule_mode='MULTI' ORDER BY ((CAST(substr(start_time,1,2) AS INTEGER)*60+CAST(substr(start_time,4,2) AS INTEGER))-(?)+1440)%1440,id",(warehouse['id'],sh*60+sm)).fetchall())
                count=(duration+479)//480
                for index,row in enumerate(rows):
                    if index<count:
                        block=sh*60+sm+index*480;minutes=min(480,duration-index*480);break_minutes=30 if minutes>=360 else(15 if minutes>=240 else 0);finish=(block+minutes)%1440
                        connection.execute('UPDATE shifts SET start_time=?,end_time=?,cross_midnight_yn=?,break_minutes=?,active_yn=? WHERE id=?',(f'{(block%1440)//60:02d}:{block%60:02d}',f'{finish//60:02d}:{finish%60:02d}',int((block%1440)+minutes>=1440),break_minutes,int(enabled),row['id']))
                    else:connection.execute('UPDATE shifts SET active_yn=0 WHERE id=?',(row['id'],))
        if not shift_mode_initialized:connection.execute("INSERT INTO settings(key,value)VALUES('shift_mode_initialized','1')")
        coverage_repaired=connection.execute("SELECT 1 FROM settings WHERE key='shift_mode_coverage_repaired_v2'").fetchone()
        if not coverage_repaired:
            for warehouse in connection.execute('SELECT id,operating_start_time,operating_end_time,shifts_enabled_yn FROM warehouses WHERE deleted_at IS NULL AND shifts_enabled_yn=1').fetchall():
                start=warehouse['operating_start_time'];end=warehouse['operating_end_time'];sh,sm=map(int,start[:5].split(':'));eh,em=map(int,end[:5].split(':'));duration=((eh*60+em)-(sh*60+sm))%1440 or 1440;count=(duration+479)//480
                rows=list(connection.execute("SELECT id FROM shifts WHERE warehouse_id=? AND schedule_mode='MULTI' ORDER BY ((CAST(substr(start_time,1,2) AS INTEGER)*60+CAST(substr(start_time,4,2) AS INTEGER))-(?)+1440)%1440,id",(warehouse['id'],sh*60+sm)).fetchall())
                for index,row in enumerate(rows):
                    if index<count:
                        block=sh*60+sm+index*480;minutes=min(480,duration-index*480);break_minutes=30 if minutes>=360 else(15 if minutes>=240 else 0);finish=(block+minutes)%1440
                        connection.execute('UPDATE shifts SET start_time=?,end_time=?,cross_midnight_yn=?,break_minutes=?,active_yn=1 WHERE id=?',(f'{(block%1440)//60:02d}:{block%60:02d}',f'{finish//60:02d}:{finish%60:02d}',int((block%1440)+minutes>=1440),break_minutes,row['id']))
                    else:connection.execute('UPDATE shifts SET active_yn=0 WHERE id=?',(row['id'],))
            connection.execute("INSERT INTO settings(key,value)VALUES('shift_mode_coverage_repaired_v2','1')")
        break_end_migrated=connection.execute("SELECT 1 FROM settings WHERE key='break_inclusive_shift_end_v1'").fetchone()
        if not break_end_migrated:
            connection.execute("UPDATE employee_work_calendar SET shift_end=(SELECT end_time FROM shifts WHERE shifts.id=employee_work_calendar.shift_id) WHERE shift_id IS NOT NULL AND calendar_date>=date('now') AND manual_override_yn=0")
            connection.execute("INSERT INTO settings(key,value)VALUES('break_inclusive_shift_end_v1','1')")
        active_count_repaired=connection.execute("SELECT 1 FROM settings WHERE key='shift_active_count_repaired_v3'").fetchone()
        if not active_count_repaired:
            for warehouse in connection.execute('SELECT id,operating_start_time,operating_end_time,shifts_enabled_yn FROM warehouses WHERE deleted_at IS NULL').fetchall():
                sh,sm=map(int,warehouse['operating_start_time'][:5].split(':'));eh,em=map(int,warehouse['operating_end_time'][:5].split(':'));duration=((eh*60+em)-(sh*60+sm))%1440 or 1440;count=(duration+479)//480
                rows=list(connection.execute("SELECT id FROM shifts WHERE warehouse_id=? AND schedule_mode='MULTI' ORDER BY ((CAST(substr(start_time,1,2) AS INTEGER)*60+CAST(substr(start_time,4,2) AS INTEGER))-(?)+1440)%1440,id",(warehouse['id'],sh*60+sm)).fetchall())
                for index,row in enumerate(rows):connection.execute('UPDATE shifts SET active_yn=? WHERE id=?',(int(bool(warehouse['shifts_enabled_yn'])and index<count),row['id']))
            connection.execute("INSERT INTO settings(key,value)VALUES('shift_active_count_repaired_v3','1')")
        overlap_design_migrated=connection.execute("SELECT 1 FROM settings WHERE key='two_hour_overlap_shift_design_v5'").fetchone()
        if not overlap_design_migrated:
            for warehouse in connection.execute('SELECT id,operating_start_time,operating_end_time,shifts_enabled_yn FROM warehouses WHERE deleted_at IS NULL').fetchall():
                if not warehouse['shifts_enabled_yn']:continue
                start=warehouse['operating_start_time'];sh,sm=map(int,start[:5].split(':'));eh,em=map(int,warehouse['operating_end_time'][:5].split(':'));duration=((eh*60+em)-(sh*60+sm))%1440 or 1440;offset=0;design=[]
                while True:
                    working=duration if duration<=480 else 480;break_minutes=30 if working>=360 else(15 if working>=240 else 0);scheduled=working;finish=(sh*60+sm+offset+scheduled)%1440
                    design.append((f'{((sh*60+sm+offset)%1440)//60:02d}:{(sh*60+sm+offset)%60:02d}',f'{finish//60:02d}:{finish%60:02d}',int((sh*60+sm+offset)%1440+scheduled>=1440),break_minutes))
                    if offset+working>=duration:break
                    offset+=scheduled-120
                rows=list(connection.execute("SELECT id FROM shifts WHERE warehouse_id=? AND schedule_mode='MULTI' ORDER BY ((CAST(substr(start_time,1,2) AS INTEGER)*60+CAST(substr(start_time,4,2) AS INTEGER))-(?)+1440)%1440,id",(warehouse['id'],sh*60+sm)).fetchall())
                for index,values in enumerate(design):
                    if index<len(rows):connection.execute('UPDATE shifts SET start_time=?,end_time=?,cross_midnight_yn=?,break_minutes=?,active_yn=1 WHERE id=?',values+(rows[index]['id'],))
                    else:connection.execute("""INSERT INTO shifts(shift_code,shift_label,start_time,end_time,cross_midnight_yn,break_minutes,department_scope,active_yn,warehouse_id,schedule_mode)
                      VALUES(?,?,?,?,?,?,'Warehouse',1,?,'MULTI')""",(f"WH{warehouse['id']}-SHIFT-{index+1}",f'Shift {index+1}',*values,warehouse['id']))
                for row in rows[len(design):]:connection.execute('UPDATE shifts SET active_yn=0 WHERE id=?',(row['id'],))
            connection.execute("UPDATE employee_work_calendar SET shift_start=(SELECT start_time FROM shifts WHERE shifts.id=employee_work_calendar.shift_id),shift_end=(SELECT end_time FROM shifts WHERE shifts.id=employee_work_calendar.shift_id) WHERE shift_id IS NOT NULL AND calendar_date>=date('now') AND manual_override_yn=0")
            connection.execute("INSERT INTO settings(key,value)VALUES('two_hour_overlap_shift_design_v5','1')")
        close_aligned_design=connection.execute("SELECT 1 FROM settings WHERE key='warehouse_close_aligned_shift_design_v6'").fetchone()
        if not close_aligned_design:
            for warehouse in connection.execute('SELECT id,operating_start_time,operating_end_time,shifts_enabled_yn FROM warehouses WHERE deleted_at IS NULL').fetchall():
                if not warehouse['shifts_enabled_yn']:continue
                start=warehouse['operating_start_time'];sh,sm=map(int,start[:5].split(':'));eh,em=map(int,warehouse['operating_end_time'][:5].split(':'));duration=((eh*60+em)-(sh*60+sm))%1440 or 1440
                if duration<=480:break_minutes=30 if duration>=360 else(15 if duration>=240 else 0);offsets=[0];scheduled_lengths=[duration]
                else:
                    break_minutes=30;final_offset=duration-480;count=max(2,(final_offset+359)//360+1);offsets=[0]+[int(((sh*60+sm+index*final_offset/(count-1))+15)//30)*30-(sh*60+sm) for index in range(1,count-1)]+[final_offset];scheduled_lengths=[480]*count
                design=[]
                for offset,scheduled in zip(offsets,scheduled_lengths):
                    begin=sh*60+sm+offset;finish=begin+scheduled;design.append((f'{(begin%1440)//60:02d}:{begin%60:02d}',f'{(finish%1440)//60:02d}:{finish%60:02d}',int((begin%1440)+scheduled>=1440),break_minutes))
                rows=list(connection.execute("SELECT id FROM shifts WHERE warehouse_id=? AND schedule_mode='MULTI' ORDER BY ((CAST(substr(start_time,1,2) AS INTEGER)*60+CAST(substr(start_time,4,2) AS INTEGER))-(?)+1440)%1440,id",(warehouse['id'],sh*60+sm)).fetchall())
                for index,values in enumerate(design):
                    if index<len(rows):connection.execute('UPDATE shifts SET start_time=?,end_time=?,cross_midnight_yn=?,break_minutes=?,active_yn=1 WHERE id=?',values+(rows[index]['id'],))
                    else:connection.execute("""INSERT INTO shifts(shift_code,shift_label,start_time,end_time,cross_midnight_yn,break_minutes,department_scope,active_yn,warehouse_id,schedule_mode)
                      VALUES(?,?,?,?,?,?,'Warehouse',1,?,'MULTI')""",(f"WH{warehouse['id']}-SHIFT-{index+1}",f'Shift {index+1}',*values,warehouse['id']))
                for row in rows[len(design):]:connection.execute('UPDATE shifts SET active_yn=0 WHERE id=?',(row['id'],))
            connection.execute("UPDATE employee_work_calendar SET shift_start=(SELECT start_time FROM shifts WHERE shifts.id=employee_work_calendar.shift_id),shift_end=(SELECT end_time FROM shifts WHERE shifts.id=employee_work_calendar.shift_id) WHERE shift_id IS NOT NULL AND calendar_date>=date('now') AND manual_override_yn=0")
            connection.execute("INSERT INTO settings(key,value)VALUES('warehouse_close_aligned_shift_design_v6','1')")
        night_shift_labeled=connection.execute("SELECT 1 FROM settings WHERE key='warehouse_fourth_night_shift_label_v1'").fetchone()
        if not night_shift_labeled:
            for warehouse in connection.execute('SELECT id,operating_start_time FROM warehouses WHERE deleted_at IS NULL').fetchall():
                sh,sm=map(int,warehouse['operating_start_time'][:5].split(':'))
                rows=list(connection.execute("SELECT id FROM shifts WHERE warehouse_id=? AND schedule_mode='MULTI' ORDER BY ((CAST(substr(start_time,1,2) AS INTEGER)*60+CAST(substr(start_time,4,2) AS INTEGER))-(?)+1440)%1440,id",(warehouse['id'],sh*60+sm)).fetchall())
                if len(rows)>=4:connection.execute("UPDATE shifts SET shift_label='Night Shift' WHERE id=?",(rows[3]['id'],))
            connection.execute("INSERT INTO settings(key,value)VALUES('warehouse_fourth_night_shift_label_v1','1')")
        standardized_shift_starts=connection.execute("SELECT 1 FROM settings WHERE key='warehouse_half_hour_shift_starts_v7'").fetchone()
        if not standardized_shift_starts:
            for warehouse in connection.execute('SELECT id,operating_start_time,operating_end_time,shifts_enabled_yn FROM warehouses WHERE deleted_at IS NULL').fetchall():
                if not warehouse['shifts_enabled_yn']:continue
                start=warehouse['operating_start_time'];sh,sm=map(int,start[:5].split(':'));eh,em=map(int,warehouse['operating_end_time'][:5].split(':'));duration=((eh*60+em)-(sh*60+sm))%1440 or 1440
                if duration<=480:offsets=[0];scheduled_lengths=[duration];break_minutes=30 if duration>=360 else(15 if duration>=240 else 0)
                else:
                    break_minutes=30;final_offset=duration-480;count=max(2,(final_offset+359)//360+1);offsets=[0]+[int(((sh*60+sm+index*final_offset/(count-1))+15)//30)*30-(sh*60+sm) for index in range(1,count-1)]+[final_offset];scheduled_lengths=[480]*count
                rows=list(connection.execute("SELECT id FROM shifts WHERE warehouse_id=? AND schedule_mode='MULTI' ORDER BY ((CAST(substr(start_time,1,2) AS INTEGER)*60+CAST(substr(start_time,4,2) AS INTEGER))-(?)+1440)%1440,id",(warehouse['id'],sh*60+sm)).fetchall())
                labels=['First Shift','Second Shift','Third Shift','Night Shift']
                for index,(offset,scheduled) in enumerate(zip(offsets,scheduled_lengths)):
                    begin=sh*60+sm+offset;finish=begin+scheduled;values=(labels[index],f'{(begin%1440)//60:02d}:{begin%60:02d}',f'{(finish%1440)//60:02d}:{finish%60:02d}',int((begin%1440)+scheduled>=1440),break_minutes)
                    if index<len(rows):connection.execute('UPDATE shifts SET shift_label=?,start_time=?,end_time=?,cross_midnight_yn=?,break_minutes=?,active_yn=1 WHERE id=?',values+(rows[index]['id'],))
                for row in rows[len(offsets):]:connection.execute('UPDATE shifts SET active_yn=0 WHERE id=?',(row['id'],))
            connection.execute("UPDATE employee_work_calendar SET shift_start=(SELECT start_time FROM shifts WHERE shifts.id=employee_work_calendar.shift_id),shift_end=(SELECT end_time FROM shifts WHERE shifts.id=employee_work_calendar.shift_id) WHERE shift_id IS NOT NULL AND calendar_date>=date('now') AND manual_override_yn=0")
            connection.execute("INSERT INTO settings(key,value)VALUES('warehouse_half_hour_shift_starts_v7','1')")
        # Internal breaks do not extend shift boundaries. Preserve historical calendars.
        if 'work_periods_json' not in {row['name'] for row in connection.execute('PRAGMA table_info(employee_work_calendar)')}:
            connection.execute("ALTER TABLE employee_work_calendar ADD COLUMN work_periods_json TEXT")
        if not connection.execute("SELECT 1 FROM settings WHERE key='internal_shift_breaks_v1'").fetchone():
            corrected=[]
            for shift in connection.execute("SELECT * FROM shifts WHERE warehouse_id IS NULL AND schedule_mode='MULTI'").fetchall():
                sh,sm=map(int,shift['start_time'][:5].split(':'));eh,em=map(int,shift['end_time'][:5].split(':'))
                duration=((eh*60+em)-(sh*60+sm))%1440 or 1440
                if duration==480+int(shift['break_minutes']or 0):
                    finish=(sh*60+sm+480)%1440;end=f'{finish//60:02d}:{finish%60:02d}'
                    connection.execute('UPDATE shifts SET end_time=?,cross_midnight_yn=? WHERE id=?',(end,int(sh*60+sm+480>=1440),shift['id']))
                    corrected.append({'id':shift['id'],'previous_end':shift['end_time'],'end':end})
            connection.execute("UPDATE employee_work_calendar SET shift_end=(SELECT end_time FROM shifts WHERE shifts.id=employee_work_calendar.shift_id) WHERE shift_id IS NOT NULL AND calendar_date>=date('now') AND manual_override_yn=0 AND status<>'LOCKED'")
            connection.execute("INSERT INTO settings(key,value)VALUES('internal_shift_breaks_v1',?)",(json.dumps(corrected),))
        taxonomy = {
            'Raw Material':['Cement','Fine Aggregate / Sand','Coarse Aggregate','Admixture','Water','Steel','Reinforcement Steel','Steel Mesh','Prestressing Steel','Fibres','Inserts & Cast-in Items'],
            'Production Consumable':['Abrasive','Binding & Tying','Curing','Grout','Release Agent','Repair Material','Sealant','Spacers & Chairs','Steel Consumable','Welding','Formwork Consumable'],
            'PPE':['Head Protection','Eye Protection','Face Protection','Hearing Protection','Hand Protection','Foot Protection','Respiratory Protection','Fall Protection','Visibility','Protective Clothing'],
            'Tool':['Hand Tool','Power Tool','Measuring Tool','Cutting Tool','Concrete Tool','Rigging Tool','Welding Tool'],
            'Tools':['Hand Tools','Power Tools','Measuring Tools','Cutting Tools','Concrete Tools'],
            'Equipment':['Formwork','Moulds','Batching Plant','Concrete Vibrator','Lifting & Handling','Crane & Hoist','Generator','Compressor','Welding Equipment','Workshop Equipment'],
            'Electrical':['Cable & Wire','Temporary Power','Plug & Socket','Switchgear','Motor & Drive','Lighting','Insulation','Fastening','Electrical Spare'],
            'Mechanical':['Bearing','Belt & Chain','Pump','Valve','Hydraulic Component','Pneumatic Component','Machine Spare','Fabricated Part'],
            'Fastener':['Bolt & Nut','Washer','Anchor','Screw','Rivet','Threaded Rod','Clamp'],
            'Maintenance Consumable':['Lubricant','Chemical','Cleaning','Filter','Seal & Gasket','Workshop Consumable'],
            'Warehouse Consumable':['Pallet','Packaging','Labeling','Stationery','Storage Bin','Material Handling'],
            'QC / Laboratory':['Concrete Testing','Aggregate Testing','Cement Testing','Dimensional Inspection','Calibration Standard','Laboratory Consumable','Sample Preparation'],
            'Fuel & Lubricants':['Diesel','Petrol','Hydraulic Oil','Gear Oil','Engine Oil','Grease','Coolant'],
            'Chemicals':['Construction Chemical','Industrial Chemical','Water Treatment','Cleaning Chemical','Coating & Paint'],
            'Consumables':['Accessories','Lubricants','Cleaning','Packaging','General Consumable'],
            'Production':['Concrete','Reinforcement','Prestressing','Mould Preparation','Finishing'],
        }
        for row in connection.execute("SELECT DISTINCT trim(category) category,trim(subcategory) subcategory FROM items WHERE trim(COALESCE(category,''))<>''").fetchall():
            taxonomy.setdefault(row['category'],[])
            if row['subcategory'] and row['subcategory'] not in taxonomy[row['category']]:taxonomy[row['category']].append(row['subcategory'])
        for category,subcategories in taxonomy.items():
            connection.execute("INSERT OR IGNORE INTO item_categories(name)VALUES(?)",(category,))
            category_id=connection.execute("SELECT id FROM item_categories WHERE name=? COLLATE NOCASE",(category,)).fetchone()['id']
            for subcategory in subcategories:connection.execute("INSERT OR IGNORE INTO item_subcategories(category_id,name)VALUES(?,?)",(category_id,subcategory))
        for supplier in connection.execute('SELECT id FROM suppliers WHERE deleted_at IS NULL').fetchall():
            totals=connection.execute('SELECT COALESCE(SUM(gi.quantity_received),0) received,COALESCE(SUM(gi.accepted_qty),0) accepted FROM grn_items gi JOIN grns g ON g.id=gi.grn_id WHERE g.supplier_id=?',(supplier['id'],)).fetchone()
            delivery=connection.execute('SELECT COUNT(*) deliveries,SUM(CASE WHEN po.committed_delivery_date IS NOT NULL AND date(g.grn_date)<=date(po.committed_delivery_date) THEN 1 ELSE 0 END) on_time FROM grns g JOIN purchase_orders po ON po.id=g.po_id WHERE g.supplier_id=? AND po.committed_delivery_date IS NOT NULL',(supplier['id'],)).fetchone()
            ordered=connection.execute('SELECT COALESCE(SUM(pi.quantity),0) quantity FROM po_items pi JOIN purchase_orders po ON po.id=pi.po_id WHERE po.supplier_id=? AND EXISTS(SELECT 1 FROM grns g WHERE g.po_id=po.id)',(supplier['id'],)).fetchone()['quantity']
            received=float(totals['received']or 0);accepted=float(totals['accepted']or 0)
            rating=0 if not received else round(5*(min(1,accepted/received)*.45+min(1,accepted/float(ordered or accepted or 1))*.25+(float(delivery['on_time']or 0)/float(delivery['deliveries']or 1))*.30),2)
            connection.execute('UPDATE suppliers SET rating=? WHERE id=?',(rating,supplier['id']))
        connection.execute("""CREATE TABLE IF NOT EXISTS employee_clearances(
            id INTEGER PRIMARY KEY AUTOINCREMENT,clearance_number TEXT NOT NULL UNIQUE,
            employee_id INTEGER NOT NULL REFERENCES employees(id),clearance_reason TEXT NOT NULL,reason_comments TEXT,
            request_date TEXT NOT NULL DEFAULT(date('now')),request_time TEXT NOT NULL DEFAULT(time('now')),
            initial_status TEXT NOT NULL,current_status TEXT NOT NULL,letter_status TEXT NOT NULL DEFAULT 'Not Generated',
            initial_outstanding_item_count INTEGER NOT NULL DEFAULT 0,current_outstanding_item_count INTEGER NOT NULL DEFAULT 0,
            initial_outstanding_value REAL NOT NULL DEFAULT 0,current_outstanding_value REAL NOT NULL DEFAULT 0,
            unresolved_liability_count INTEGER NOT NULL DEFAULT 0,unresolved_liability_value REAL NOT NULL DEFAULT 0,
            warehouses_checked_count INTEGER NOT NULL DEFAULT 0,final_verification_at TEXT,clearance_date TEXT,
            cancellation_reason TEXT,cancelled_by INTEGER REFERENCES users(id),cancelled_at TEXT,
            created_by INTEGER NOT NULL REFERENCES users(id),created_at TEXT NOT NULL DEFAULT(datetime('now')),
            updated_at TEXT NOT NULL DEFAULT(datetime('now')))""")
        connection.execute("""CREATE TABLE IF NOT EXISTS employee_clearance_liabilities(
            id INTEGER PRIMARY KEY AUTOINCREMENT,clearance_id INTEGER NOT NULL REFERENCES employee_clearances(id),
            employee_id INTEGER NOT NULL REFERENCES employees(id),item_id INTEGER NOT NULL REFERENCES items(id),
            warehouse_id INTEGER REFERENCES warehouses(id),original_issue_id INTEGER,source_type TEXT NOT NULL DEFAULT 'Material Return',
            source_id INTEGER,condition TEXT NOT NULL,liability_status TEXT NOT NULL,liability_value REAL NOT NULL DEFAULT 0,
            resolution_reason TEXT,resolution_reference TEXT,resolved_by INTEGER REFERENCES users(id),resolved_at TEXT,
            created_at TEXT NOT NULL DEFAULT(datetime('now')),UNIQUE(clearance_id,source_type,source_id))""")
        connection.execute("""CREATE TABLE IF NOT EXISTS employee_clearance_documents(
            id INTEGER PRIMARY KEY AUTOINCREMENT,clearance_id INTEGER NOT NULL REFERENCES employee_clearances(id),
            document_number TEXT NOT NULL UNIQUE,document_type TEXT NOT NULL,status_snapshot TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,total_outstanding_value_snapshot REAL NOT NULL DEFAULT 0,
            generated_by INTEGER NOT NULL REFERENCES users(id),generated_at TEXT NOT NULL DEFAULT(datetime('now')))""")
        connection.execute('DROP INDEX IF EXISTS idx_employee_clearance_active')
        connection.execute("CREATE UNIQUE INDEX idx_employee_clearance_active ON employee_clearances(employee_id) WHERE current_status NOT IN('Cancelled','Completed') AND letter_status<>'Clearance Certificate Issued'")
        connection.execute('CREATE INDEX IF NOT EXISTS idx_employee_clearance_status_date ON employee_clearances(current_status,request_date)')
        connection.execute('CREATE INDEX IF NOT EXISTS idx_employee_clearance_liability ON employee_clearance_liabilities(clearance_id,liability_status)')
        connection.execute('CREATE INDEX IF NOT EXISTS idx_material_issue_employee_status ON material_issues(employee_id,status)')
        connection.execute('CREATE INDEX IF NOT EXISTS idx_returns_employee_item ON returns(employee_id,item_id)')
        connection.execute("""CREATE TABLE IF NOT EXISTS inventory_quarantine(
            id INTEGER PRIMARY KEY AUTOINCREMENT,item_id INTEGER NOT NULL REFERENCES items(id),
            warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),location_id INTEGER REFERENCES locations(id),
            quantity REAL NOT NULL CHECK(quantity>0),unit_cost REAL NOT NULL DEFAULT 0,
            inventory_status TEXT NOT NULL CHECK(inventory_status IN('DAMAGED','REPAIR_PENDING','INSPECTION_PENDING','PUT_AWAY_PENDING','REJECTED')),
            source_table TEXT NOT NULL,source_id INTEGER NOT NULL,created_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT(datetime('now')),released_at TEXT,released_by INTEGER REFERENCES users(id))""")
        connection.execute('CREATE INDEX IF NOT EXISTS idx_inventory_quarantine_warehouse_status ON inventory_quarantine(warehouse_id,inventory_status,item_id)')
        quarantine_columns={row['name']for row in connection.execute('PRAGMA table_info(inventory_quarantine)')}
        for column,definition in {'batch':'TEXT','expiry_date':'TEXT','source_grn_item_id':'INTEGER REFERENCES grn_items(id)','transaction_uom':'TEXT','base_uom':'TEXT','audit_reference':'TEXT','tool_id':'INTEGER REFERENCES tools(id)'}.items():
            if column not in quarantine_columns:connection.execute(f'ALTER TABLE inventory_quarantine ADD COLUMN {column} {definition}')
        connection.execute("""CREATE TABLE IF NOT EXISTS goods_inspections(
            id INTEGER PRIMARY KEY AUTOINCREMENT,inspection_number TEXT NOT NULL UNIQUE,grn_id INTEGER REFERENCES grns(id),
            grn_item_id INTEGER REFERENCES grn_items(id),hold_id INTEGER NOT NULL REFERENCES inventory_quarantine(id),source_table TEXT NOT NULL,source_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL REFERENCES items(id),warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
            inspected_quantity REAL NOT NULL,passed_quantity REAL NOT NULL,failed_quantity REAL NOT NULL,
            decision TEXT NOT NULL CHECK(decision IN('PASSED','PARTIALLY_PASSED','FAILED')),
            remarks TEXT,inspected_by INTEGER NOT NULL REFERENCES users(id),inspected_at TEXT NOT NULL DEFAULT(datetime('now')),
            audit_reference TEXT NOT NULL)""")
        connection.execute('CREATE INDEX IF NOT EXISTS idx_goods_inspections_grn_line ON goods_inspections(grn_item_id,inspected_at)')
        inspection_columns={row['name']for row in connection.execute('PRAGMA table_info(goods_inspections)')}
        for column,definition in {'source_table':"TEXT NOT NULL DEFAULT 'grn_items'",'source_id':'INTEGER NOT NULL DEFAULT 0','inspector_name':'TEXT','inspector_department':'TEXT','inspector_designation':'TEXT'}.items():
            if column not in inspection_columns:connection.execute(f'ALTER TABLE goods_inspections ADD COLUMN {column} {definition}')
        connection.execute("""CREATE TABLE IF NOT EXISTS tool_custody_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,tool_id INTEGER NOT NULL REFERENCES tools(id),
            employee_id INTEGER NOT NULL REFERENCES employees(id),warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
            checked_out_by INTEGER NOT NULL REFERENCES users(id),checked_out_at TEXT NOT NULL DEFAULT(datetime('now')),
            checked_in_by INTEGER REFERENCES users(id),checked_in_at TEXT,return_condition TEXT,
            status TEXT NOT NULL DEFAULT 'CHECKED_OUT')""")
        connection.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_active_custody ON tool_custody_history(tool_id) WHERE status=\'CHECKED_OUT\'')
        tool_columns={row['name'] for row in connection.execute('PRAGMA table_info(tools)')}
        for column,definition in {
            'status':"TEXT NOT NULL DEFAULT 'Available' CHECK(status IN('Pending Tool Registration','Available','Assigned','Damaged','Quarantined','Lost','Retired','Under Repair'))",
            'source_grn_item_id':'INTEGER REFERENCES grn_items(id)',
            'source_unit_number':'INTEGER CHECK(source_unit_number>0)',
            'registered_at':'TEXT','registered_by':'INTEGER REFERENCES users(id)',
            'calibration_required_yn':'INTEGER NOT NULL DEFAULT 0 CHECK(calibration_required_yn IN(0,1))',
            'location_id':'INTEGER REFERENCES locations(id)','custody_unit_cost':'REAL NOT NULL DEFAULT 0',
            'transfer_id':'INTEGER REFERENCES transfers(id)','transfer_pending_yn':'INTEGER NOT NULL DEFAULT 0',
        }.items():
            if column not in tool_columns:connection.execute(f'ALTER TABLE tools ADD COLUMN {column} {definition}')
        if 'status' not in tool_columns:
            connection.execute("""UPDATE tools SET status=CASE WHEN employee_id IS NOT NULL AND return_date IS NULL THEN 'Assigned'
                WHEN condition='Damaged' THEN 'Damaged' WHEN condition='Needs Repair' THEN 'Under Repair'
                WHEN condition IN('Lost','Retired','Quarantined') THEN condition ELSE 'Available' END,
                registered_at=datetime('now'),calibration_required_yn=CASE WHEN NULLIF(calibration_due_date,'') IS NOT NULL THEN 1 ELSE 0 END""")
        connection.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_grn_unit ON tools(source_grn_item_id,source_unit_number) WHERE source_grn_item_id IS NOT NULL')
        grn_columns={row['name'] for row in connection.execute('PRAGMA table_info(grns)')}
        for column in ('request_key','request_payload'):
            if column not in grn_columns:connection.execute(f'ALTER TABLE grns ADD COLUMN {column} TEXT')
        connection.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_grn_request_key ON grns(request_key) WHERE request_key IS NOT NULL')
        for trigger in ('tool_source_guard','tool_serial_insert','tool_serial_update','tool_registration_guard','tool_grn_identity_immutable','tool_issue_guard','tool_custody_guard','tool_new_assignment_guard'):
            connection.execute(f'DROP TRIGGER IF EXISTS {trigger}')
        connection.execute("""CREATE TRIGGER tool_new_assignment_guard BEFORE INSERT ON tools
            WHEN NEW.employee_id IS NOT NULL OR NEW.status='Assigned'
            BEGIN SELECT RAISE(ABORT,'Register the tool before manual issue'); END""")
        connection.execute("""CREATE TRIGGER IF NOT EXISTS tool_source_guard BEFORE INSERT ON tools
            WHEN NEW.source_grn_item_id IS NOT NULL
            BEGIN SELECT CASE WHEN NEW.source_unit_number IS NULL OR NEW.source_unit_number<>CAST(NEW.source_unit_number AS INTEGER) OR NEW.status<>'Pending Tool Registration' OR NEW.employee_id IS NOT NULL
                OR NOT EXISTS(SELECT 1 FROM grn_items gi JOIN items i ON i.id=gi.item_id WHERE gi.id=NEW.source_grn_item_id
                    AND gi.item_id=NEW.item_id AND gi.warehouse_id=NEW.warehouse_id AND i.consumable_returnable='Returnable'
                    AND NEW.source_unit_number<=gi.accepted_base_quantity)
                THEN RAISE(ABORT,'Invalid pending GRN tool unit') END; END""")
        for operation in ('INSERT','UPDATE'):
            connection.execute(f"""CREATE TRIGGER IF NOT EXISTS tool_serial_{operation.lower()} BEFORE {operation} ON tools
                WHEN NULLIF(trim(NEW.serial_number),'') IS NOT NULL AND EXISTS(SELECT 1 FROM tools WHERE lower(trim(serial_number))=lower(trim(NEW.serial_number)) AND id<>NEW.id)
                BEGIN SELECT RAISE(ABORT,'Manufacturer serial number already registered'); END""")
        connection.execute("""CREATE TRIGGER IF NOT EXISTS tool_registration_guard BEFORE UPDATE OF status,registered_at ON tools
            WHEN NEW.status='Available' AND (NEW.registered_at IS NULL OR NULLIF(trim(NEW.serial_number),'') IS NULL)
            BEGIN SELECT RAISE(ABORT,'Complete tool registration before making it available'); END""")
        connection.execute("""CREATE TRIGGER IF NOT EXISTS tool_grn_identity_immutable BEFORE UPDATE OF source_grn_item_id,source_unit_number,tool_code,item_id ON tools
            WHEN OLD.source_grn_item_id IS NOT NULL AND (NEW.source_grn_item_id IS NOT OLD.source_grn_item_id OR NEW.source_unit_number IS NOT OLD.source_unit_number OR NEW.tool_code<>OLD.tool_code OR NEW.item_id<>OLD.item_id)
            BEGIN SELECT RAISE(ABORT,'GRN tool identity cannot be changed'); END""")
        connection.execute("""CREATE TRIGGER IF NOT EXISTS tool_issue_guard BEFORE UPDATE OF employee_id,status ON tools
            WHEN NEW.employee_id IS NOT NULL AND NEW.return_date IS NULL AND (OLD.employee_id IS NOT NEW.employee_id OR OLD.status<>'Assigned')
            BEGIN
              SELECT CASE WHEN OLD.status<>'Available' OR OLD.registered_at IS NULL OR COALESCE(OLD.condition,'')<>'Good' OR COALESCE(NEW.condition,'')<>'Good'
                OR OLD.employee_id IS NOT NULL OR NEW.status<>'Assigned'
                OR (OLD.source_grn_item_id IS NOT NULL AND OLD.location_id IS NULL)
                OR (OLD.calibration_required_yn=1 AND (date(OLD.calibration_due_date) IS NULL OR date(OLD.calibration_due_date)<date('now')))
                OR OLD.transfer_pending_yn=1
                OR EXISTS(SELECT 1 FROM inventory_quarantine WHERE ((source_table='tools' AND source_id=OLD.id) OR tool_id=OLD.id) AND released_at IS NULL)
                OR NOT EXISTS(SELECT 1 FROM employees WHERE id=NEW.employee_id AND status='Active' AND deleted_at IS NULL)
                OR NEW.warehouse_id<>OLD.warehouse_id
                THEN RAISE(ABORT,'Tool is not eligible for issue') END;
            END""")
        connection.execute("""CREATE TRIGGER IF NOT EXISTS tool_custody_guard BEFORE INSERT ON tool_custody_history
            WHEN NEW.status='CHECKED_OUT' AND NOT EXISTS(SELECT 1 FROM tools WHERE id=NEW.tool_id AND status='Assigned' AND employee_id=NEW.employee_id AND warehouse_id=NEW.warehouse_id AND return_date IS NULL)
            BEGIN SELECT RAISE(ABORT,'Custody must match assigned tool and warehouse'); END""")
        connection.execute("""CREATE TABLE IF NOT EXISTS three_way_match_tolerances(
            id INTEGER PRIMARY KEY AUTOINCREMENT,company_id INTEGER NOT NULL REFERENCES company(id),
            component TEXT NOT NULL CHECK(component IN('quantity','unit_price','line_value','total_value','tax','freight','other_charges','rounding')),
            percentage_tolerance REAL,absolute_tolerance REAL,currency TEXT,active_yn INTEGER NOT NULL DEFAULT 1,
            effective_from TEXT NOT NULL DEFAULT(date('now')),effective_until TEXT,created_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT(datetime('now')),CHECK(percentage_tolerance IS NOT NULL OR absolute_tolerance IS NOT NULL))""")
        connection.execute('CREATE INDEX IF NOT EXISTS idx_match_tolerance_company_component ON three_way_match_tolerances(company_id,component,active_yn,effective_from)')
        connection.execute("""CREATE TABLE IF NOT EXISTS invoice_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,invoice_id INTEGER NOT NULL REFERENCES invoices(id),item_id INTEGER NOT NULL REFERENCES items(id),
            quantity REAL NOT NULL,unit_price REAL NOT NULL,line_value REAL NOT NULL,tax REAL NOT NULL DEFAULT 0,
            freight REAL NOT NULL DEFAULT 0,other_charges REAL NOT NULL DEFAULT 0)""")
        connection.execute('CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice_item ON invoice_items(invoice_id,item_id)')
        approval_columns={row['name'] for row in connection.execute('PRAGMA table_info(approval_log)')}
        for column,definition in {'approval_method':'TEXT','authority_reference':'TEXT','event_type':'TEXT','supersedes_approval_id':'INTEGER REFERENCES approval_log(id)'}.items():
            if column not in approval_columns:connection.execute(f'ALTER TABLE approval_log ADD COLUMN {column} {definition}')
        invoice_columns={row['name'] for row in connection.execute('PRAGMA table_info(invoices)')}
        for column,definition in {'match_result_code':'TEXT','match_details_json':'TEXT'}.items():
            if column not in invoice_columns:connection.execute(f'ALTER TABLE invoices ADD COLUMN {column} {definition}')
        adjustment_columns={row['name'] for row in connection.execute('PRAGMA table_info(stock_adjustments)')}
        for column,definition in {
            'quantity_before':'REAL','quantity_after':'REAL','unit_cost':'REAL','total_value_impact':'REAL',
            'detailed_remarks':'TEXT','attachment_required':'INTEGER NOT NULL DEFAULT 0','approved_at':'TEXT',
            'authority_reference':'TEXT','approval_method':'TEXT','cycle_count_id':'INTEGER',
            'cycle_count_item_id':'INTEGER'
        }.items():
            if column not in adjustment_columns:connection.execute(f'ALTER TABLE stock_adjustments ADD COLUMN {column} {definition}')
        cycle_count_columns={row['name'] for row in connection.execute('PRAGMA table_info(cycle_counts)')}
        for column,definition in {'submitted_by':'INTEGER REFERENCES users(id)','submitted_at':'TEXT','reviewed_by':'INTEGER REFERENCES users(id)','reviewed_at':'TEXT','review_comments':'TEXT'}.items():
            if column not in cycle_count_columns:connection.execute(f'ALTER TABLE cycle_counts ADD COLUMN {column} {definition}')
        cycle_sql=(connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='cycle_counts'").fetchone() or {'sql':''})['sql'] or ''
        if "status IN ('Draft','Counted','Approved')" in cycle_sql:
            connection.execute('PRAGMA legacy_alter_table=ON')
            connection.execute('ALTER TABLE cycle_counts RENAME TO cycle_counts_legacy_status')
            connection.execute("""CREATE TABLE cycle_counts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,count_number TEXT NOT NULL UNIQUE,warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
                count_date TEXT NOT NULL DEFAULT(date('now')),status TEXT NOT NULL DEFAULT 'Draft' CHECK(status IN ('Draft','Counted','Approved','Rejected','Recount Requested','Adjustment Pending SCM Approval')),
                created_by INTEGER REFERENCES users(id),submitted_by INTEGER REFERENCES users(id),submitted_at TEXT,reviewed_by INTEGER REFERENCES users(id),reviewed_at TEXT,review_comments TEXT)""")
            existing={row['name'] for row in connection.execute('PRAGMA table_info(cycle_counts_legacy_status)')}
            columns=[column for column in ('id','count_number','warehouse_id','count_date','status','created_by','submitted_by','submitted_at','reviewed_by','reviewed_at','review_comments') if column in existing]
            connection.execute(f"INSERT INTO cycle_counts({','.join(columns)}) SELECT {','.join(columns)} FROM cycle_counts_legacy_status")
            connection.execute('DROP TABLE cycle_counts_legacy_status')
            if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cycle_count_items'").fetchone():
                item_existing={row['name'] for row in connection.execute('PRAGMA table_info(cycle_count_items)')}
                connection.execute('ALTER TABLE cycle_count_items RENAME TO cycle_count_items_legacy_fk')
                connection.execute("""CREATE TABLE cycle_count_items(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,count_id INTEGER NOT NULL REFERENCES cycle_counts(id),
                    item_id INTEGER NOT NULL REFERENCES items(id),system_qty REAL NOT NULL DEFAULT 0,counted_qty REAL,
                    variance REAL,count_note TEXT,adjustment_id INTEGER)""")
                item_columns=[column for column in ('id','count_id','item_id','system_qty','counted_qty','variance','count_note','adjustment_id') if column in item_existing]
                connection.execute(f"INSERT INTO cycle_count_items({','.join(item_columns)}) SELECT {','.join(item_columns)} FROM cycle_count_items_legacy_fk")
                connection.execute('DROP TABLE cycle_count_items_legacy_fk')
        item_sql=(connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='cycle_count_items'").fetchone() or {'sql':''})['sql'] or ''
        adjustment_sql=(connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='stock_adjustments'").fetchone() or {'sql':''})['sql'] or ''
        if 'cycle_counts_legacy_status' in item_sql or 'cycle_counts_legacy_status' in adjustment_sql:
            connection.execute('PRAGMA legacy_alter_table=ON')
            if 'cycle_counts_legacy_status' in adjustment_sql:
                adjustment_existing={row['name'] for row in connection.execute('PRAGMA table_info(stock_adjustments)')}
                connection.execute('ALTER TABLE stock_adjustments RENAME TO stock_adjustments_legacy_cycle_fk')
                connection.execute("""CREATE TABLE stock_adjustments(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,adjustment_number TEXT UNIQUE NOT NULL,
                    item_id INTEGER NOT NULL REFERENCES items(id),warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
                    quantity_change REAL NOT NULL,reason TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending','Approved','Rejected')),
                    approved_by INTEGER REFERENCES users(id),created_by INTEGER REFERENCES users(id),
                    adjustment_date TEXT NOT NULL DEFAULT(date('now')),location_id INTEGER,
                    quantity_before REAL,quantity_after REAL,unit_cost REAL,total_value_impact REAL,
                    detailed_remarks TEXT,attachment_required INTEGER NOT NULL DEFAULT 0,approved_at TEXT,
                    authority_reference TEXT,approval_method TEXT,cycle_count_id INTEGER,cycle_count_item_id INTEGER)""")
                adjustment_columns=[column for column in ('id','adjustment_number','item_id','warehouse_id','quantity_change','reason','status','approved_by','created_by','adjustment_date','location_id','quantity_before','quantity_after','unit_cost','total_value_impact','detailed_remarks','attachment_required','approved_at','authority_reference','approval_method','cycle_count_id','cycle_count_item_id') if column in adjustment_existing]
                connection.execute(f"INSERT INTO stock_adjustments({','.join(adjustment_columns)}) SELECT {','.join(adjustment_columns)} FROM stock_adjustments_legacy_cycle_fk")
                connection.execute('DROP TABLE stock_adjustments_legacy_cycle_fk')
            if 'cycle_counts_legacy_status' in item_sql:
                item_existing={row['name'] for row in connection.execute('PRAGMA table_info(cycle_count_items)')}
                connection.execute('ALTER TABLE cycle_count_items RENAME TO cycle_count_items_legacy_cycle_fk')
                connection.execute("""CREATE TABLE cycle_count_items(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,count_id INTEGER NOT NULL REFERENCES cycle_counts(id),
                    item_id INTEGER NOT NULL REFERENCES items(id),system_qty REAL NOT NULL DEFAULT 0,
                    counted_qty REAL,variance REAL,count_note TEXT,adjustment_id INTEGER)""")
                item_columns=[column for column in ('id','count_id','item_id','system_qty','counted_qty','variance','count_note','adjustment_id') if column in item_existing]
                connection.execute(f"INSERT INTO cycle_count_items({','.join(item_columns)}) SELECT {','.join(item_columns)} FROM cycle_count_items_legacy_cycle_fk")
                connection.execute('DROP TABLE cycle_count_items_legacy_cycle_fk')
        cycle_count_item_columns={row['name'] for row in connection.execute('PRAGMA table_info(cycle_count_items)')}
        for column,definition in {'count_note':'TEXT','adjustment_id':'INTEGER'}.items():
            if column not in cycle_count_item_columns:connection.execute(f'ALTER TABLE cycle_count_items ADD COLUMN {column} {definition}')
        storekeeper_permission_rows=connection.execute("SELECT id,permission_keys FROM employees WHERE approval_role='Storekeeper' AND deleted_at IS NULL").fetchall()
        from .permissions import defaults_for_role
        old_storekeeper_defaults=set(defaults_for_role('Storekeeper'))-{'task.transfers'}
        old_ui_storekeeper_defaults=old_storekeeper_defaults-{'po.view','grn.view','grn.post','issue.view','issue.post'}
        for employee in storekeeper_permission_rows:
            if not employee['permission_keys']:
                continue
            try:
                keys=json.loads(employee['permission_keys'])
            except (TypeError,ValueError):
                continue
            if not isinstance(keys,list):
                continue
            changed=False
            if 'task.cycle_count' not in keys:
                keys.append('task.cycle_count')
                changed=True
            if 'task.transfers' not in keys and set(keys) in (old_storekeeper_defaults,old_ui_storekeeper_defaults):
                keys.append('task.transfers')
                changed=True
            if changed:
                connection.execute('UPDATE employees SET permission_keys=? WHERE id=?',(json.dumps(keys),employee['id']))
        transfer_columns={row['name'] for row in connection.execute('PRAGMA table_info(transfers)')}
        for column,definition in {
            'transaction_quantity':'REAL','transaction_uom':'TEXT','conversion_factor_used':'REAL',
            'base_quantity':'REAL','base_uom':'TEXT','dispatched_quantity':'REAL NOT NULL DEFAULT 0',
            'received_good_quantity':'REAL NOT NULL DEFAULT 0','damaged_quantity':'REAL NOT NULL DEFAULT 0',
            'rejected_quantity':'REAL NOT NULL DEFAULT 0','shortage_quantity':'REAL NOT NULL DEFAULT 0',
            'outstanding_quantity':'REAL NOT NULL DEFAULT 0','total_value':'REAL NOT NULL DEFAULT 0',
            'closed_by':'INTEGER REFERENCES users(id)','closed_at':'TEXT',
            'multi_item_yn':'INTEGER NOT NULL DEFAULT 0'
        }.items():
            if column not in transfer_columns:connection.execute(f'ALTER TABLE transfers ADD COLUMN {column} {definition}')
        receipt_columns={row['name'] for row in connection.execute('PRAGMA table_info(transfer_receipts)')}
        for column,definition in {
            'physical_quantity':'REAL NOT NULL DEFAULT 0','good_quantity':'REAL NOT NULL DEFAULT 0',
            'damaged_quantity':'REAL NOT NULL DEFAULT 0','rejected_quantity':'REAL NOT NULL DEFAULT 0',
            'shortage_quantity':'REAL NOT NULL DEFAULT 0','unit_cost':'REAL NOT NULL DEFAULT 0',
            'total_value':'REAL NOT NULL DEFAULT 0','receipt_status':'TEXT','remarks':'TEXT'
        }.items():
            if column not in receipt_columns:connection.execute(f'ALTER TABLE transfer_receipts ADD COLUMN {column} {definition}')
        location_columns={row['name'] for row in connection.execute('PRAGMA table_info(locations)')}
        for column,definition in {
            'storage_classification':'TEXT','environment':'TEXT','structure_type':'TEXT',
            'capacity_quantity':'REAL','capacity_uom':'TEXT','secure_storage':'INTEGER NOT NULL DEFAULT 0',
            'temperature_controlled':'INTEGER NOT NULL DEFAULT 0','mixing_rule':'TEXT NOT NULL DEFAULT \'MIXED_ITEMS_ALLOWED\'',
            'active_yn':'INTEGER NOT NULL DEFAULT 1','full_code':'TEXT'
        }.items():
            if column not in location_columns:connection.execute(f'ALTER TABLE locations ADD COLUMN {column} {definition}')
        item_columns={row['name'] for row in connection.execute('PRAGMA table_info(items)')}
        for column,definition in {
            'storage_classification_override':'TEXT','environment_override':'TEXT','structure_type_override':'TEXT',
            'secure_storage_required':'INTEGER NOT NULL DEFAULT 0','hazardous_storage_required':'INTEGER NOT NULL DEFAULT 0',
            'temperature_controlled_required':'INTEGER NOT NULL DEFAULT 0'
        }.items():
            if column not in item_columns:connection.execute(f'ALTER TABLE items ADD COLUMN {column} {definition}')
        connection.execute('''CREATE TABLE IF NOT EXISTS item_category_storage_rules(
            id INTEGER PRIMARY KEY AUTOINCREMENT,category TEXT NOT NULL,storage_classification TEXT,
            environment TEXT,structure_type TEXT,secure_required INTEGER NOT NULL DEFAULT 0,
            hazardous_required INTEGER NOT NULL DEFAULT 0,temperature_controlled_required INTEGER NOT NULL DEFAULT 0,
            preferred_warehouse_id INTEGER REFERENCES warehouses(id),priority INTEGER NOT NULL DEFAULT 100,
            active_yn INTEGER NOT NULL DEFAULT 1,created_by INTEGER REFERENCES users(id),created_at TEXT NOT NULL DEFAULT(datetime('now')),
            updated_at TEXT NOT NULL DEFAULT(datetime('now')))''')
        connection.execute('''CREATE TABLE IF NOT EXISTS putaway_recommendations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,item_id INTEGER NOT NULL REFERENCES items(id),warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
            quantity REAL NOT NULL,inventory_status TEXT NOT NULL DEFAULT 'AVAILABLE',recommended_location_id INTEGER REFERENCES locations(id),
            selected_location_id INTEGER REFERENCES locations(id),status TEXT NOT NULL DEFAULT 'RECOMMENDED',reason TEXT,
            override_reason TEXT,source_table TEXT,source_id INTEGER,recommended_by INTEGER REFERENCES users(id),recommended_at TEXT NOT NULL DEFAULT(datetime('now')),
            confirmed_by INTEGER REFERENCES users(id),confirmed_at TEXT)''')
        connection.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_locations_warehouse_code_stable ON locations(warehouse_id,code) WHERE deleted_at IS NULL')
        connection.execute('CREATE INDEX IF NOT EXISTS idx_locations_hierarchy ON locations(warehouse_id,parent_id,type,active_yn)')
        connection.execute('CREATE INDEX IF NOT EXISTS idx_storage_rules_category_priority ON item_category_storage_rules(category,active_yn,priority)')
        connection.execute('''CREATE TABLE IF NOT EXISTS location_code_migration_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,location_id INTEGER NOT NULL REFERENCES locations(id),old_code TEXT NOT NULL,new_code TEXT NOT NULL,
            reason TEXT NOT NULL,migrated_at TEXT NOT NULL DEFAULT(datetime('now')),UNIQUE(location_id,old_code,new_code))''')
        used_warehouse_codes={str(row['warehouse_code']).upper() for row in connection.execute("SELECT warehouse_code FROM warehouses WHERE trim(COALESCE(warehouse_code,''))<>'' AND upper(warehouse_code)<>'NONE'")}
        warehouse_sequence=1
        for warehouse in connection.execute("SELECT id,warehouse_code FROM warehouses WHERE trim(COALESCE(warehouse_code,''))='' OR upper(warehouse_code)='NONE' ORDER BY id").fetchall():
            while f'WH{warehouse_sequence:02d}' in used_warehouse_codes:warehouse_sequence+=1
            replacement=f"WH{warehouse_sequence:02d}";connection.execute('UPDATE warehouses SET warehouse_code=? WHERE id=?',(replacement,warehouse['id']));used_warehouse_codes.add(replacement);warehouse_sequence+=1
        for location in connection.execute("SELECT l.id,l.warehouse_id,l.code,w.warehouse_code FROM locations l JOIN warehouses w ON w.id=l.warehouse_id WHERE upper(l.code) LIKE 'NONE-%'").fetchall():
            new_code=location['warehouse_code']+location['code'][4:]
            collision=connection.execute('SELECT id FROM locations WHERE code=? AND warehouse_id=? AND id<>?',(new_code,location['warehouse_id'],location['id'])).fetchone()
            if not collision:
                connection.execute("INSERT OR IGNORE INTO location_code_migration_log(location_id,old_code,new_code,reason)VALUES(?,?,?,'Replaced invalid NONE prefix while preserving the location ID and all foreign-key history')",(location['id'],location['code'],new_code));connection.execute('UPDATE locations SET code=?,full_code=? WHERE id=?',(new_code,new_code,location['id']))
        connection.execute('''CREATE TABLE IF NOT EXISTS in_transit_inventory(
            transfer_id INTEGER PRIMARY KEY REFERENCES transfers(id),item_id INTEGER NOT NULL REFERENCES items(id),
            from_warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),to_warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
            dispatched_quantity REAL NOT NULL,outstanding_quantity REAL NOT NULL,unit_cost REAL NOT NULL,total_value REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'IN_TRANSIT',dispatched_at TEXT NOT NULL DEFAULT(datetime('now')),updated_at TEXT NOT NULL DEFAULT(datetime('now')))''')
        connection.execute('''CREATE TABLE IF NOT EXISTS transfer_cost_allocations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,transfer_id INTEGER NOT NULL REFERENCES transfers(id),source_layer_id INTEGER,
            dispatched_quantity REAL NOT NULL,accounted_quantity REAL NOT NULL DEFAULT 0,unit_cost REAL NOT NULL,
            UNIQUE(transfer_id,source_layer_id))''')
        connection.execute('''CREATE TABLE IF NOT EXISTS transfer_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,transfer_id INTEGER NOT NULL REFERENCES transfers(id),
            item_id INTEGER NOT NULL REFERENCES items(id),from_location_id INTEGER NOT NULL REFERENCES locations(id),
            to_location_id INTEGER REFERENCES locations(id),quantity REAL NOT NULL,
            transaction_quantity REAL,transaction_uom TEXT,conversion_factor_used REAL,base_uom TEXT,
            unit_cost REAL NOT NULL DEFAULT 0,total_value REAL NOT NULL DEFAULT 0,
            dispatched_quantity REAL NOT NULL DEFAULT 0,received_good_quantity REAL NOT NULL DEFAULT 0,
            damaged_quantity REAL NOT NULL DEFAULT 0,rejected_quantity REAL NOT NULL DEFAULT 0,
            shortage_quantity REAL NOT NULL DEFAULT 0,outstanding_quantity REAL NOT NULL DEFAULT 0)''')
        connection.execute('''INSERT INTO transfer_items(transfer_id,item_id,from_location_id,to_location_id,quantity,
            transaction_quantity,transaction_uom,conversion_factor_used,base_uom,unit_cost,total_value,
            dispatched_quantity,received_good_quantity,damaged_quantity,rejected_quantity,shortage_quantity,outstanding_quantity)
            SELECT t.id,t.item_id,t.from_location_id,t.to_location_id,t.quantity,t.transaction_quantity,
            t.transaction_uom,t.conversion_factor_used,t.base_uom,t.unit_cost,
            COALESCE(NULLIF(t.total_value,0),t.quantity*t.unit_cost),
            COALESCE(NULLIF(t.dispatched_quantity,0),t.quantity),t.received_good_quantity,
            t.damaged_quantity,t.rejected_quantity,t.shortage_quantity,
            CASE WHEN t.outstanding_quantity>0 THEN t.outstanding_quantity
                WHEN t.status IN('In Transit','Partially Received') THEN MAX(0,t.quantity-
                    COALESCE(t.received_good_quantity,0)-COALESCE(t.damaged_quantity,0)-
                    COALESCE(t.rejected_quantity,0)-COALESCE(t.shortage_quantity,0))
                ELSE 0 END FROM transfers t
            WHERE NOT EXISTS(SELECT 1 FROM transfer_items ti WHERE ti.transfer_id=t.id)''')
        allocation_columns={row['name'] for row in connection.execute('PRAGMA table_info(transfer_cost_allocations)')}
        if 'transfer_item_id' not in allocation_columns:
            connection.execute('ALTER TABLE transfer_cost_allocations ADD COLUMN transfer_item_id INTEGER REFERENCES transfer_items(id)')
        connection.execute('''UPDATE transfer_cost_allocations SET transfer_item_id=(
            SELECT id FROM transfer_items WHERE transfer_id=transfer_cost_allocations.transfer_id ORDER BY id LIMIT 1)
            WHERE transfer_item_id IS NULL''')
        connection.execute('''CREATE TABLE IF NOT EXISTS transfer_receipt_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,receipt_id INTEGER NOT NULL REFERENCES transfer_receipts(id),
            transfer_item_id INTEGER NOT NULL REFERENCES transfer_items(id),item_id INTEGER NOT NULL REFERENCES items(id),
            location_id INTEGER NOT NULL REFERENCES locations(id),physical_quantity REAL NOT NULL DEFAULT 0,
            good_quantity REAL NOT NULL DEFAULT 0,damaged_quantity REAL NOT NULL DEFAULT 0,
            rejected_quantity REAL NOT NULL DEFAULT 0,shortage_quantity REAL NOT NULL DEFAULT 0,
            unit_cost REAL NOT NULL DEFAULT 0,total_value REAL NOT NULL DEFAULT 0,
            UNIQUE(receipt_id,transfer_item_id))''')
        connection.execute('''INSERT INTO transfer_receipt_items(receipt_id,transfer_item_id,item_id,location_id,
            physical_quantity,good_quantity,damaged_quantity,rejected_quantity,shortage_quantity,unit_cost,total_value)
            SELECT r.id,ti.id,r.item_id,r.location_id,
            CASE WHEN r.physical_quantity=0 AND r.good_quantity=0 AND r.damaged_quantity=0 AND r.rejected_quantity=0
                THEN r.quantity_received ELSE r.physical_quantity END,
            CASE WHEN r.physical_quantity=0 AND r.good_quantity=0 AND r.damaged_quantity=0 AND r.rejected_quantity=0
                THEN r.quantity_received ELSE r.good_quantity END,r.damaged_quantity,
            r.rejected_quantity,r.shortage_quantity,r.unit_cost,r.total_value FROM transfer_receipts r
            JOIN transfer_items ti ON ti.transfer_id=r.transfer_id
            WHERE NOT EXISTS(SELECT 1 FROM transfer_receipt_items ri WHERE ri.receipt_id=r.id)''')
        connection.execute('CREATE INDEX IF NOT EXISTS idx_transfer_items_transfer ON transfer_items(transfer_id,id)')
        connection.execute('CREATE INDEX IF NOT EXISTS idx_transfer_receipt_items_receipt ON transfer_receipt_items(receipt_id,transfer_item_id)')
        connection.execute('''CREATE TABLE IF NOT EXISTS transfer_shortages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,transfer_id INTEGER NOT NULL REFERENCES transfers(id),receipt_id INTEGER NOT NULL REFERENCES transfer_receipts(id),
            item_id INTEGER NOT NULL REFERENCES items(id),quantity REAL NOT NULL,unit_cost REAL NOT NULL,total_value REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',remarks TEXT,recorded_by INTEGER REFERENCES users(id),recorded_at TEXT NOT NULL DEFAULT(datetime('now')),
            resolution_type TEXT,resolution_reference TEXT,resolved_by INTEGER REFERENCES users(id),resolved_at TEXT)''')
        shortage_columns={row['name'] for row in connection.execute('PRAGMA table_info(transfer_shortages)')}
        if 'transfer_item_id' not in shortage_columns:
            connection.execute('ALTER TABLE transfer_shortages ADD COLUMN transfer_item_id INTEGER REFERENCES transfer_items(id)')
        connection.execute('''UPDATE transfer_shortages SET transfer_item_id=(
            SELECT id FROM transfer_items WHERE transfer_id=transfer_shortages.transfer_id ORDER BY id LIMIT 1)
            WHERE transfer_item_id IS NULL''')
        connection.execute('''CREATE TABLE IF NOT EXISTS transfer_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,transfer_id INTEGER NOT NULL REFERENCES transfers(id),event_type TEXT NOT NULL,
            event_data TEXT,performed_by INTEGER REFERENCES users(id),created_at TEXT NOT NULL DEFAULT(datetime('now')))''')
        connection.execute('CREATE INDEX IF NOT EXISTS idx_transfer_receipts_transfer ON transfer_receipts(transfer_id,received_at)')
        connection.execute('CREATE INDEX IF NOT EXISTS idx_transfer_shortages_transfer_status ON transfer_shortages(transfer_id,status)')
        # Multi-warehouse inventory queries and FIFO posting always lead with
        # warehouse and item; these indexes keep authorization filtering in SQL.
        connection.execute('CREATE INDEX IF NOT EXISTS idx_inventory_stock_warehouse_item_location ON inventory_stock(warehouse_id,item_id,location_id)')
        connection.execute('CREATE INDEX IF NOT EXISTS idx_inventory_layers_warehouse_item_fifo ON inventory_layers(warehouse_id,item_id,location_id,received_date,id)')
        connection.execute('CREATE INDEX IF NOT EXISTS idx_stock_ledger_warehouse_item_date ON stock_ledger(warehouse_id,item_id,created_at)')
        connection.execute('CREATE INDEX IF NOT EXISTS idx_grn_items_warehouse_grn ON grn_items(warehouse_id,grn_id)')
        connection.execute('CREATE INDEX IF NOT EXISTS idx_material_issue_items_warehouse_issue ON material_issue_items(warehouse_id,issue_id)')
        connection.execute('CREATE INDEX IF NOT EXISTS idx_transfers_source_destination ON transfers(from_warehouse_id,to_warehouse_id,transfer_date)')
        connection.execute('CREATE INDEX IF NOT EXISTS idx_stock_adjustments_warehouse_date ON stock_adjustments(warehouse_id,adjustment_date)')
        connection.execute("""CREATE TABLE IF NOT EXISTS warehouse_migration_issues(
            id INTEGER PRIMARY KEY AUTOINCREMENT,issue_key TEXT NOT NULL UNIQUE,table_name TEXT NOT NULL,
            record_id INTEGER NOT NULL,column_name TEXT NOT NULL,issue_type TEXT NOT NULL,
            details TEXT,status TEXT NOT NULL DEFAULT 'OPEN',detected_at TEXT NOT NULL DEFAULT(datetime('now')),
            resolved_at TEXT,resolved_by INTEGER REFERENCES users(id))""")
        # Legacy rows are flagged for controlled review. Warehouse assignments
        # are never guessed or silently backfilled.
        for table,column in [('inventory_stock','warehouse_id'),('inventory_layers','warehouse_id'),('stock_ledger','warehouse_id'),('grn_items','warehouse_id'),('material_issue_items','warehouse_id'),('returns','warehouse_id'),('stock_adjustments','warehouse_id'),('tools','warehouse_id')]:
            columns={row['name']for row in connection.execute(f'PRAGMA table_info({table})')}
            if column not in columns:continue
            for row in connection.execute(f'SELECT id FROM {table} WHERE {column} IS NULL').fetchall():
                key=f'{table}:{row["id"]}:{column}:missing'
                connection.execute('INSERT OR IGNORE INTO warehouse_migration_issues(issue_key,table_name,record_id,column_name,issue_type,details)VALUES(?,?,?,?,?,?)',(key,table,row['id'],column,'MISSING_WAREHOUSE','Warehouse could not be derived safely; administrator review is required'))
        for table in ['inventory_stock','inventory_layers','stock_ledger','grn_items','material_issue_items','returns','stock_adjustments']:
            columns={row['name']for row in connection.execute(f'PRAGMA table_info({table})')}
            if not {'warehouse_id','location_id'}<=columns:continue
            for row in connection.execute(f'''SELECT x.id FROM {table} x JOIN locations l ON l.id=x.location_id
              WHERE x.location_id IS NOT NULL AND x.warehouse_id<>l.warehouse_id''').fetchall():
                key=f'{table}:{row["id"]}:location_id:mismatch'
                connection.execute('INSERT OR IGNORE INTO warehouse_migration_issues(issue_key,table_name,record_id,column_name,issue_type,details)VALUES(?,?,?,?,?,?)',(key,table,row['id'],'location_id','WAREHOUSE_LOCATION_MISMATCH','Location belongs to a different warehouse; administrator review is required'))
    from .pr_schema import ensure_pr_workflow_schema
    ensure_pr_workflow_schema()
    with connect() as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
