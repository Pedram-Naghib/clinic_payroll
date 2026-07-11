"""
One-time migration: leave-tracking audit columns + payslip support + data backfill.

Run automatically at every app startup from app/ui/main_window.py (idempotent,
same convention as init_db()). Can also be run standalone:

    python -m app.db.migrations.migrate_v3_leave_payslip

What this does:
  1. leave_requests: adds `notes`, `source` ('manual' | 'auto_shortfall'), and
     `payroll_run_id` (nullable FK) so automatic shortfall-coverage entries
     created by payroll_runs.save_payroll_run() are traceable to the run that
     created them, and can be cleanly reversed if that run is overwritten.
  2. payroll_line_items: adds `leave_days_covered` (days drawn from the
     employee's vacation_balance_days to cover an hours shortfall this run).
  3. system_config: seeds `annual_paid_leave_days_cap` = 30 (Owner-editable,
     matches the existing pattern for every other constant).
  4. Data backfill: any `insured` employee whose base_hourly_rate is 0 or
     NULL (the UI's "0" text field bug -- see employees.py / employees_tab.py)
     but who has a fixed_monthly_salary gets base_hourly_rate recomputed as
     round(fixed_monthly_salary / base_monthly_hours). Fixes stale rows like
     Leila Ranjkesh's (id=3) whose base_hourly_rate was stuck at 0.
  5. Corrects the stale English `system_config.description` text for
     `overtime_premium_pct` that used to (wrongly) reference shift code 'H'
     ("Help") -- 'H' has nothing to do with overtime; on the manager's paper
     it denotes a holiday day. The Persian label shown in the Config tab
     already comes from app/ui/strings_fa.py (fixed separately); this just
     keeps the underlying DB row consistent for anyone inspecting it directly.
"""

from __future__ import annotations
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "clinic.db"


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def migrate(conn: sqlite3.Connection) -> None:
    # --- Step 1: leave_requests audit columns ---
    leave_cols = _table_columns(conn, "leave_requests")
    if "notes" not in leave_cols:
        conn.execute("ALTER TABLE leave_requests ADD COLUMN notes TEXT")
        print("[1/5] leave_requests: added 'notes'")
    if "source" not in leave_cols:
        conn.execute(
            """ALTER TABLE leave_requests ADD COLUMN source TEXT NOT NULL
               DEFAULT 'manual' CHECK (source IN ('manual','auto_shortfall'))"""
        )
        print("[1/5] leave_requests: added 'source'")
    if "payroll_run_id" not in leave_cols:
        conn.execute(
            "ALTER TABLE leave_requests ADD COLUMN payroll_run_id INTEGER REFERENCES payroll_runs(id)"
        )
        print("[1/5] leave_requests: added 'payroll_run_id'")
    if leave_cols >= {"notes", "source", "payroll_run_id"}:
        print("[1/5] leave_requests: already migrated -- skipped")

    # --- Step 2: payroll_line_items.leave_days_covered ---
    line_item_cols = _table_columns(conn, "payroll_line_items")
    if "leave_days_covered" not in line_item_cols:
        conn.execute(
            "ALTER TABLE payroll_line_items ADD COLUMN leave_days_covered REAL DEFAULT 0"
        )
        print("[2/5] payroll_line_items: added 'leave_days_covered'")
    else:
        print("[2/5] payroll_line_items: already migrated -- skipped")

    # --- Step 3: annual paid leave cap config ---
    conn.execute(
        """INSERT OR IGNORE INTO system_config (key, value, value_type, label, description, category)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            "annual_paid_leave_days_cap", "30", "int",
            "Annual Paid Leave Cap (days)",
            "Maximum paid vacation days per employee per Jalali year",
            "leave",
        ),
    )
    print("[3/5] system_config: annual_paid_leave_days_cap ready")

    # --- Step 4: backfill base_hourly_rate for insured employees stuck at 0/NULL ---
    base_hours_row = conn.execute(
        "SELECT value FROM system_config WHERE key = 'base_monthly_hours'"
    ).fetchone()
    base_hours = int(base_hours_row[0]) if base_hours_row else 192

    stale = conn.execute(
        """SELECT id, fixed_monthly_salary FROM employees
           WHERE employment_type = 'insured'
             AND (base_hourly_rate IS NULL OR base_hourly_rate = 0)
             AND fixed_monthly_salary IS NOT NULL AND fixed_monthly_salary > 0"""
    ).fetchall()
    for emp_id, salary in stale:
        new_rate = round(salary / base_hours)
        conn.execute(
            "UPDATE employees SET base_hourly_rate = ? WHERE id = ?", (new_rate, emp_id)
        )
    print(f"[4/5] employees: backfilled base_hourly_rate for {len(stale)} insured employee(s)")

    # --- Step 5: fix stale 'H (Help)' description text ---
    conn.execute(
        "UPDATE system_config SET description = ? WHERE key = 'overtime_premium_pct' AND description LIKE ?",
        ("Extra % over base hourly rate for hours worked beyond base_monthly_hours", "%'H'%"),
    )
    print("[5/5] system_config: corrected stale 'H (Help)' description if present")

    conn.commit()


def main():
    if not DB_PATH.exists():
        print(f"No database found at {DB_PATH} -- nothing to migrate.")
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
