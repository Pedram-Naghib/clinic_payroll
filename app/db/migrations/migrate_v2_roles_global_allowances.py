"""
One-time migration: globalize housing/food allowances + add Job Roles.

Run ONCE against your existing populated data/clinic.db:

    python -m app.db.migrations.migrate_v2_roles_global_allowances

Back up data/clinic.db before running (copy the file) -- this script rebuilds
the `employees` and `allowance_definitions` tables in place. It is NOT
idempotent in the sense of being safe to re-run blindly forever: a second run
on an already-migrated DB is a no-op for steps 1-3 (INSERT OR IGNORE) but
step 4/5 (table rebuild) will simply re-detect there's nothing to rebuild and
skip, so re-running is safe, just unnecessary.

What this does:
  1. Inserts the 4 new global allowance config keys into system_config with
     the approved real-world Rial values.
  2. Creates the roles / employee_roles tables and seeds 'بهیار' / 'پذیرش'
     (renaming any pre-existing English 'Behyar'/'Paziresh' rows in place if
     this DB was migrated before this fix, preserving all assignments).
  3. Updates allowance_definitions rows (housing_fixed/food_fixed/
     housing_hourly/food_hourly) to read from the new global config keys
     instead of per-employee columns -- requires rebuilding the table first
     since 'config_per_hour' is a new amount_type value not allowed by the
     old CHECK constraint.
  4. Rebuilds the employees table without housing_allowance_per_hour,
     food_allowance_per_hour, fixed_housing_allowance, fixed_food_allowance.
     `active` is NOT touched -- it stays exactly as-is (soft-delete remains
     in the DB; only the UI grid was asked to stop displaying it).
  5. Runs PRAGMA foreign_key_check at the end and raises if anything is
     inconsistent, so a partial/bad migration never gets committed silently.
"""

from __future__ import annotations
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "clinic.db"

GLOBAL_ALLOWANCE_DEFAULTS = [
    # key, value, value_type, label, description, category
    ("fixed_housing_allowance", "30000000", "int",
     "Housing Allowance (fixed, insured)",
     "Flat monthly amount for all insured staff -- one global rate, edit here instead of per employee",
     "allowances"),
    ("fixed_food_allowance", "22000000", "int",
     "Food Allowance (fixed, insured)",
     "Flat monthly amount for all insured staff -- one global rate, edit here instead of per employee",
     "allowances"),
    ("housing_allowance_per_hour", "156250", "int",
     "Housing Allowance (per hour, non-insured)",
     "Multiplied by worked hours for all non-insured staff -- one global rate",
     "allowances"),
    ("food_allowance_per_hour", "114500", "int",
     "Food Allowance (per hour, non-insured)",
     "Multiplied by worked hours for all non-insured staff -- one global rate",
     "allowances"),
]

SEED_ROLES = ["بهیار", "پذیرش"]
LEGACY_ROLE_RENAMES = {"Behyar": "بهیار", "Paziresh": "پذیرش"}  # for DBs migrated before the Persian-name fix

EMPLOYEES_COLUMNS_TO_DROP = {
    "housing_allowance_per_hour", "food_allowance_per_hour",
    "fixed_housing_allowance", "fixed_food_allowance",
}


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _employees_needs_rebuild(conn: sqlite3.Connection) -> bool:
    cols = set(_table_columns(conn, "employees"))
    return bool(cols & EMPLOYEES_COLUMNS_TO_DROP)


def _allowance_definitions_needs_rebuild(conn: sqlite3.Connection) -> bool:
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='allowance_definitions'"
    ).fetchone()[0]
    return "config_per_hour" not in sql


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = OFF;")  # required while rebuilding referenced tables

    # --- Step 1: global allowance config values ---
    conn.executemany(
        """INSERT OR IGNORE INTO system_config (key, value, value_type, label, description, category)
           VALUES (?, ?, ?, ?, ?, ?)""",
        GLOBAL_ALLOWANCE_DEFAULTS,
    )
    print(f"[1/5] system_config: inserted (or already present) {len(GLOBAL_ALLOWANCE_DEFAULTS)} global allowance keys")

    # --- Step 2: roles / employee_roles tables ---
    conn.execute(
        "CREATE TABLE IF NOT EXISTS roles (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)"
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS employee_roles (
               employee_id INTEGER NOT NULL REFERENCES employees(id),
               role_id     INTEGER NOT NULL REFERENCES roles(id),
               PRIMARY KEY (employee_id, role_id)
           )"""
    )
    conn.executemany("INSERT OR IGNORE INTO roles (name) VALUES (?)", [(r,) for r in SEED_ROLES])

    # If this DB was already migrated with the original English seed names
    # ('Behyar'/'Paziresh'), rename them to Persian in place. Renaming the
    # `roles.name` value keeps the same role_id, so every employee_roles
    # assignment stays intact automatically -- no junction-table changes needed.
    # If both an old and new row somehow exist (e.g. partially re-run), merge
    # any assignments onto the Persian row and drop the English one.
    for old_name, new_name in LEGACY_ROLE_RENAMES.items():
        old_row = conn.execute("SELECT id FROM roles WHERE name = ?", (old_name,)).fetchone()
        if old_row is None:
            continue
        new_row = conn.execute("SELECT id FROM roles WHERE name = ?", (new_name,)).fetchone()
        if new_row is None:
            conn.execute("UPDATE roles SET name = ? WHERE id = ?", (new_name, old_row["id"]))
            print(f"    roles: renamed '{old_name}' -> '{new_name}'")
        else:
            conn.execute(
                "UPDATE OR IGNORE employee_roles SET role_id = ? WHERE role_id = ?",
                (new_row["id"], old_row["id"]),
            )
            conn.execute("DELETE FROM employee_roles WHERE role_id = ?", (old_row["id"],))
            conn.execute("DELETE FROM roles WHERE id = ?", (old_row["id"],))
            print(f"    roles: merged '{old_name}' into existing '{new_name}'")

    print(f"[2/5] roles / employee_roles tables ready, seeded: {', '.join(SEED_ROLES)}")

    # --- Step 3: rebuild allowance_definitions (new CHECK constraint for 'config_per_hour') ---
    if _allowance_definitions_needs_rebuild(conn):
        conn.execute(
            """
            CREATE TABLE allowance_definitions_new (
                code                    TEXT PRIMARY KEY,
                label                   TEXT NOT NULL,
                applies_to_insured      INTEGER NOT NULL DEFAULT 0,
                applies_to_non_insured  INTEGER NOT NULL DEFAULT 0,
                enabled                 INTEGER NOT NULL DEFAULT 1,
                amount_type             TEXT NOT NULL CHECK (amount_type IN (
                                             'config_flat',
                                             'config_per_child',
                                             'config_per_hour',
                                             'employee_field_flat',
                                             'employee_field_per_hour'
                                         )),
                config_key              TEXT,
                employee_field          TEXT,
                condition_employee_field TEXT,
                excluded_from_insurance_base INTEGER NOT NULL DEFAULT 0,
                sort_order               INTEGER DEFAULT 0,
                updated_at                TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """INSERT INTO allowance_definitions_new
               SELECT code, label, applies_to_insured, applies_to_non_insured, enabled, amount_type,
                      config_key, employee_field, condition_employee_field,
                      excluded_from_insurance_base, sort_order, updated_at
               FROM allowance_definitions"""
        )
        conn.execute("DROP TABLE allowance_definitions")
        conn.execute("ALTER TABLE allowance_definitions_new RENAME TO allowance_definitions")
        print("[3/5] allowance_definitions: rebuilt with 'config_per_hour' amount_type allowed")
    else:
        print("[3/5] allowance_definitions: already has 'config_per_hour' -- skipped rebuild")

    # Re-point the housing/food allowance rules at the new global config keys
    # (safe to run every time -- idempotent UPDATEs)
    conn.execute(
        """UPDATE allowance_definitions
           SET amount_type = 'config_flat', config_key = 'fixed_housing_allowance', employee_field = NULL
           WHERE code = 'housing_fixed'"""
    )
    conn.execute(
        """UPDATE allowance_definitions
           SET amount_type = 'config_flat', config_key = 'fixed_food_allowance', employee_field = NULL
           WHERE code = 'food_fixed'"""
    )
    conn.execute(
        """UPDATE allowance_definitions
           SET amount_type = 'config_per_hour', config_key = 'housing_allowance_per_hour', employee_field = NULL
           WHERE code = 'housing_hourly'"""
    )
    conn.execute(
        """UPDATE allowance_definitions
           SET amount_type = 'config_per_hour', config_key = 'food_allowance_per_hour', employee_field = NULL
           WHERE code = 'food_hourly'"""
    )
    print("    allowance_definitions: housing_fixed/food_fixed/housing_hourly/food_hourly re-pointed at global config")

    # --- Step 4: rebuild employees table without the 4 per-employee allowance columns ---
    if _employees_needs_rebuild(conn):
        conn.execute(
            """
            CREATE TABLE employees_new (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name           TEXT NOT NULL,
                device_enroll_no    TEXT,
                employment_type     TEXT NOT NULL CHECK (employment_type IN ('insured', 'non_insured')),
                is_exempt_from_shifts INTEGER NOT NULL DEFAULT 0,
                fixed_monthly_salary INTEGER,
                base_hourly_rate     INTEGER,
                is_married                   INTEGER DEFAULT 0,
                number_of_children           INTEGER DEFAULT 0,
                seniority_allowance          INTEGER DEFAULT 0,
                vacation_balance_days        REAL DEFAULT 0,
                active                       INTEGER NOT NULL DEFAULT 1,
                notes                        TEXT,
                created_at                   TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """INSERT INTO employees_new (
                   id, full_name, device_enroll_no, employment_type, is_exempt_from_shifts,
                   fixed_monthly_salary, base_hourly_rate, is_married, number_of_children,
                   seniority_allowance, vacation_balance_days, active, notes, created_at
               )
               SELECT
                   id, full_name, device_enroll_no, employment_type, is_exempt_from_shifts,
                   fixed_monthly_salary, base_hourly_rate, is_married, number_of_children,
                   seniority_allowance, vacation_balance_days, active, notes, created_at
               FROM employees"""
        )
        conn.execute("DROP TABLE employees")
        conn.execute("ALTER TABLE employees_new RENAME TO employees")
        print("[4/5] employees: rebuilt without housing/food allowance columns (active preserved as-is)")
    else:
        print("[4/5] employees: already migrated -- skipped rebuild")

    conn.execute("PRAGMA foreign_keys = ON;")

    # --- Step 5: integrity check before committing ---
    violations = conn.execute("PRAGMA foreign_key_check;").fetchall()
    if violations:
        conn.rollback()
        raise RuntimeError(f"Migration aborted -- foreign_key_check found violations: {violations}")
    conn.commit()
    print("[5/5] foreign_key_check passed, migration committed.")


def main():
    if not DB_PATH.exists():
        print(f"No database found at {DB_PATH} -- nothing to migrate (a fresh init_db() "
              f"will already create the new schema directly).")
        sys.exit(0)

    print(f"Migrating: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        migrate(conn)
    finally:
        conn.close()
    print("Done.")


if __name__ == "__main__":
    main()