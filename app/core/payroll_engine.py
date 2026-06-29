"""
Payroll Calculation Engine.

DEVICE-ID-BASED PAY MODE (in addition to the is_exempt_from_shifts flag):
  - device_enroll_no = '-1'  -> pay fixed_monthly_salary in full, no hour math.
                                Used for staff who don't clock in (e.g. Pegah).
  - device_enroll_no = '0'   -> missing/incomplete info; payroll is SKIPPED
                                until a real device ID (or -1) is provided.
                                calculate_payroll_for_employee returns None.
  - any other value           -> normal hour-based calculation.
"""

from __future__ import annotations
import sqlite3
from dataclasses import dataclass, field

from app.core.config import get_config
from app.core.allowance_engine import compute_allowances_for_employee, AllowanceResult


@dataclass
class PayrollResult:
    employee_id: int
    full_name: str
    employment_type: str
    regular_hours: float
    overtime_hours: float
    holiday_hours: float
    base_pay: int = 0
    overtime_pay: int = 0
    holiday_pay: int = 0
    allowances: list[AllowanceResult] = field(default_factory=list)
    insurance_deduction: int = 0
    total_pay: int = 0
    pay_mode: str = "hourly"  # 'hourly' | 'fixed_no_clocking'
    notes: list[str] = field(default_factory=list)

    @property
    def allowances_total(self) -> int:
        return sum(a.amount for a in self.allowances)

    def to_dict(self) -> dict:
        return {
            "employee_id": self.employee_id,
            "full_name": self.full_name,
            "employment_type": self.employment_type,
            "pay_mode": self.pay_mode,
            "regular_hours": self.regular_hours,
            "overtime_hours": self.overtime_hours,
            "holiday_hours": self.holiday_hours,
            "base_pay": self.base_pay,
            "overtime_pay": self.overtime_pay,
            "holiday_pay": self.holiday_pay,
            "allowances": [
                {"code": a.code, "label": a.label, "amount": a.amount} for a in self.allowances
            ],
            "allowances_total": self.allowances_total,
            "insurance_deduction": self.insurance_deduction,
            "total_pay": self.total_pay,
            "notes": self.notes,
        }


def _is_fixed_no_clocking(employee: sqlite3.Row) -> bool:
    """True if employee gets fixed_monthly_salary in full with no hour math."""
    if employee["is_exempt_from_shifts"]:
        return True
    dev = str(employee["device_enroll_no"] or "").strip()
    return dev == "-1"


def _is_payroll_skipped(employee: sqlite3.Row) -> bool:
    """True if employee should be skipped (device_enroll_no = '0')."""
    dev = str(employee["device_enroll_no"] or "").strip()
    return dev == "0"


def calculate_payroll_for_employee(
    conn: sqlite3.Connection,
    employee: sqlite3.Row,
    worked_hours: float,
    holiday_hours: float = 0.0,
) -> PayrollResult | None:
    """Returns None if employee has device_enroll_no = '0' (missing info)."""
    if _is_payroll_skipped(employee):
        return None

    base_hours = get_config(conn, "base_monthly_hours", default=192)
    overtime_premium_pct = get_config(conn, "overtime_premium_pct", default=40)
    holiday_premium_pct = get_config(conn, "holiday_premium_pct", default=30)
    insurance_pct = get_config(conn, "insurance_deduction_pct", default=7)

    employment_type = employee["employment_type"]
    base_hourly_rate = employee["base_hourly_rate"] or 0
    fixed_monthly_salary = employee["fixed_monthly_salary"] or 0

    result = PayrollResult(
        employee_id=employee["id"],
        full_name=employee["full_name"],
        employment_type=employment_type,
        regular_hours=0,
        overtime_hours=0,
        holiday_hours=holiday_hours,
    )

    # === Fixed-no-clocking mode ===
    if _is_fixed_no_clocking(employee):
        result.pay_mode = "fixed_no_clocking"
        allowances = compute_allowances_for_employee(conn, employee, base_hours)
        result.allowances = allowances
        result.base_pay = fixed_monthly_salary
        result.regular_hours = base_hours

        if employment_type == "insured":
            insurance_base = fixed_monthly_salary + sum(
                a.amount for a in allowances if not a.excluded_from_insurance_base
            )
            result.insurance_deduction = round(insurance_base * insurance_pct / 100)
        result.total_pay = (
            result.base_pay + result.allowances_total - result.insurance_deduction
        )
        return result

    # === Normal hour-based path ===
    allowances = compute_allowances_for_employee(conn, employee, worked_hours)
    result.allowances = allowances

    if employment_type == "insured":
        regular_hours = min(worked_hours, base_hours)
        overtime_hours = max(0.0, worked_hours - base_hours)
        result.regular_hours = regular_hours
        result.overtime_hours = overtime_hours

        base_pay = round(fixed_monthly_salary * (regular_hours / base_hours)) if base_hours else 0
        overtime_pay = round(overtime_hours * base_hourly_rate * (1 + overtime_premium_pct / 100))

        result.base_pay = base_pay
        result.overtime_pay = overtime_pay

        insurance_base = base_pay + sum(
            a.amount for a in allowances if not a.excluded_from_insurance_base
        )
        insurance_deduction = round(insurance_base * insurance_pct / 100)
        result.insurance_deduction = insurance_deduction

        result.total_pay = (
            base_pay + overtime_pay + result.allowances_total - insurance_deduction
        )

    else:  # non_insured
        regular_hours = max(0.0, worked_hours - holiday_hours)
        result.regular_hours = regular_hours
        result.overtime_hours = 0.0

        regular_pay = round(regular_hours * base_hourly_rate)
        holiday_pay = round(holiday_hours * base_hourly_rate * (1 + holiday_premium_pct / 100))

        result.base_pay = regular_pay
        result.holiday_pay = holiday_pay
        result.insurance_deduction = 0

        result.total_pay = (
            regular_pay + holiday_pay + result.allowances_total + fixed_monthly_salary
        )

    return result


def calculate_payroll_batch(
    conn: sqlite3.Connection,
    hours_by_employee_id: dict[int, tuple[float, float]],
) -> tuple[list[PayrollResult], list[int]]:
    """Returns (results, skipped_employee_ids)."""
    results = []
    skipped: list[int] = []
    for emp_id, (worked_hours, holiday_hours) in hours_by_employee_id.items():
        emp = conn.execute("SELECT * FROM employees WHERE id = ?", (emp_id,)).fetchone()
        if emp is None:
            continue
        res = calculate_payroll_for_employee(conn, emp, worked_hours, holiday_hours)
        if res is None:
            skipped.append(emp_id)
        else:
            results.append(res)
    return results, skipped