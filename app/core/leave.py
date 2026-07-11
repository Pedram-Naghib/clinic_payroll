"""
Paid leave (مرخصی) tracking.

Single-balance model: employees.vacation_balance_days is the one source of
truth for how many paid leave days an employee currently has banked. Two
things draw down that balance:

  1. Manual leave requests entered on the Leave tab
     (leave_type='vacation', source='manual').
  2. Automatic shortfall coverage: when an insured employee's monthly
     clocked hours fall short of base_monthly_hours, payroll_engine calls
     preview_shortfall_coverage() (read-only -- preview runs never mutate
     anything). payroll_runs.save_payroll_run() then calls
     apply_shortfall_coverage() to actually deduct it once the run is
     SAVED, leaving an audit leave_requests row (source='auto_shortfall')
     tied to that payroll_run_id so it can be cleanly reversed if the run
     is overwritten (see reverse_auto_shortfall_coverage()).

The annual cap (system_config['annual_paid_leave_days_cap'], default 30)
gates *manual* leave requests -- how many new vacation days can be granted
in a Jalali year. It is not a second parallel balance.
"""

from __future__ import annotations
import sqlite3
from dataclasses import dataclass

from app.core.config import get_config
from app.core.jalali import gregorian_to_jalali, jalali_to_gregorian

HOURS_PER_DAY = 8


@dataclass
class ShortfallCoverage:
    shortfall_hours: float
    covered_hours: float
    covered_days: float
    uncovered_hours: float


def get_leave_balance(conn: sqlite3.Connection, employee_id: int) -> float:
    row = conn.execute(
        "SELECT vacation_balance_days FROM employees WHERE id = ?", (employee_id,)
    ).fetchone()
    return float(row["vacation_balance_days"] or 0) if row else 0.0


def preview_shortfall_coverage(
    employee: sqlite3.Row, shortfall_hours: float
) -> ShortfallCoverage:
    """Read-only: how much of `shortfall_hours` the employee's CURRENT
    vacation_balance_days (already present on the `employee` row) could
    cover, without touching the database. Used by payroll_engine during
    calculation/preview -- the balance is only actually spent once the run
    is saved (see apply_shortfall_coverage)."""
    if shortfall_hours <= 0:
        return ShortfallCoverage(0.0, 0.0, 0.0, 0.0)

    balance_days = float(employee["vacation_balance_days"] or 0)
    balance_hours = max(0.0, balance_days * HOURS_PER_DAY)

    covered_hours = round(min(shortfall_hours, balance_hours), 4)
    covered_days = round(covered_hours / HOURS_PER_DAY, 4)
    uncovered_hours = round(shortfall_hours - covered_hours, 4)
    return ShortfallCoverage(
        shortfall_hours=shortfall_hours,
        covered_hours=covered_hours,
        covered_days=covered_days,
        uncovered_hours=uncovered_hours,
    )


def apply_shortfall_coverage(
    conn: sqlite3.Connection,
    employee_id: int,
    covered_days: float,
    payroll_run_id: int,
    period_label: str,
    period_start: str,
    period_end: str,
) -> None:
    """Actually spends `covered_days` from the employee's balance and leaves
    an audit trail row. Call only when a payroll run is being SAVED, never
    during a preview computation. Does not commit -- caller controls the
    transaction (payroll_runs.save_payroll_run)."""
    if covered_days <= 0:
        return
    conn.execute(
        "UPDATE employees SET vacation_balance_days = vacation_balance_days - ? WHERE id = ?",
        (covered_days, employee_id),
    )
    conn.execute(
        """INSERT INTO leave_requests
           (employee_id, leave_type, start_date, end_date, days_count, status,
            paid_by_clinic_days, unpaid_days, source, payroll_run_id, notes)
           VALUES (?, 'vacation', ?, ?, ?, 'approved', ?, 0, 'auto_shortfall', ?, ?)""",
        (
            employee_id, period_start, period_end, covered_days, covered_days,
            payroll_run_id, f"پوشش خودکار کسری ساعت کاری -- {period_label}",
        ),
    )


def reverse_auto_shortfall_coverage(conn: sqlite3.Connection, payroll_run_id: int) -> None:
    """Undo every auto_shortfall leave_requests row tied to `payroll_run_id`
    (restores the balance). Call before re-applying on a run overwrite, so
    re-saving the same period never double-deducts. Does not commit."""
    rows = conn.execute(
        """SELECT id, employee_id, days_count FROM leave_requests
           WHERE payroll_run_id = ? AND source = 'auto_shortfall'""",
        (payroll_run_id,),
    ).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE employees SET vacation_balance_days = vacation_balance_days + ? WHERE id = ?",
            (row["days_count"], row["employee_id"]),
        )
    conn.execute(
        "DELETE FROM leave_requests WHERE payroll_run_id = ? AND source = 'auto_shortfall'",
        (payroll_run_id,),
    )


# ============================================================
# Manual leave requests (Leave tab)
# ============================================================

@dataclass
class LeaveRequestInput:
    employee_id: int
    leave_type: str          # 'vacation' | 'medical'
    start_date: str          # ISO Gregorian
    end_date: str             # ISO Gregorian
    days_count: float
    notes: str | None = None


def _jalali_year_bounds(jalali_year: int) -> tuple[str, str]:
    start = jalali_to_gregorian(jalali_year, 1, 1)
    end = jalali_to_gregorian(jalali_year + 1, 1, 1)
    return start.isoformat(), end.isoformat()


def days_used_this_jalali_year(
    conn: sqlite3.Connection, employee_id: int, jalali_year: int, leave_type: str = "vacation"
) -> float:
    start, end = _jalali_year_bounds(jalali_year)
    row = conn.execute(
        """SELECT COALESCE(SUM(days_count), 0) AS n FROM leave_requests
           WHERE employee_id = ? AND leave_type = ? AND status = 'approved'
             AND start_date >= ? AND start_date < ?""",
        (employee_id, leave_type, start, end),
    ).fetchone()
    return float(row["n"] or 0)


def create_leave_request(conn: sqlite3.Connection, entry: LeaveRequestInput) -> int:
    """Creates a manual, immediately-approved leave request. For
    leave_type='vacation' this deducts from vacation_balance_days and
    enforces both the current balance and the annual cap
    (system_config['annual_paid_leave_days_cap']). Raises ValueError if
    either would be exceeded -- callers (the Leave tab) should show that
    message to the owner rather than silently failing."""
    if entry.leave_type == "vacation":
        balance = get_leave_balance(conn, entry.employee_id)
        if entry.days_count > balance:
            raise ValueError(
                f"موجودی مرخصی کافی نیست (موجودی: {balance:g} روز، درخواست: {entry.days_count:g} روز)"
            )
        gy, gm, gd = (int(x) for x in entry.start_date.split("-"))
        jy, _, _ = gregorian_to_jalali(gy, gm, gd)
        cap = get_config(conn, "annual_paid_leave_days_cap", default=30)
        used = days_used_this_jalali_year(conn, entry.employee_id, jy)
        if used + entry.days_count > cap:
            raise ValueError(
                f"سقف سالانه مرخصی ({cap:g} روز) رد می‌شود "
                f"(استفاده‌شده: {used:g}، درخواست: {entry.days_count:g})"
            )

    cur = conn.execute(
        """INSERT INTO leave_requests
           (employee_id, leave_type, start_date, end_date, days_count, status,
            paid_by_clinic_days, unpaid_days, source, notes)
           VALUES (?, ?, ?, ?, ?, 'approved', ?, 0, 'manual', ?)""",
        (
            entry.employee_id, entry.leave_type, entry.start_date, entry.end_date,
            entry.days_count, entry.days_count if entry.leave_type == "vacation" else 0,
            entry.notes,
        ),
    )
    if entry.leave_type == "vacation":
        conn.execute(
            "UPDATE employees SET vacation_balance_days = vacation_balance_days - ? WHERE id = ?",
            (entry.days_count, entry.employee_id),
        )
    conn.commit()
    return cur.lastrowid


def cancel_leave_request(conn: sqlite3.Connection, request_id: int) -> None:
    """Deletes a manual leave request and restores its balance impact.
    Refuses to touch auto_shortfall rows -- those are tied to a specific
    payroll run and are only reversed via reverse_auto_shortfall_coverage()
    when that run is deleted/overwritten."""
    row = conn.execute(
        "SELECT * FROM leave_requests WHERE id = ?", (request_id,)
    ).fetchone()
    if row is None:
        return
    if row["source"] == "auto_shortfall":
        raise ValueError(
            "این مرخصی به‌صورت خودکار از یک اجرای حقوق ایجاد شده و باید از طریق حذف یا "
            "بازمحاسبهٔ همان اجرای حقوق اصلاح شود، نه به‌صورت مستقیم."
        )
    if row["leave_type"] == "vacation" and row["status"] == "approved":
        conn.execute(
            "UPDATE employees SET vacation_balance_days = vacation_balance_days + ? WHERE id = ?",
            (row["days_count"], row["employee_id"]),
        )
    conn.execute("DELETE FROM leave_requests WHERE id = ?", (request_id,))
    conn.commit()


def list_leave_requests(
    conn: sqlite3.Connection, employee_id: int | None = None
) -> list[sqlite3.Row]:
    q = (
        "SELECT lr.*, e.full_name AS employee_name FROM leave_requests lr "
        "JOIN employees e ON e.id = lr.employee_id WHERE 1=1"
    )
    params: list = []
    if employee_id is not None:
        q += " AND lr.employee_id = ?"
        params.append(employee_id)
    q += " ORDER BY lr.start_date DESC, lr.id DESC"
    return conn.execute(q, params).fetchall()


# ============================================================
# Year-end payout (بازخرید مرخصی) -- explicit, owner-triggered only.
# Never runs automatically: disbursing money without the owner reviewing
# it first is too risky for a payroll tool.
# ============================================================

def compute_year_end_payout(conn: sqlite3.Connection, employee_id: int) -> int:
    """Rial value of the employee's current unused vacation_balance_days,
    priced at fixed_monthly_salary / 30 per day. Read-only. Returns 0 if
    there's no positive balance or no salary on file to price it against."""
    emp = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if emp is None or not emp["fixed_monthly_salary"]:
        return 0
    balance = float(emp["vacation_balance_days"] or 0)
    if balance <= 0:
        return 0
    daily_rate = emp["fixed_monthly_salary"] / 30
    return round(balance * daily_rate)


def settle_year_end_payout(conn: sqlite3.Connection, employee_id: int) -> int:
    """Owner-triggered only: pays out the current balance (the caller is
    responsible for actually disbursing/recording the payment -- this app
    has no accounting ledger) and resets vacation_balance_days to 0 for the
    new year. Returns the Rial amount that was paid out."""
    amount = compute_year_end_payout(conn, employee_id)
    if amount > 0:
        conn.execute(
            "UPDATE employees SET vacation_balance_days = 0 WHERE id = ?", (employee_id,)
        )
        conn.commit()
    return amount
