"""
Payslip (فیش حقوقی) data assembly for individual employees.

Deliberately does NOT recompute payroll independently -- it calls the same
attendance_engine.build_payroll_inputs() + payroll_engine.calculate_payroll_
for_employee() used by the Payroll tab / saved payroll runs, and only
re-labels/re-groups the resulting PayrollResult into the sections a payslip
needs (Earnings / Allowances / Deductions / Leave tracking). This keeps the
payslip and the payroll table as a single source of truth -- there is no
second place net pay could drift out of sync.
"""

from __future__ import annotations
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from app.core.payroll_engine import PayrollResult
from app.core.pay_rounding import calculate_payroll_for_employee  # rounds total_pay up to 1,000 Rial
from app.core.attendance_engine import build_payroll_inputs
from app.core.jalali import gregorian_to_jalali

# Allowance codes that belong in the "Earnings" section of a payslip (bonuses
# tied to service/seniority) rather than "Allowances" (family/cost-of-living
# support) -- everything else in PayrollResult.allowances falls into Allowances.
_EARNINGS_ALLOWANCE_CODES = {"seniority_fixed"}

# Allowance codes grouped by type -- housing ("حق مسکن") and food/meal
# ("حق بن (خوراک)") used to be merged into a single "بن و مسکن" line; kept
# as separate lines now per request, so each is individually visible.
_HOUSING_CODES = {"housing_fixed", "housing_hourly"}
_FOOD_CODES = {"food_fixed", "food_hourly"}

_ALLOWANCE_DISPLAY_LABELS = {
    "marriage": "حق تاهل",
    "child": "حق اولاد",
    "seniority_fixed": "سنوات",
}


@dataclass
class PayslipLine:
    label: str
    amount: int


@dataclass
class AttendanceDetailLine:
    """One daily_attendance row, re-labeled for the payslip's attached
    day-by-day detail sheet -- lets a manager check exactly which date/times
    a disputed month's hours came from, without opening the Attendance tab."""
    jalali_date: str
    first_in: str   # "HH:MM" or "—"
    last_out: str   # "HH:MM" or "—"
    worked_hours: float
    status: str


@dataclass
class Payslip:
    employee_id: int
    full_name: str
    employment_type: str
    period_label: str
    period_start: str  # ISO Gregorian, inclusive
    period_end: str     # ISO Gregorian, exclusive

    regular_hours: float
    overtime_hours: float
    holiday_hours: float

    personnel_code: str = ""

    earnings: list[PayslipLine] = field(default_factory=list)
    allowances: list[PayslipLine] = field(default_factory=list)
    deductions: list[PayslipLine] = field(default_factory=list)

    # Leave/absence tracking -- shown separately, per spec, distinguishing
    # "covered by leave balance" (no pay impact) from "explicit leave taken"
    # and from "کمبود کارکرد" (the uncovered shortfall, already folded into
    # `deductions` above as its own line).
    leave_days_covered: float = 0.0
    uncovered_shortfall_hours: float = 0.0
    explicit_leave_days_taken: float = 0.0

    # Day-by-day punch detail for this period (date + shift start/end +
    # hours), so a disputed month can be checked at a glance -- see
    # _daily_attendance_detail(). Empty for fixed-no-clocking staff.
    daily_attendance: list[AttendanceDetailLine] = field(default_factory=list)

    gross_pay: int = 0
    total_deductions: int = 0
    net_pay: int = 0

    @property
    def earnings_total(self) -> int:
        return sum(l.amount for l in self.earnings)

    @property
    def allowances_total(self) -> int:
        return sum(l.amount for l in self.allowances)

    @property
    def deductions_total(self) -> int:
        return sum(l.amount for l in self.deductions)


def _group_allowances(result: PayrollResult) -> tuple[list[PayslipLine], list[PayslipLine]]:
    """Splits PayrollResult.allowances into (earnings_extra, allowances) --
    housing ('حق مسکن') and food/meal ('حق بن (خوراک)') are kept as separate
    lines. Any allowance code not explicitly mapped keeps its own
    DB-configured label, so a future Owner-added allowance never silently
    disappears from the payslip."""
    earnings_extra: list[PayslipLine] = []
    allowances: list[PayslipLine] = []
    housing_total = 0
    food_total = 0
    seen_other: dict[str, int] = {}

    for a in result.allowances:
        if a.code in _EARNINGS_ALLOWANCE_CODES:
            earnings_extra.append(PayslipLine(_ALLOWANCE_DISPLAY_LABELS.get(a.code, a.label), a.amount))
        elif a.code in _HOUSING_CODES:
            housing_total += a.amount
        elif a.code in _FOOD_CODES:
            food_total += a.amount
        else:
            label = _ALLOWANCE_DISPLAY_LABELS.get(a.code, a.label)
            seen_other[label] = seen_other.get(label, 0) + a.amount

    if housing_total:
        allowances.append(PayslipLine("حق مسکن", housing_total))
    if food_total:
        allowances.append(PayslipLine("حق بن (خوراک)", food_total))
    for label, amount in seen_other.items():
        allowances.append(PayslipLine(label, amount))

    return earnings_extra, allowances


_STATUS_DISPLAY = {"ok": "عادی", "missing_punch": "ثبت ناقص (کسری ضربه)"}


def _fmt_clock(dt_str: str | None) -> str:
    if not dt_str:
        return "—"
    try:
        return datetime.fromisoformat(dt_str).strftime("%H:%M")
    except ValueError:
        # tolerate 'YYYY-MM-DD HH:MM:SS' (sqlite default) as well
        return dt_str[11:16] if len(dt_str) >= 16 else dt_str


def _daily_attendance_detail(
    conn: sqlite3.Connection, employee_id: int, period_start: str, period_end: str
) -> list[AttendanceDetailLine]:
    """Pulls this employee's daily_attendance rows for the period, for the
    payslip's attached day-by-day detail sheet (date + shift start/end +
    hours) -- e.g. so a disputed month can be checked at a glance instead of
    re-opening the Attendance tab. Empty for fixed-no-clocking staff, who
    never get daily_attendance rows in the first place."""
    rows = conn.execute(
        """SELECT work_date, first_in, last_out, worked_hours, status
           FROM daily_attendance
           WHERE employee_id = ? AND work_date >= ? AND work_date < ?
           ORDER BY work_date""",
        (employee_id, period_start, period_end),
    ).fetchall()

    detail = []
    for r in rows:
        gy, gm, gd = (int(x) for x in r["work_date"].split("-"))
        jy, jm, jd = gregorian_to_jalali(gy, gm, gd)
        detail.append(
            AttendanceDetailLine(
                jalali_date=f"{jy:04d}/{jm:02d}/{jd:02d}",
                first_in=_fmt_clock(r["first_in"]),
                last_out=_fmt_clock(r["last_out"]),
                worked_hours=r["worked_hours"] or 0.0,
                status=_STATUS_DISPLAY.get(r["status"], r["status"] or ""),
            )
        )
    return detail


def _explicit_leave_days_taken(
    conn: sqlite3.Connection, employee_id: int, period_start: str, period_end: str
) -> float:
    """Days of manually-requested leave (vacation or medical) whose start
    date falls in this payroll period -- i.e. leave the employee explicitly
    took, as opposed to the automatic shortfall-coverage mechanism."""
    row = conn.execute(
        """SELECT COALESCE(SUM(days_count), 0) AS n FROM leave_requests
           WHERE employee_id = ? AND source = 'manual' AND status = 'approved'
             AND start_date >= ? AND start_date < ?""",
        (employee_id, period_start, period_end),
    ).fetchone()
    return float(row["n"] or 0)


def build_payslip(
    conn: sqlite3.Connection,
    employee_id: int,
    period_start: datetime,
    period_end: datetime,
    period_label: str | None = None,
) -> Payslip | None:
    """Builds a full Payslip for one employee for one Jalali-month period
    (period_end exclusive, matching attendance_engine's convention).
    Returns None if the employee has no payroll result for this period
    (device_enroll_no='0', i.e. calculate_payroll_for_employee's skip case).
    """
    employee = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if employee is None:
        return None

    inputs = build_payroll_inputs(conn, period_start, period_end)
    worked_hours, holiday_hours = inputs.get(employee_id, (0.0, 0.0))
    result = calculate_payroll_for_employee(conn, employee, worked_hours, holiday_hours)
    if result is None:
        return None

    period_start_iso = period_start.date().isoformat()
    period_end_iso = period_end.date().isoformat()
    label = period_label or f"{period_start_iso} → {period_end_iso}"

    earnings_extra, allowances = _group_allowances(result)

    # اضافه‌کاری / تعطیلات are always shown, even at 0 -- previously they were
    # hidden entirely when zero, which made payslips structurally
    # inconsistent from one employee/month to the next (a manager comparing
    # several payslips side by side shouldn't have rows appearing/
    # disappearing based on amount).
    earnings = [
        PayslipLine("پایه حقوق", result.base_pay),
        PayslipLine("اضافه‌کاری", result.overtime_pay),
        PayslipLine("تعطیلات", result.holiday_pay),
    ]
    earnings.extend(earnings_extra)

    deductions: list[PayslipLine] = []
    if result.insurance_deduction:
        deductions.append(PayslipLine("۷٪ حق بیمه سهم کارگر", result.insurance_deduction))
    if result.under_hours_deduction:
        deductions.append(PayslipLine("کمبود کارکرد", result.under_hours_deduction))

    payslip = Payslip(
        employee_id=employee_id,
        full_name=result.full_name,
        employment_type=result.employment_type,
        period_label=label,
        period_start=period_start_iso,
        period_end=period_end_iso,
        regular_hours=result.regular_hours,
        overtime_hours=result.overtime_hours,
        holiday_hours=result.holiday_hours,
        personnel_code=str(employee["device_enroll_no"] or ""),
        earnings=earnings,
        allowances=allowances,
        deductions=deductions,
        leave_days_covered=result.leave_days_covered,
        uncovered_shortfall_hours=result.uncovered_shortfall_hours,
        explicit_leave_days_taken=_explicit_leave_days_taken(
            conn, employee_id, period_start_iso, period_end_iso
        ),
        daily_attendance=_daily_attendance_detail(
            conn, employee_id, period_start_iso, period_end_iso
        ),
    )
    payslip.gross_pay = payslip.earnings_total + payslip.allowances_total
    payslip.total_deductions = payslip.deductions_total
    payslip.net_pay = result.total_pay
    return payslip