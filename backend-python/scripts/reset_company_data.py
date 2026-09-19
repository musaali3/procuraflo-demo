"""Offline tenant reset that preserves company and administrator identity data."""

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path


REFERENCE_TABLES = {
    "countries",
    "cities",
    "currencies",
    "item_categories",
    "item_subcategories",
    "settings",
    "role_shift_requirements",
    "company",
    "system_maintenance",
}


def reset_database(database_path: Path) -> Path:
    database_path = database_path.resolve()
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = database_path.with_name(f"{database_path.stem}.before-data-reset-{timestamp}.db")

    source = sqlite3.connect(database_path, timeout=30)
    source.row_factory = sqlite3.Row
    backup = sqlite3.connect(backup_path)
    try:
        source.backup(backup)
        backup.close()
        admin = source.execute(
            "SELECT * FROM users WHERE role='SupplyChainManager' AND is_active=1 "
            "AND deleted_at IS NULL ORDER BY id LIMIT 1"
        ).fetchone()
        if not admin or not admin["employee_id"]:
            raise RuntimeError("An active SupplyChainManager administrator with an employee profile is required")
        employee = source.execute("SELECT * FROM employees WHERE id=?", (admin["employee_id"],)).fetchone()
        if not employee:
            raise RuntimeError("Administrator employee profile was not found")
        department_id = employee["department_id"]
        tables = [row[0] for row in source.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )]
        source.execute("PRAGMA foreign_keys=OFF")
        source.execute("BEGIN IMMEDIATE")
        for table in tables:
            if table in REFERENCE_TABLES:
                continue
            if table == "users":
                source.execute("DELETE FROM users WHERE id<>?", (admin["id"],))
            elif table == "employees":
                source.execute("DELETE FROM employees WHERE id<>?", (employee["id"],))
            elif table == "departments":
                source.execute("DELETE FROM departments WHERE id<>?", (department_id,))
            else:
                source.execute(f'DELETE FROM "{table}"')
        source.execute("UPDATE users SET warehouse_id=NULL, locked_reason=NULL WHERE id=?", (admin["id"],))
        source.execute(
            "UPDATE employees SET warehouse_id=NULL,reports_to=NULL,reports_to_employee_id=NULL WHERE id=?",
            (employee["id"],),
        )
        source.execute("UPDATE system_maintenance SET active_yn=0,session_epoch=session_epoch+1 WHERE id=1")
        if "sqlite_sequence" in [row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")]:
            placeholders = ",".join("?" for _ in REFERENCE_TABLES | {"users", "employees", "departments"})
            source.execute(
                f"DELETE FROM sqlite_sequence WHERE name NOT IN ({placeholders})",
                tuple(REFERENCE_TABLES | {"users", "employees", "departments"}),
            )
        source.commit()
        check = source.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise RuntimeError(f"Database integrity check failed: {check}")
    except Exception:
        source.rollback()
        raise
    finally:
        source.close()
    return backup_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        with sqlite3.connect(args.database) as connection:
            connection.row_factory = sqlite3.Row
            preserved = {"countries", "cities", "currencies", "item_categories", "item_subcategories", "settings", "role_shift_requirements", "company", "system_maintenance", "users", "employees", "departments"}
            tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            nonempty = [(table, connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]) for table in tables if table not in preserved and connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]]
            print({"company_count": connection.execute("SELECT COUNT(*) FROM company").fetchone()[0], "admin_count": connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], "employee_count": connection.execute("SELECT COUNT(*) FROM employees").fetchone()[0], "nonempty_business_tables": nonempty, "integrity": connection.execute("PRAGMA integrity_check").fetchone()[0]})
    else:
        print(reset_database(args.database))
