"""
Direct commissions (Rule 8 of project_instructions / Section 4 of handover).

These are paid out directly from patient fees and are tracked entirely
separate from the monthly payroll run -- never merged into payroll_line_items.

Commission rates (piercing_commission_pct, fast_blood_test_commission_pct)
live in system_config so the owner can adjust them without a code change.

service_date is stored as ISO Gregorian text, consistent with every other
date column in the schema (raw_punches.punch_datetime, iranian_holidays.work_date,
daily_attendance.work_date) -- the UI is responsible for Jalali<->Gregorian
conversion at the edges.
"""

from __future__ import annotations
import sqlite3
from dataclasses import dataclass

from app.core.config import get_config

SERVICE_TYPES = ("piercing", "fast_blood_test")

_RATE_CONFIG_KEY = {
    "piercing": "piercing_commission_pct",
    "fast_blood_test": "fast_blood_test_commission_pct",
}


@dataclass
class CommissionInput:
    employee_id: int
    service_type: str          # 'piercing' | 'fast_blood_test'
    fee_received: int          # Rial, already converted from Toman by the UI
    service_date: str          # ISO Gregorian 'YYYY-MM-DD'
    notes: str | None = None


def get_commission_rate(conn: sqlite3.Connection, service_type: str) -> float:
    """Current rate (%) for a service type, read live from system_config."""
    key = _RATE_CONFIG_KEY.get(service_type)
    if key is None:
        raise ValueError(f"Unknown service_type: {service_type}")
    rate = get_config(conn, key)
    if rate is None:
        raise ValueError(f"Missing system_config entry: {key}")
    return float(rate)


def compute_commission_amount(fee_received: int, commission_rate: float) -> int:
    """Rial amount owed to the staff member. Rounded to the nearest Rial."""
    return round(fee_received * commission_rate / 100)


def add_commission(conn: sqlite3.Connection, entry: CommissionInput) -> int:
    """Looks up the current rate, computes the amount, and persists the row.
    The rate actually used is stored on the row itself (commission_rate) so
    later rate changes in system_config never retroactively alter history."""
    rate = get_commission_rate(conn, entry.service_type)
    amount = compute_commission_amount(entry.fee_received, rate)
    cur = conn.execute(
        """
        INSERT INTO direct_commissions (
            employee_id, service_type, fee_received,
            commission_rate, commission_amount, service_date, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry.employee_id, entry.service_type, entry.fee_received,
            rate, amount, entry.service_date, entry.notes,
        ),
    )
    conn.commit()
    return cur.lastrowid


def delete_commission(conn: sqlite3.Connection, commission_id: int) -> None:
    conn.execute("DELETE FROM direct_commissions WHERE id = ?", (commission_id,))
    conn.commit()


def list_commissions(
    conn: sqlite3.Connection,
    employee_id: int | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
) -> list[sqlite3.Row]:
    """period_start/period_end are inclusive ISO Gregorian date strings."""
    q = (
        "SELECT dc.*, e.full_name AS employee_name "
        "FROM direct_commissions dc "
        "JOIN employees e ON e.id = dc.employee_id "
        "WHERE 1=1"
    )
    params: list = []
    if employee_id is not None:
        q += " AND dc.employee_id = ?"
        params.append(employee_id)
    if period_start is not None:
        q += " AND dc.service_date >= ?"
        params.append(period_start)
    if period_end is not None:
        q += " AND dc.service_date <= ?"
        params.append(period_end)
    q += " ORDER BY dc.service_date DESC, dc.id DESC"
    return conn.execute(q, params).fetchall()