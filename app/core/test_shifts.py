"""Checks for app.core.shifts's swap-suggestion algorithm against a real
in-memory SQLite db built from the actual schema.
Run: python -m app.core.test_shifts
"""
import sqlite3
from pathlib import Path

from app.core import shifts

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def _new_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute(
        """INSERT INTO shift_definitions (code, label, start_time, end_time, crosses_midnight) VALUES
               ('M', 'Morning', '08:00', '14:00', 0),
               ('E', 'Evening', '14:00', '20:00', 0),
               ('N', 'Night',   '20:00', '08:00', 1)"""
    )
    conn.execute(
        "INSERT INTO users (id, username, password_hash, role) VALUES (1, 'owner', 'x', 'owner')"
    )
    conn.commit()
    return conn


def _add_employee(conn: sqlite3.Connection, name: str) -> int:
    cur = conn.execute(
        "INSERT INTO employees (full_name, employment_type) VALUES (?, 'insured')", (name,)
    )
    conn.commit()
    return cur.lastrowid


def test_absent_employee_gets_a_covering_suggestion():
    conn = _new_db()
    absent = _add_employee(conn, "Absent Emp")
    coverer = _add_employee(conn, "Coverer Emp")

    shifts.save_month_schedule(conn, [(absent, "2026-06-01", "M")], user_id=1)
    # coverer clocked in during the M window but wasn't scheduled for it
    conn.execute(
        """INSERT INTO daily_attendance (employee_id, work_date, first_in, last_out, worked_hours, status)
           VALUES (?, '2026-06-01', '2026-06-01 08:10:00', '2026-06-01 14:05:00', 6, 'ok')""",
        (coverer,),
    )
    conn.commit()

    created = shifts.generate_swap_suggestions(conn, "2026-06-01", "2026-06-02")
    assert created == 1

    suggestions = shifts.list_swap_suggestions(conn, status="pending")
    assert len(suggestions) == 1
    assert suggestions[0]["absent_employee_id"] == absent
    assert suggestions[0]["covering_employee_id"] == coverer


def test_no_suggestion_when_scheduled_employee_showed_up():
    conn = _new_db()
    emp = _add_employee(conn, "Present Emp")
    shifts.save_month_schedule(conn, [(emp, "2026-06-01", "M")], user_id=1)
    conn.execute(
        """INSERT INTO daily_attendance (employee_id, work_date, first_in, last_out, worked_hours, status)
           VALUES (?, '2026-06-01', '2026-06-01 08:00:00', '2026-06-01 14:00:00', 6, 'ok')""",
        (emp,),
    )
    conn.commit()

    assert shifts.generate_swap_suggestions(conn, "2026-06-01", "2026-06-02") == 0
    assert shifts.list_swap_suggestions(conn) == []


def test_generate_is_idempotent_for_already_pending_suggestion():
    conn = _new_db()
    absent = _add_employee(conn, "Absent Emp")
    coverer = _add_employee(conn, "Coverer Emp")
    shifts.save_month_schedule(conn, [(absent, "2026-06-01", "M")], user_id=1)
    conn.execute(
        """INSERT INTO daily_attendance (employee_id, work_date, first_in, last_out, worked_hours, status)
           VALUES (?, '2026-06-01', '2026-06-01 08:10:00', '2026-06-01 14:05:00', 6, 'ok')""",
        (coverer,),
    )
    conn.commit()

    assert shifts.generate_swap_suggestions(conn, "2026-06-01", "2026-06-02") == 1
    assert shifts.generate_swap_suggestions(conn, "2026-06-01", "2026-06-02") == 0
    assert len(shifts.list_swap_suggestions(conn)) == 1


def test_decide_swap_suggestion_approve():
    conn = _new_db()
    absent = _add_employee(conn, "Absent Emp")
    coverer = _add_employee(conn, "Coverer Emp")
    shifts.save_month_schedule(conn, [(absent, "2026-06-01", "M")], user_id=1)
    conn.execute(
        """INSERT INTO daily_attendance (employee_id, work_date, first_in, last_out, worked_hours, status)
           VALUES (?, '2026-06-01', '2026-06-01 08:10:00', '2026-06-01 14:05:00', 6, 'ok')""",
        (coverer,),
    )
    conn.commit()
    shifts.generate_swap_suggestions(conn, "2026-06-01", "2026-06-02")
    suggestion_id = shifts.list_swap_suggestions(conn)[0]["id"]

    shifts.decide_swap_suggestion(conn, suggestion_id, approve=True, user_id=1)

    row = shifts.list_swap_suggestions(conn, status="approved")[0]
    assert row["id"] == suggestion_id
    assert row["decided_by"] == 1


def test_save_month_schedule_blank_code_deletes_cell():
    conn = _new_db()
    emp = _add_employee(conn, "Emp")
    shifts.save_month_schedule(conn, [(emp, "2026-06-01", "M")], user_id=1)
    assert shifts.get_schedule(conn, "2026-06-01", "2026-06-02") == {emp: {"2026-06-01": "M"}}

    shifts.save_month_schedule(conn, [(emp, "2026-06-01", "")], user_id=1)
    assert shifts.get_schedule(conn, "2026-06-01", "2026-06-02") == {}


def run_all():
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} checks passed")


if __name__ == "__main__":
    run_all()
