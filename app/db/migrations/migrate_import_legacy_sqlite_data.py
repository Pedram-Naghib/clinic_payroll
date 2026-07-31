"""
One-time data import: copies real business data out of the legacy desktop
app's data/clinic.db (SQLite) into whatever database app.db.database.get_connection()
currently points at (Postgres, when DATABASE_URL is set -- i.e. the web app's DB).

Why this exists: the Postgres schema was ported from clinic.db (Phase 0), but
only the *shape* -- the actual rows (31 employees, their role assignments,
324 days of attendance history, commissions, and the owner's real allowance/
leave-cap config) never got copied over. This script does that copy, once.

Run:
    docker compose exec web python -m app.db.migrations.migrate_import_legacy_sqlite_data

Safety:
  - Refuses to run if the target `employees` table is not empty (prevents
    double-importing/duplicating 31 real people on a second run).
  - Only touches tables where the target was actually missing data:
    employees, roles, employee_roles, daily_attendance, direct_commissions,
    iranian_holidays, system_config. Nothing else (users, raw_punches,
    payroll_runs, leave_requests, ... ) is touched -- those were empty on
    BOTH sides, so there's nothing to import.
  - employees.id is preserved (OVERRIDING SYSTEM VALUE) because
    employee_roles / daily_attendance / direct_commissions / users all key
    off it; the identity sequence is reset afterward so future INSERTs
    (add_employee) don't collide.
  - roles are merged BY NAME, not by id: 'بهیار'/'پذیرش' already exist in
    Postgres (seeded by app/db/database.py) with different ids than in
    SQLite, so re-using SQLite's raw ids would either collide or silently
    create duplicate-named roles. Every other table that references a role
    goes through the name->id map built here.
"""
from __future__ import annotations
import sqlite3
import sys
from pathlib import Path

from app.db.database import get_connection

SQLITE_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "clinic.db"


def _sqlite_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_employees(src: sqlite3.Connection, dst) -> int:
    rows = src.execute("SELECT * FROM employees ORDER BY id").fetchall()
    for r in rows:
        dst.execute(
            """INSERT INTO employees (
                   id, full_name, device_enroll_no, employment_type, is_exempt_from_shifts,
                   fixed_monthly_salary, base_hourly_rate, is_married, number_of_children,
                   seniority_allowance, vacation_balance_days, active, notes, created_at
               ) OVERRIDING SYSTEM VALUE VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                r["id"], r["full_name"], r["device_enroll_no"], r["employment_type"],
                r["is_exempt_from_shifts"], r["fixed_monthly_salary"], r["base_hourly_rate"],
                r["is_married"], r["number_of_children"], r["seniority_allowance"],
                r["vacation_balance_days"], r["active"], r["notes"], r["created_at"],
            ),
        )
    if rows:
        dst.execute(
            "SELECT setval(pg_get_serial_sequence('employees', 'id'), (SELECT MAX(id) FROM employees))"
        )
    dst.commit()
    return len(rows)


def _migrate_roles_and_assignments(src: sqlite3.Connection, dst) -> tuple[int, int]:
    name_to_dst_id: dict[str, int] = {
        row["name"]: row["id"] for row in dst.execute("SELECT id, name FROM roles").fetchall()
    }
    new_roles = 0
    for row in src.execute("SELECT id, name FROM roles ORDER BY id").fetchall():
        if row["name"] in name_to_dst_id:
            continue
        cur = dst.execute("INSERT INTO roles (name) VALUES (?)", (row["name"],))
        name_to_dst_id[row["name"]] = cur.lastrowid
        new_roles += 1
    dst.commit()

    src_role_names = {row["id"]: row["name"] for row in src.execute("SELECT id, name FROM roles").fetchall()}
    assignments = 0
    for row in src.execute("SELECT employee_id, role_id FROM employee_roles").fetchall():
        role_name = src_role_names.get(row["role_id"])
        dst_role_id = name_to_dst_id.get(role_name)
        if dst_role_id is None:
            continue
        dst.execute(
            "INSERT INTO employee_roles (employee_id, role_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
            (row["employee_id"], dst_role_id),
        )
        assignments += 1
    dst.commit()
    return new_roles, assignments


def _migrate_daily_attendance(src: sqlite3.Connection, dst) -> int:
    rows = src.execute("SELECT * FROM daily_attendance ORDER BY id").fetchall()
    for r in rows:
        dst.execute(
            """INSERT INTO daily_attendance (
                   employee_id, work_date, first_in, last_out, worked_hours,
                   planned_shift_code, status, manager_reviewed, manager_note
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(employee_id, work_date) DO NOTHING""",
            (
                r["employee_id"], r["work_date"], r["first_in"], r["last_out"], r["worked_hours"],
                r["planned_shift_code"], r["status"], r["manager_reviewed"], r["manager_note"],
            ),
        )
    dst.commit()
    return len(rows)


def _migrate_direct_commissions(src: sqlite3.Connection, dst) -> int:
    rows = src.execute("SELECT * FROM direct_commissions ORDER BY id").fetchall()
    for r in rows:
        dst.execute(
            """INSERT INTO direct_commissions (
                   employee_id, service_type, fee_received, commission_rate, commission_amount,
                   service_date, notes, recorded_by, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                r["employee_id"], r["service_type"], r["fee_received"], r["commission_rate"],
                r["commission_amount"], r["service_date"], r["notes"], None, r["created_at"],
            ),
        )
    dst.commit()
    return len(rows)


def _migrate_holidays(src: sqlite3.Connection, dst) -> int:
    rows = src.execute("SELECT * FROM iranian_holidays ORDER BY work_date").fetchall()
    for r in rows:
        dst.execute(
            """INSERT INTO iranian_holidays (work_date, label, source, confirmed)
               VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING""",
            (r["work_date"], r["label"], r["source"], r["confirmed"]),
        )
    dst.commit()
    return len(rows)


def _migrate_system_config(src: sqlite3.Connection, dst) -> int:
    rows = src.execute("SELECT * FROM system_config ORDER BY key").fetchall()
    for r in rows:
        dst.execute(
            """INSERT INTO system_config (key, value, value_type, label, description, category)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value, value_type = excluded.value_type""",
            (r["key"], r["value"], r["value_type"], r["label"], r["description"], r["category"]),
        )
    dst.commit()
    return len(rows)


def main() -> None:
    if not SQLITE_PATH.exists():
        print(f"No legacy database at {SQLITE_PATH} -- nothing to import.")
        sys.exit(0)

    dst = get_connection()
    try:
        existing = dst.execute("SELECT COUNT(*) AS n FROM employees").fetchone()["n"]
        if existing:
            print(f"Target `employees` table already has {existing} rows -- refusing to run "
                  f"(this script is not safe to re-run once data exists, to avoid duplicates).")
            sys.exit(1)

        src = _sqlite_conn()
        try:
            n_emp = _migrate_employees(src, dst)
            print(f"[1/6] employees: imported {n_emp}")

            n_roles, n_assign = _migrate_roles_and_assignments(src, dst)
            print(f"[2/6] roles: added {n_roles} new role names; employee_roles: {n_assign} assignments")

            n_att = _migrate_daily_attendance(src, dst)
            print(f"[3/6] daily_attendance: imported {n_att}")

            n_comm = _migrate_direct_commissions(src, dst)
            print(f"[4/6] direct_commissions: imported {n_comm}")

            n_hol = _migrate_holidays(src, dst)
            print(f"[5/6] iranian_holidays: imported {n_hol} (existing rows for other years untouched)")

            n_cfg = _migrate_system_config(src, dst)
            print(f"[6/6] system_config: upserted {n_cfg} keys with the real configured values")
        finally:
            src.close()
    finally:
        dst.close()
    print("Done.")


if __name__ == "__main__":
    main()
