"""Checks for manual attendance entry (whole-month totals) + its
interaction with the device-recompute pipeline (the whole point of the
'source' column).
Run: python -m app.core.test_attendance_manual
"""
import sqlite3
from datetime import datetime
from pathlib import Path

from app.core import attendance_engine as ae

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"

JUNE_START, JUNE_END = "2026-06-01", "2026-07-01"


def _new_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    # iranian_holidays isn't in schema.sql -- app.core.holidays creates it
    # lazily via ensure_holiday_table(); build_payroll_inputs queries it
    # unconditionally, so the test db needs it too.
    conn.execute(
        """CREATE TABLE iranian_holidays (
               work_date TEXT PRIMARY KEY, label TEXT NOT NULL,
               source TEXT NOT NULL, confirmed INTEGER NOT NULL DEFAULT 1
           )"""
    )
    conn.commit()
    return conn


def _add_employee(conn: sqlite3.Connection, name: str, device_enroll_no: str = "100") -> int:
    cur = conn.execute(
        "INSERT INTO employees (full_name, employment_type, device_enroll_no) VALUES (?, 'insured', ?)",
        (name, device_enroll_no),
    )
    conn.commit()
    return cur.lastrowid


def test_save_month_attendance_no_holiday_hours_creates_one_row():
    conn = _new_db()
    emp = _add_employee(conn, "Emp")
    ae.save_manual_month_attendance(conn, emp, JUNE_START, JUNE_END, total_hours=180)

    rows = conn.execute("SELECT * FROM daily_attendance WHERE employee_id = ?", (emp,)).fetchall()
    assert len(rows) == 1
    assert rows[0]["source"] == "manual"
    assert rows[0]["status"] == "manual"
    assert rows[0]["worked_hours"] == 180


def test_save_month_attendance_splits_holiday_hours_onto_holiday_date():
    conn = _new_db()
    emp = _add_employee(conn, "Emp")
    conn.execute(
        "INSERT INTO iranian_holidays (work_date, label, source) VALUES ('2026-06-15', 'test holiday', 'manual')"
    )
    conn.commit()

    ae.save_manual_month_attendance(conn, emp, JUNE_START, JUNE_END, total_hours=180, holiday_hours=10)

    rows = {r["work_date"]: r for r in conn.execute(
        "SELECT * FROM daily_attendance WHERE employee_id = ?", (emp,)
    ).fetchall()}
    assert rows["2026-06-15"]["worked_hours"] == 10
    assert rows["2026-06-15"]["first_in"] is not None  # required for holiday-premium classification
    regular_rows = [r for d, r in rows.items() if d != "2026-06-15"]
    assert len(regular_rows) == 1
    assert regular_rows[0]["worked_hours"] == 170


def test_holiday_hours_without_a_recorded_holiday_date_raises():
    conn = _new_db()
    emp = _add_employee(conn, "Emp")
    try:
        ae.save_manual_month_attendance(conn, emp, JUNE_START, JUNE_END, total_hours=180, holiday_hours=10)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_holiday_hours_cannot_exceed_total_hours():
    conn = _new_db()
    emp = _add_employee(conn, "Emp")
    try:
        ae.save_manual_month_attendance(conn, emp, JUNE_START, JUNE_END, total_hours=5, holiday_hours=10)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_resaving_a_month_replaces_not_adds():
    conn = _new_db()
    emp = _add_employee(conn, "Emp")
    ae.save_manual_month_attendance(conn, emp, JUNE_START, JUNE_END, total_hours=180)
    ae.save_manual_month_attendance(conn, emp, JUNE_START, JUNE_END, total_hours=150)

    rows = conn.execute("SELECT * FROM daily_attendance WHERE employee_id = ?", (emp,)).fetchall()
    assert len(rows) == 1
    assert rows[0]["worked_hours"] == 150


def test_recompute_does_not_wipe_manual_entry_with_no_device_sessions():
    conn = _new_db()
    emp = _add_employee(conn, "Emp")
    ae.save_manual_month_attendance(conn, emp, JUNE_START, JUNE_END, total_hours=180)

    # Simulate a "Compute attendance" run for June that found zero sessions
    # for this employee (e.g. device had no punches that month at all).
    att = ae.EmployeeAttendance(employee_id=emp, full_name="Emp", employment_type="insured", sessions=[])
    ae.persist_daily_attendance(conn, [att], datetime(2026, 6, 1), datetime(2026, 7, 1))

    rows = conn.execute("SELECT * FROM daily_attendance WHERE employee_id = ?", (emp,)).fetchall()
    assert len(rows) == 1, "manual entry was wiped by recompute -- the bug the 'source' column exists to prevent"
    assert rows[0]["source"] == "manual"
    assert rows[0]["worked_hours"] == 180


def test_real_device_punch_on_same_day_reclassifies_as_device():
    conn = _new_db()
    emp = _add_employee(conn, "Emp")
    ae.save_manual_month_attendance(conn, emp, JUNE_START, JUNE_END, total_hours=180)
    # The manual entry landed on period_start (2026-06-01) since there's no
    # holiday in this test's period -- a real punch that same day should
    # reclassify that row back to 'device'.
    session = ae.WorkSession(
        employee_id=emp, in_time=datetime(2026, 6, 1, 8, 0), out_time=datetime(2026, 6, 1, 14, 0),
        hours=6.0, note="ok",
    )
    att = ae.EmployeeAttendance(employee_id=emp, full_name="Emp", employment_type="insured", sessions=[session])
    ae.persist_daily_attendance(conn, [att], datetime(2026, 6, 1), datetime(2026, 7, 1))

    row = conn.execute(
        "SELECT * FROM daily_attendance WHERE employee_id = ? AND work_date = '2026-06-01'", (emp,)
    ).fetchone()
    assert row["source"] == "device"
    assert row["worked_hours"] == 6.0


def test_delete_manual_month_attendance_only_removes_manual_rows():
    conn = _new_db()
    emp = _add_employee(conn, "Emp")
    ae.save_manual_month_attendance(conn, emp, JUNE_START, JUNE_END, total_hours=180)
    ae.delete_manual_month_attendance(conn, emp, JUNE_START, JUNE_END)
    assert conn.execute("SELECT * FROM daily_attendance WHERE employee_id = ?", (emp,)).fetchone() is None


def test_manual_hours_feed_into_build_payroll_inputs():
    conn = _new_db()
    emp = _add_employee(conn, "Emp")
    conn.execute(
        "INSERT INTO iranian_holidays (work_date, label, source) VALUES ('2026-06-15', 'test holiday', 'manual')"
    )
    conn.commit()
    ae.save_manual_month_attendance(conn, emp, JUNE_START, JUNE_END, total_hours=180, holiday_hours=10)

    worked_hours, holiday_hours = ae.build_payroll_inputs(conn, datetime(2026, 6, 1), datetime(2026, 7, 1))[emp]
    assert worked_hours == 180
    assert holiday_hours == 10


def test_manual_attendance_month_totals_collapses_rows_for_display():
    conn = _new_db()
    emp = _add_employee(conn, "Emp")
    conn.execute(
        "INSERT INTO iranian_holidays (work_date, label, source) VALUES ('2026-06-15', 'test holiday', 'manual')"
    )
    conn.commit()
    ae.save_manual_month_attendance(conn, emp, JUNE_START, JUNE_END, total_hours=180, holiday_hours=10)

    totals = ae.manual_attendance_month_totals(conn, JUNE_START, JUNE_END)
    assert totals[emp]["total_hours"] == 180
    assert totals[emp]["holiday_hours"] == 10


def run_all():
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} checks passed")


if __name__ == "__main__":
    run_all()
