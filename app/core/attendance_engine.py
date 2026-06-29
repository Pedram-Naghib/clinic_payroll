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
MAX_PLAUSIBLE_SESSION_HOURS = 16
MIN_PLAUSIBLE_SESSION_MINUTES = 5


@dataclass
class WorkSession:
    employee_id: int
    in_time: datetime
    out_time: datetime
    hours: float
    note: str = "ok"  # 'ok' | 'too_long' | 'too_short'


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

        # Orphan trailing IN inside the period
        if len(times) % 2 == 1:
            orphan = times[-1]
            if period_start <= orphan < period_end:
                att.anomalies.append(f"ورود بدون خروج در {orphan} — خروج ثبت نشده")

        att.total_hours = round(att.total_hours, 2)
        att.days_worked = len(days_with_session)
        results.append(att)

    return results