"""
Employee CRUD operations.
"""

from __future__ import annotations
import sqlite3
from dataclasses import dataclass, field


@dataclass
class EmployeeInput:
    full_name: str
    employment_type: str  # 'insured' | 'non_insured'
    device_enroll_no: str | None = None
    is_exempt_from_shifts: bool = False
    fixed_monthly_salary: int | None = None   # insured: base monthly salary. non_insured: flat add-on (e.g. Rahmani)
    base_hourly_rate: int | None = None        # non_insured: explicit hourly rate; insured: auto-derived if None
    is_married: bool = False
    number_of_children: int = 0
    seniority_allowance: int = 0
    vacation_balance_days: float = 0
    notes: str | None = None


BASE_MONTHLY_HOURS = 192


def add_employee(conn: sqlite3.Connection, emp: EmployeeInput) -> int:
    base_hourly = emp.base_hourly_rate
    if emp.employment_type == "insured" and base_hourly is None and emp.fixed_monthly_salary:
        base_hourly = round(emp.fixed_monthly_salary / BASE_MONTHLY_HOURS)

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
    base_hourly = emp.base_hourly_rate
    if emp.employment_type == "insured" and base_hourly is None and emp.fixed_monthly_salary:
        base_hourly = round(emp.fixed_monthly_salary / BASE_MONTHLY_HOURS)

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