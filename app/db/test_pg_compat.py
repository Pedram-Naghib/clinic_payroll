"""Pure-function checks for pg_compat.translate_sql and Row -- no DB connection needed.
Run: python -m app.db.test_pg_compat
"""
from app.db.pg_compat import Row, translate_sql


def test_plain_select_translates_placeholders():
    sql, wants_id = translate_sql("SELECT * FROM employees WHERE id = ?")
    assert sql == "SELECT * FROM employees WHERE id = %s"
    assert wants_id is False


def test_bare_insert_gets_returning_id():
    sql, wants_id = translate_sql(
        "INSERT INTO employees (full_name, employment_type) VALUES (?, ?)"
    )
    assert sql == "INSERT INTO employees (full_name, employment_type) VALUES (%s, %s) RETURNING id"
    assert wants_id is True


def test_multiline_bare_insert_gets_returning_id():
    # real shape from app/core/employees.py -- leading newline + indentation before INSERT
    sql, wants_id = translate_sql(
        """
        INSERT INTO employees (
            full_name, device_enroll_no, employment_type, is_exempt_from_shifts,
            fixed_monthly_salary, base_hourly_rate,
            is_married, number_of_children,
            seniority_allowance,
            vacation_balance_days, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
    )
    assert wants_id is True
    assert sql.rstrip().endswith("RETURNING id")
    assert "?" not in sql


def test_insert_with_on_conflict_do_nothing_is_not_touched_for_lastrowid():
    # real shape from app/core/roles.py (post dialect-neutral fix)
    sql, wants_id = translate_sql(
        "INSERT INTO roles (name) VALUES (?) ON CONFLICT DO NOTHING"
    )
    assert sql == "INSERT INTO roles (name) VALUES (%s) ON CONFLICT DO NOTHING"
    assert wants_id is False


def test_insert_with_on_conflict_do_update_is_not_touched_for_lastrowid():
    # real shape from app/core/attendance_engine.py's daily_attendance upsert
    sql, wants_id = translate_sql(
        """
        INSERT INTO daily_attendance
            (employee_id, work_date, first_in, last_out, worked_hours, status)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(employee_id, work_date) DO UPDATE SET
            first_in = excluded.first_in,
            last_out = excluded.last_out,
            worked_hours = excluded.worked_hours,
            status = excluded.status
        """
    )
    assert wants_id is False
    assert "RETURNING" not in sql.upper()
    assert "?" not in sql


def test_update_statement_untouched_besides_placeholders():
    sql, wants_id = translate_sql(
        "UPDATE system_config SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?"
    )
    assert sql == "UPDATE system_config SET value = %s, updated_at = CURRENT_TIMESTAMP WHERE key = %s"
    assert wants_id is False


def test_delete_statement_untouched_besides_placeholders():
    sql, wants_id = translate_sql("DELETE FROM employees WHERE id = ?")
    assert sql == "DELETE FROM employees WHERE id = %s"
    assert wants_id is False


def test_query_with_no_placeholders_untouched():
    sql, wants_id = translate_sql("SELECT * FROM system_config ORDER BY category, label")
    assert sql == "SELECT * FROM system_config ORDER BY category, label"
    assert wants_id is False


def test_row_supports_string_key_access():
    row = Row(["id", "full_name"], [3, "تست"])
    assert row["id"] == 3
    assert row["full_name"] == "تست"


def test_row_supports_positional_index_access():
    row = Row(["id", "full_name"], [3, "تست"])
    assert row[0] == 3
    assert row[1] == "تست"


def test_row_tuple_unpacking_yields_values_not_keys():
    # the exact bug this Row class exists to prevent: attendance_engine.py
    # does `for (emp_id,) in conn.execute("SELECT id FROM employees...")` --
    # a plain dict-row would unpack to its KEY ("id") instead of the value.
    row = Row(["id"], [42])
    (emp_id,) = row
    assert emp_id == 42


def run_all():
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} checks passed")


if __name__ == "__main__":
    run_all()
