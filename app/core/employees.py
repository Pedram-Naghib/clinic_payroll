"""
Employee CRUD operations.
"""

from __future__ import annotations
import sqlite3
from dataclasses import dataclass, field

from app.core.config import get_config


@dataclass
class EmployeeInput:
    full_name: str
    employment_type: str  # 'insured' | 'non_insured'
    device_enroll_no: str | None = None
    is_exempt_from_shifts: bool = False
    fixed_monthly_salary: int | None = None   # insured: base monthly salary. non_insured: flat add-on (e.g. Rahmani)
    base_hourly_rate: int | None = None        # non_insured: explicit hourly rate; insured: auto-derived if left blank/0
    is_married: bool = False
    number_of_children: int = 0
    seniority_allowance: int = 0
    vacation_balance_days: float = 0
    notes: str | None = None


# Fallback only -- add_employee/update_employee read the live, Owner-editable
# system_config['base_monthly_hours'] instead whenever a connection is
# available, so a later change to that setting doesn't leave newly-derived
# hourly rates using a stale hardcoded value.
BASE_MONTHLY_HOURS = 192


def add_employee(conn: sqlite3.Connection, emp: EmployeeInput) -> int:
    base_hours = get_config(conn, "base_monthly_hours", default=BASE_MONTHLY_HOURS)
    base_hourly = emp.base_hourly_rate
    # Treat 0 the same as "left blank" -- a "0" typed into the hourly-rate
    # field (or an old CSV import with an explicit 0) should never silently
    # override the derived rate, since base_pay/overtime/under-hours math
    # all depend on this being a real, non-zero hourly rate for insured staff.
    if emp.employment_type == "insured" and not base_hourly and emp.fixed_monthly_salary:
        base_hourly = round(emp.fixed_monthly_salary / base_hours) if base_hours else 0

    cur = conn.execute(
        """
        INSERT INTO employees (
            full_name, device_enroll_no, employment_type, is_exempt_from_shifts,
            fixed_monthly_salary, base_hourly_rate,
            is_married, number_of_children,
            seniority_allowance,
            vacation_balance_days, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            emp.full_name, emp.device_enroll_no, emp.employment_type,
            int(emp.is_exempt_from_shifts),
            emp.fixed_monthly_salary, base_hourly,
            int(emp.is_married), emp.number_of_children,
            emp.seniority_allowance,
            emp.vacation_balance_days, emp.notes,
        ),
    )
    conn.commit()
    return cur.lastrowid


def update_employee(conn: sqlite3.Connection, employee_id: int, emp: EmployeeInput) -> None:
    base_hours = get_config(conn, "base_monthly_hours", default=BASE_MONTHLY_HOURS)
    base_hourly = emp.base_hourly_rate
    if emp.employment_type == "insured" and not base_hourly and emp.fixed_monthly_salary:
        base_hourly = round(emp.fixed_monthly_salary / base_hours) if base_hours else 0

    conn.execute(
        """
        UPDATE employees SET
            full_name = ?, device_enroll_no = ?, employment_type = ?, is_exempt_from_shifts = ?,
            fixed_monthly_salary = ?, base_hourly_rate = ?,
            is_married = ?, number_of_children = ?,
            seniority_allowance = ?,
            vacation_balance_days = ?, notes = ?
        WHERE id = ?
        """,
        (
            emp.full_name, emp.device_enroll_no, emp.employment_type,
            int(emp.is_exempt_from_shifts),
            emp.fixed_monthly_salary, base_hourly,
            int(emp.is_married), emp.number_of_children,
            emp.seniority_allowance,
            emp.vacation_balance_days, emp.notes,
            employee_id,
        ),
    )
    conn.commit()


def delete_employee(conn: sqlite3.Connection, employee_id: int, hard_delete: bool = False) -> None:
    """Soft-delete by default (active=0) to preserve payroll history/FK integrity."""
    if hard_delete:
        conn.execute("DELETE FROM employees WHERE id = ?", (employee_id,))
    else:
        conn.execute("UPDATE employees SET active = 0 WHERE id = ?", (employee_id,))
    conn.commit()


def list_employees(conn: sqlite3.Connection, active_only: bool = True) -> list[sqlite3.Row]:
    q = "SELECT * FROM employees"
    if active_only:
        q += " WHERE active = 1"
    q += " ORDER BY full_name"
    return conn.execute(q).fetchall()


def set_device_enroll_no(conn: sqlite3.Connection, employee_id: int, enroll_no: str) -> None:
    conn.execute(
        "UPDATE employees SET device_enroll_no = ? WHERE id = ?", (enroll_no, employee_id)
    )
    conn.commit()


def get_employee_by_enroll_no(conn: sqlite3.Connection, enroll_no: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM employees WHERE device_enroll_no = ?", (enroll_no,)
    ).fetchone()