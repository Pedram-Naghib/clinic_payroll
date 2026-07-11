"""
Persistence for payroll runs.

Deliberately kept separate from payroll_engine.py (finalized, not to be
touched -- see handover Section 5). This module's only job is mapping a
list[PayrollResult] (already-computed, in-memory) onto the
payroll_runs / payroll_line_items tables.

Column-mapping notes (the schema has more granular allowance columns than
PayrollResult.allowances exposes as a flat list, so this is where the
mapping decision lives):
  - allowance code 'marriage'                  -> family_allowance
  - allowance code 'child'                      -> child_allowance
  - allowance codes 'housing_fixed'/'housing_hourly' -> housing_allowance (summed)
  - allowance codes 'food_fixed'/'food_hourly'       -> food_allowance (summed)
  - allowance code 'seniority_fixed'             -> seniority_allowance
  - any other/future allowance code              -> folded into family_allowance
    as a catch-all so nothing silently disappears from total_pay; the full
    detail is never lost regardless, since breakdown_json stores the
    complete PayrollResult.to_dict() for every line item.
  - under_hours_deduction: populated from PayrollResult.under_hours_deduction
    (the portion of an insured employee's hours shortfall NOT covered by
    their paid-leave balance -- see app.core.leave). leave_days_covered
    (the portion that WAS covered) is stored alongside it so the payslip can
    show both halves of the shortfall story.
  - unpaid_medical_leave_deduction: medical leave is out of scope per the
    handover; always stored as 0 -- flagged here rather than guessed.
"""

from __future__ import annotations
import json
import sqlite3

from app.core.payroll_engine import PayrollResult
from app.core.leave import apply_shortfall_coverage, reverse_auto_shortfall_coverage

_ALLOWANCE_COLUMN_MAP = {
    "marriage": "family_allowance",
    "child": "child_allowance",
    "housing_fixed": "housing_allowance",
    "housing_hourly": "housing_allowance",
    "food_fixed": "food_allowance",
    "food_hourly": "food_allowance",
    "seniority_fixed": "seniority_allowance",
}
_DEFAULT_ALLOWANCE_COLUMN = "family_allowance"  # catch-all for unmapped/future codes


def find_existing_run(
    conn: sqlite3.Connection, period_start: str, period_end: str
) -> sqlite3.Row | None:
    """period_start/period_end are ISO Gregorian date strings (period_end exclusive,
    matching attendance_engine's convention). Returns the most recent run for
    that exact period, if any."""
    return conn.execute(
        """
        SELECT * FROM payroll_runs
        WHERE period_start = ? AND period_end = ?
        ORDER BY generated_at DESC LIMIT 1
        """,
        (period_start, period_end),
    ).fetchone()


def _line_item_columns(result: PayrollResult) -> dict:
    cols = {
        "total_hours": result.regular_hours + result.overtime_hours + result.holiday_hours,
        "overtime_hours": result.overtime_hours,
        "holiday_hours": result.holiday_hours,
        "base_pay": result.base_pay,
        "overtime_pay": result.overtime_pay,
        "holiday_premium_pay": result.holiday_pay,
        "housing_allowance": 0,
        "food_allowance": 0,
        "child_allowance": 0,
        "seniority_allowance": 0,
        "family_allowance": 0,
        "under_hours_deduction": result.under_hours_deduction,
        "leave_days_covered": result.leave_days_covered,
        "insurance_deduction": result.insurance_deduction,
        "unpaid_medical_leave_deduction": 0,
        "total_pay": result.total_pay,
        "breakdown_json": json.dumps(result.to_dict(), ensure_ascii=False),
    }
    for a in result.allowances:
        col = _ALLOWANCE_COLUMN_MAP.get(a.code, _DEFAULT_ALLOWANCE_COLUMN)
        cols[col] += a.amount
    return cols


def save_payroll_run(
    conn: sqlite3.Connection,
    period_start: str,
    period_end: str,
    results: list[PayrollResult],
    overwrite_run_id: int | None = None,
    notes: str | None = None,
) -> int:
    """Persists a computed payroll batch. If overwrite_run_id is given, the
    existing run row is reused (generated_at refreshed) and its old line
    items are replaced; otherwise a new payroll_runs row is created."""
    if overwrite_run_id is not None:
        # Undo this run's own auto-shortfall leave deductions BEFORE deleting
        # its line items, so re-saving the same period never double-spends
        # (or double-restores) an employee's vacation_balance_days.
        reverse_auto_shortfall_coverage(conn, overwrite_run_id)
        conn.execute(
            "DELETE FROM payroll_line_items WHERE payroll_run_id = ?",
            (overwrite_run_id,),
        )
        conn.execute(
            """UPDATE payroll_runs
               SET generated_at = datetime('now'), notes = ?
               WHERE id = ?""",
            (notes, overwrite_run_id),
        )
        run_id = overwrite_run_id
    else:
        cur = conn.execute(
            """INSERT INTO payroll_runs (period_start, period_end, notes)
               VALUES (?, ?, ?)""",
            (period_start, period_end, notes),
        )
        run_id = cur.lastrowid

    period_label = f"{period_start} → {period_end}"
    for result in results:
        cols = _line_item_columns(result)
        conn.execute(
            """
            INSERT INTO payroll_line_items (
                payroll_run_id, employee_id, total_hours, overtime_hours, holiday_hours,
                base_pay, overtime_pay, holiday_premium_pay,
                housing_allowance, food_allowance, child_allowance, seniority_allowance,
                family_allowance, under_hours_deduction, insurance_deduction,
                unpaid_medical_leave_deduction, total_pay, breakdown_json, leave_days_covered
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, result.employee_id, cols["total_hours"], cols["overtime_hours"],
                cols["holiday_hours"], cols["base_pay"], cols["overtime_pay"],
                cols["holiday_premium_pay"], cols["housing_allowance"], cols["food_allowance"],
                cols["child_allowance"], cols["seniority_allowance"], cols["family_allowance"],
                cols["under_hours_deduction"], cols["insurance_deduction"],
                cols["unpaid_medical_leave_deduction"], cols["total_pay"], cols["breakdown_json"],
                cols["leave_days_covered"],
            ),
        )
        # Actually spend the leave balance now that the run is truly being
        # saved (calculate_payroll_for_employee/preview never mutate it).
        apply_shortfall_coverage(
            conn, result.employee_id, result.leave_days_covered, run_id,
            period_label, period_start, period_end,
        )
    conn.commit()
    return run_id


def list_payroll_runs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM payroll_runs ORDER BY period_start DESC, generated_at DESC"
    ).fetchall()


def get_payroll_run_line_items(conn: sqlite3.Connection, run_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT pli.*, e.full_name AS employee_name
        FROM payroll_line_items pli
        JOIN employees e ON e.id = pli.employee_id
        WHERE pli.payroll_run_id = ?
        ORDER BY e.full_name
        """,
        (run_id,),
    ).fetchall()