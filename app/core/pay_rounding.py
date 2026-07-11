"""
Rounds each employee's final net pay (PayrollResult.total_pay) UP to the
nearest 1,000 Rial -- e.g. 303,864,822 -> 303,865,000 -- so cash amounts are
clean.

Deliberately kept as a thin layer ABOVE payroll_engine.py rather than a
change inside it: payroll_engine.py is finalized/off-limits (see handover),
so this module wraps its two public entry points, applies the rounding to
total_pay only (every other figure -- base_pay, overtime_pay, insurance
deduction, allowances, etc. -- is left exactly as the engine computed it),
and is what callers should import instead of the raw engine functions.

Both call sites that ultimately display/save total_pay -- the Payroll Run
tab (calculate_payroll_batch) and the payslip dialog (build_payslip ->
calculate_payroll_for_employee) -- go through here, so the payroll table,
the saved payroll_runs/payroll_line_items rows, and the printed payslip all
agree on the same rounded net pay.
"""

from __future__ import annotations
import math
import sqlite3

from app.core.payroll_engine import (
    calculate_payroll_for_employee as _calculate_payroll_for_employee,
    calculate_payroll_batch as _calculate_payroll_batch,
    PayrollResult,
)

ROUND_TO_RIALS = 1000000


def round_up_to_thousand(amount: int | float) -> int:
    return int(math.ceil(amount / ROUND_TO_RIALS) * ROUND_TO_RIALS)


def _apply(result: PayrollResult | None) -> PayrollResult | None:
    if result is not None:
        result.total_pay = round_up_to_thousand(result.total_pay)
    return result


def calculate_payroll_for_employee(
    conn: sqlite3.Connection,
    employee: sqlite3.Row,
    worked_hours: float,
    holiday_hours: float = 0.0,
) -> PayrollResult | None:
    return _apply(
        _calculate_payroll_for_employee(conn, employee, worked_hours, holiday_hours)
    )


def calculate_payroll_batch(
    conn: sqlite3.Connection,
    hours_by_employee_id: dict[int, tuple[float, float]],
) -> tuple[list[PayrollResult], list[int]]:
    results, skipped = _calculate_payroll_batch(conn, hours_by_employee_id)
    for r in results:
        _apply(r)
    return results, skipped