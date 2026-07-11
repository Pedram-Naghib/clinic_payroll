"""
Attendance Engine.

Given the raw_punches table populated by punch_importer, group each employee's
punches into work sessions (IN/OUT pairs) and compute total worked hours within
a given period.

ALGORITHM:
- Per-employee, sort all punches chronologically (padding the window by ±12h to
  catch night shifts that cross the period boundary).
- Drop near-duplicate punches (same person scanning twice within
  DUPLICATE_PUNCH_WINDOW_MINUTES).
- Pair consecutively: 1st punch = IN, 2nd = OUT, 3rd = IN, 4th = OUT...
- Each (IN, OUT) pair is one work session. Hours attributed to the IN date.
  A session whose IN time falls within [period_start, period_end) counts;
  one whose IN is outside the period is ignored even if it overlaps in time.
- Sanity checks raise anomalies but don't break the loop:
    * Session > MAX_PLAUSIBLE_SESSION_HOURS: likely missed an OUT
    * Session < MIN_PLAUSIBLE_SESSION_MINUTES: likely accidental scan
    * Odd-numbered punches: orphan IN at end of period (no OUT punched)

FIXED-PAY EMPLOYEES (is_exempt_from_shifts=1, device_enroll_no='-1', NULL, or '0')
are skipped from the attendance pass — they don't clock in/out. Their attendance
record will show 0 sessions / 0 hours, with a status flag.
"""

from __future__ import annotations
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta


DUPLICATE_PUNCH_WINDOW_MINUTES = 3
MAX_PLAUSIBLE_SESSION_HOURS = 18  # EN (Evening+Night) double-shift = 14:00->08:00 next day = 18h exactly
MIN_PLAUSIBLE_SESSION_MINUTES = 5


@dataclass
class WorkSession:
    employee_id: int
    in_time: datetime
    out_time: datetime | None
    hours: float
    note: str = "ok"  # 'ok' | 'too_long' | 'too_short' | 'missing_punch'


@dataclass
class EmployeeAttendance:
    employee_id: int
    full_name: str
    employment_type: str
    is_fixed_pay: bool = False            # True for exempt / -1 / 0 / NULL device id
    sessions: list[WorkSession] = field(default_factory=list)
    total_hours: float = 0.0
    days_worked: int = 0
    anomalies: list[str] = field(default_factory=list)


def _is_fixed_pay(emp: sqlite3.Row) -> bool:
    if emp["is_exempt_from_shifts"]:
        return True
    dev = str(emp["device_enroll_no"] or "").strip()
    return dev in ("-1", "0", "")


def compute_attendance(
    conn: sqlite3.Connection,
    period_start: datetime,
    period_end: datetime,
) -> list[EmployeeAttendance]:
    """Pair punches and compute hours for every active employee in the window
    [period_start, period_end). The end is exclusive (use first of next month).
    """
    pad_start = (period_start - timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")
    pad_end = (period_end + timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")

    employees = conn.execute(
        """SELECT id, full_name, employment_type, device_enroll_no, is_exempt_from_shifts
           FROM employees
           WHERE active = 1
           ORDER BY id"""
    ).fetchall()

    results: list[EmployeeAttendance] = []
    for emp in employees:
        att = EmployeeAttendance(
            employee_id=emp["id"],
            full_name=emp["full_name"],
            employment_type=emp["employment_type"],
            is_fixed_pay=_is_fixed_pay(emp),
        )

        if att.is_fixed_pay:
            results.append(att)
            continue

        punches = conn.execute(
            """SELECT punch_datetime FROM raw_punches
               WHERE employee_id = ? AND punch_datetime BETWEEN ? AND ?
               ORDER BY punch_datetime""",
            (emp["id"], pad_start, pad_end),
        ).fetchall()

        if not punches:
            results.append(att)
            continue

        # Parse + dedupe near-duplicates
        times: list[datetime] = []
        for p in punches:
            t = datetime.strptime(p["punch_datetime"], "%Y-%m-%d %H:%M:%S")
            if times and (t - times[-1]).total_seconds() < DUPLICATE_PUNCH_WINDOW_MINUTES * 60:
                continue
            times.append(t)

        # Pair: alternate IN/OUT
        days_with_session: set = set()
        i = 0
        while i + 1 < len(times):
            in_t = times[i]
            out_t = times[i + 1]

            if period_start <= in_t < period_end:
                hours = (out_t - in_t).total_seconds() / 3600
                note = "ok"
                if hours > MAX_PLAUSIBLE_SESSION_HOURS:
                    note = "too_long"
                    att.anomalies.append(
                        f"جلسه > {MAX_PLAUSIBLE_SESSION_HOURS} ساعت در {in_t.date()}: "
                        f"{hours:.1f} ساعت — احتمالاً خروج ثبت نشده"
                    )
                elif hours * 60 < MIN_PLAUSIBLE_SESSION_MINUTES:
                    note = "too_short"

                # Only count sessions flagged 'ok' toward total_hours.
                # too_long/too_short sessions are recorded for audit but excluded
                # from the working-hours total — the user must resolve them
                # (typically by adding the missing punch) and recompute.
                if note == "ok":
                    att.total_hours += hours
                    days_with_session.add(in_t.date())

                att.sessions.append(WorkSession(emp["id"], in_t, out_t, round(hours, 2), note))
            i += 2

        # Orphan trailing IN inside the period -- Zero-Tolerance Policy:
        # recorded as a real zero-hour session (not just a text anomaly) so
        # it persists into daily_attendance as status='missing_punch' and
        # the manager sees it per-day, not just in a tooltip.
        if len(times) % 2 == 1:
            orphan = times[-1]
            if period_start <= orphan < period_end:
                att.anomalies.append(f"ورود بدون خروج در {orphan} — خروج ثبت نشده")
                att.sessions.append(
                    WorkSession(emp["id"], orphan, None, 0.0, "missing_punch")
                )

        att.total_hours = round(att.total_hours, 2)
        att.days_worked = len(days_with_session)
        results.append(att)

    return results


# =============================================================================
# SEGMENT-ZERO PERSISTENCE  (added 2026-06-30)
# =============================================================================
#
# compute_attendance() above already EXCLUDES too_long/too_short sessions and
# trailing unmatched IN punches from total_hours -- so an employee who
# forgets to punch out already nets zero pay for that segment, mechanically.
# What was missing: (1) writing that result into daily_attendance per
# work_date so other modules (holiday join, payroll batch) can read it
# without recomputing, and (2) a clear status label per the zero-tolerance
# policy ("Missing Exit" / status='missing_punch') instead of only a
# free-text anomaly string.
#
# Nothing above this line was changed. attendance_tab.py's existing call to
# compute_attendance(self.conn, period_start, period_end) keeps working
# exactly as before. The one-line change needed there is to additionally
# call persist_daily_attendance() right after, so the "Compute Hours" button
# also fact-checks-and-saves instead of only fact-checking.

def persist_daily_attendance(
    conn: sqlite3.Connection,
    results: list[EmployeeAttendance],
) -> None:
    """Writes one daily_attendance row per (employee, work_date) found in
    `results`. Hours are attributed to the calendar date of the session's
    IN punch (handles night shifts crossing midnight). Segment-Zero: a
    session note != 'ok' (too_long/too_short, i.e. a missing or implausible
    punch) contributes 0 hours to that day's worked_hours, and the day's
    status is set to 'missing_punch' so the manager sees it -- no further
    action required from them; the employee loses that segment's pay."""
    for att in results:
        if att.is_fixed_pay:
            continue  # fixed-pay staff don't clock in; nothing to persist

        by_day: dict[str, list[WorkSession]] = {}
        for sess in att.sessions:
            day_key = sess.in_time.date().isoformat()
            by_day.setdefault(day_key, []).append(sess)

        for work_date, day_sessions in by_day.items():
            worked_hours = sum(s.hours for s in day_sessions if s.note == "ok")
            any_problem = any(s.note != "ok" for s in day_sessions)
            first_in = min(s.in_time for s in day_sessions)
            ok_outs = [s.out_time for s in day_sessions if s.note == "ok" and s.out_time]
            last_out = max(ok_outs) if ok_outs else None
            status = "missing_punch" if any_problem else "ok"

            conn.execute(
                """
                INSERT INTO daily_attendance
                    (employee_id, work_date, first_in, last_out, worked_hours, status)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(employee_id, work_date) DO UPDATE SET
                    first_in = excluded.first_in,
                    last_out = excluded.last_out,
                    worked_hours = excluded.worked_hours,
                    status = excluded.status
                """,
                (
                    att.employee_id,
                    work_date,
                    first_in.strftime("%Y-%m-%d %H:%M:%S"),
                    last_out.strftime("%Y-%m-%d %H:%M:%S") if last_out else None,
                    round(worked_hours, 2),
                    status,
                ),
            )
    conn.commit()


def compute_and_persist_attendance(
    conn: sqlite3.Connection,
    period_start: datetime,
    period_end: datetime,
) -> list[EmployeeAttendance]:
    """Convenience wrapper: compute_attendance() + persist_daily_attendance()
    in one call. Use this from the UI instead of calling compute_attendance()
    directly, so daily_attendance stays in sync with what's shown on screen."""
    results = compute_attendance(conn, period_start, period_end)
    persist_daily_attendance(conn, results)
    return results


def _load_shift_windows(conn: sqlite3.Connection) -> dict[str, tuple[int, int, bool]]:
    """Returns {code: (start_hour, end_hour, crosses_midnight)} read from the
    (Owner-editable) shift_definitions table."""
    windows: dict[str, tuple[int, int, bool]] = {}
    for row in conn.execute("SELECT code, start_time, end_time, crosses_midnight FROM shift_definitions"):
        start_h = int(str(row["start_time"]).split(":")[0])
        end_h = int(str(row["end_time"]).split(":")[0])
        windows[row["code"]] = (start_h, end_h, bool(row["crosses_midnight"]))
    return windows


def _is_night_shift(in_hour: int, windows: dict[str, tuple[int, int, bool]]) -> bool:
    """True if a session clocking in at `in_hour` (0-23) falls inside the
    'N' (night) shift window. Night shifts are never eligible for holiday
    premium (clinic policy), regardless of what calendar date they land on.
    Falls back to the clinic's default 20:00->08:00 window if shift_definitions
    is somehow missing the 'N' row (it's seeded by database.py)."""
    start_h, end_h, crosses = windows.get("N", (20, 8, True))
    if crosses:
        return in_hour >= start_h or in_hour < end_h
    return start_h <= in_hour < end_h


def build_payroll_inputs(
    conn: sqlite3.Connection,
    period_start: datetime,
    period_end: datetime,
) -> dict[int, tuple[float, float]]:
    """Returns { employee_id: (worked_hours, holiday_hours) } for every
    active employee in the period -- the exact shape
    payroll_engine.calculate_payroll_batch() expects.

    Call compute_and_persist_attendance() for this period FIRST so
    daily_attendance is up to date, then call this.

    holiday_hours is a SUBSET of worked_hours, not additional, matching how
    payroll_engine.py expects holiday_hours to be passed. A day only counts
    toward holiday_hours if (a) its work_date is in iranian_holidays AND
    (b) the day's first punch-in does NOT fall in the night-shift ('N')
    window -- night shifts never earn holiday premium, for either
    employment type, per clinic policy. This is computed in Python (not a
    SQL join) because the night-shift classification needs shift_definitions'
    hour ranges, not just a date match."""
    start_date = period_start.date().isoformat()
    end_date = (period_end.date()).isoformat()  # period_end is exclusive upstream

    holiday_dates = {
        row[0] for row in conn.execute(
            "SELECT work_date FROM iranian_holidays WHERE work_date >= ? AND work_date < ?",
            (start_date, end_date),
        )
    }
    windows = _load_shift_windows(conn)

    totals: dict[int, float] = {}
    holiday_totals: dict[int, float] = {}
    for row in conn.execute(
        """SELECT employee_id, work_date, worked_hours, first_in
           FROM daily_attendance
           WHERE work_date >= ? AND work_date < ?""",
        (start_date, end_date),
    ):
        emp_id = row["employee_id"]
        hours = row["worked_hours"] or 0.0
        totals[emp_id] = totals.get(emp_id, 0.0) + hours

        if hours > 0 and row["first_in"] and row["work_date"] in holiday_dates:
            in_hour = datetime.strptime(row["first_in"], "%Y-%m-%d %H:%M:%S").hour
            if not _is_night_shift(in_hour, windows):
                holiday_totals[emp_id] = holiday_totals.get(emp_id, 0.0) + hours

    inputs: dict[int, tuple[float, float]] = {
        emp_id: (round(total, 2), round(holiday_totals.get(emp_id, 0.0), 2))
        for emp_id, total in totals.items()
    }

    # Active employees with no daily_attendance rows this period (fixed-pay
    # staff, or genuinely zero punches) still get an entry so
    # calculate_payroll_batch sees them; fixed_no_clocking employees ignore
    # worked_hours entirely inside payroll_engine anyway.
    for (emp_id,) in conn.execute("SELECT id FROM employees WHERE active = 1"):
        inputs.setdefault(emp_id, (0.0, 0.0))

    return inputs