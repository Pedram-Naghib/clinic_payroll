"""
Import raw punches from Zaman Pardaz .TXT exports into the database.

- Each parsed punch is inserted into raw_punches.
- The employee_id is resolved on insert via employees.device_enroll_no lookup.
- Exact duplicates (same enroll-no + datetime + mode) are skipped silently
  thanks to the UNIQUE constraint, so re-importing the same file is safe.
- Punches with an enroll-no not matching any employee are still stored,
  with employee_id = NULL. They can be retroactively linked later
  via relink_unmatched_punches() once the employee record exists.
- delete_punches_in_period() / delete_all_punches() support the Attendance
  tab's "clear records" buttons, used for re-importing a corrected device
  file for a given month, or resetting entirely.
"""

from __future__ import annotations
import sqlite3
from pathlib import Path

from app.core.zamanpardaz_parser import parse_zamanpardaz_txt


def import_punches_file(conn: sqlite3.Connection, file_path: str | Path) -> dict:
    """Returns: {
        'parsed': total rows in the file,
        'inserted': new rows added,
        'duplicates': rows ignored due to UNIQUE conflict,
        'unmatched_enroll_nos': sorted list of EnNo values with no employee match,
        'unmatched_count': how many punches had no employee match,
    }
    """
    file_path = Path(file_path)
    punches = parse_zamanpardaz_txt(file_path)

    inserted = 0
    duplicates = 0
    unmatched = {}  # enroll_no -> punch count

    for p in punches:
        emp_row = conn.execute(
            "SELECT id FROM employees WHERE device_enroll_no = ?",
            (p.device_enroll_no,),
        ).fetchone()
        emp_id = emp_row["id"] if emp_row else None
        if emp_id is None:
            unmatched[p.device_enroll_no] = unmatched.get(p.device_enroll_no, 0) + 1

        try:
            conn.execute(
                """INSERT INTO raw_punches
                   (device_enroll_no, employee_id, punch_datetime, raw_mode,
                    raw_inout_flag, source_file)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    p.device_enroll_no, emp_id,
                    p.punch_datetime.strftime("%Y-%m-%d %H:%M:%S"),
                    p.mode, p.raw_inout_flag, file_path.name,
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            duplicates += 1

    conn.commit()

    return {
        "parsed": len(punches),
        "inserted": inserted,
        "duplicates": duplicates,
        "unmatched_enroll_nos": sorted(unmatched.keys(), key=lambda x: (len(x), x)),
        "unmatched_count": sum(unmatched.values()),
    }


def relink_unmatched_punches(conn: sqlite3.Connection) -> int:
    """After a new device_enroll_no is added to an employee, this pass
    re-resolves any orphan punches (employee_id IS NULL) that now match.
    Returns the number of punches successfully linked.
    """
    cur = conn.execute(
        """UPDATE raw_punches
           SET employee_id = (
               SELECT id FROM employees
               WHERE employees.device_enroll_no = raw_punches.device_enroll_no
           )
           WHERE employee_id IS NULL"""
    )
    conn.commit()
    return cur.rowcount


def delete_punches_in_period(conn: sqlite3.Connection, period_start, period_end) -> int:
    """Delete all raw_punches with punch_datetime in [period_start, period_end).

    Used by the "clear this month's records" button so a device file can be
    re-imported cleanly for a single Jalali month without touching any other
    period's data. Returns the number of rows deleted.
    """
    cur = conn.execute(
        """DELETE FROM raw_punches
           WHERE punch_datetime >= ? AND punch_datetime < ?""",
        (period_start.strftime("%Y-%m-%d %H:%M:%S"), period_end.strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    return cur.rowcount


def delete_all_punches(conn: sqlite3.Connection) -> int:
    """Wipe every row from raw_punches (full reset). Returns rows deleted."""
    cur = conn.execute("DELETE FROM raw_punches")
    conn.commit()
    return cur.rowcount


def punch_summary(conn: sqlite3.Connection) -> dict:
    """Quick stats on the raw_punches table for diagnostics."""
    total = conn.execute("SELECT COUNT(*) AS n FROM raw_punches").fetchone()["n"]
    unmatched = conn.execute(
        "SELECT COUNT(*) AS n FROM raw_punches WHERE employee_id IS NULL"
    ).fetchone()["n"]
    earliest = conn.execute(
        "SELECT MIN(punch_datetime) AS d FROM raw_punches"
    ).fetchone()["d"]
    latest = conn.execute(
        "SELECT MAX(punch_datetime) AS d FROM raw_punches"
    ).fetchone()["d"]
    return {
        "total": total,
        "unmatched": unmatched,
        "earliest": earliest,
        "latest": latest,
    }