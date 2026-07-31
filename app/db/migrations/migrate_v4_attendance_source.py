"""
One-time migration: daily_attendance.source ('device' | 'manual').

Run automatically at every app startup from app/ui/main_window.py (idempotent,
same convention as migrate_v3). Can also be run standalone:

    python -m app.db.migrations.migrate_v4_attendance_source

What this does:
  Adds `source TEXT NOT NULL DEFAULT 'device'` to daily_attendance if it's
  missing, so manually-entered attendance rows (the Owner overriding/filling
  in a day they don't trust the device for) survive
  attendance_engine.persist_daily_attendance()'s per-employee/period
  DELETE-then-reinsert instead of being silently wiped on the next
  "Compute attendance" click. Mirrors the Postgres migration
  migrations/versions/a1b2c3d4e5f6_daily_attendance_source.py.
"""

from __future__ import annotations
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "clinic.db"


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def migrate(conn: sqlite3.Connection) -> None:
    if "source" not in _table_columns(conn, "daily_attendance"):
        conn.execute(
            "ALTER TABLE daily_attendance ADD COLUMN source TEXT NOT NULL DEFAULT 'device'"
        )
        conn.commit()
        print("[1/1] daily_attendance: added 'source' column (default 'device')")
    else:
        print("[1/1] daily_attendance: 'source' column already present -- skipped")


def main():
    if not DB_PATH.exists():
        print(f"No database found at {DB_PATH} -- nothing to migrate.")
        sys.exit(0)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        migrate(conn)
    finally:
        conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
