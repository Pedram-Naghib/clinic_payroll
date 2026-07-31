"""
Manual shift schedule (planned_shifts) + swap suggestions.

planned_shifts / shift_definitions / shift_swap_suggestions have existed in
the schema since Phase 0 as an unused stub -- see schema.sql's comment "no
importer reading this table". This module is the first thing that actually
reads/writes them, covering the roadmap's last open Phase 1 item: a manual
manager grid (who's on M/E/N/off each day) plus a swap-suggestion generator.

Swap suggestions are a heuristic, not ML (same "right size for a small
clinic" reasoning as app.core.insurance's reconciliation scorer): for every
planned M/E/N shift where the assigned employee has no 'ok' daily_attendance
row that day (they didn't show up), look for another active employee who DID
clock in that day, within that shift's time window, who wasn't themselves
scheduled for it -- that's the covering candidate.
"""
from __future__ import annotations
import sqlite3
from datetime import datetime

REAL_SHIFT_CODES = ("M", "E", "N")  # the only codes with a time window to match swaps against


def get_shift_definitions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM shift_definitions ORDER BY code").fetchall()


def update_shift_definition(
    conn: sqlite3.Connection, code: str, label: str, start_time: str, end_time: str, crosses_midnight: bool
) -> None:
    conn.execute(
        """UPDATE shift_definitions SET label = ?, start_time = ?, end_time = ?, crosses_midnight = ?
           WHERE code = ?""",
        (label, start_time, end_time, int(crosses_midnight), code),
    )
    conn.commit()


def get_schedule(conn: sqlite3.Connection, start_date: str, end_date: str) -> dict[int, dict[str, str]]:
    """{employee_id: {work_date: shift_code}} for planned_shifts in [start_date, end_date)."""
    rows = conn.execute(
        "SELECT employee_id, work_date, shift_code FROM planned_shifts WHERE work_date >= ? AND work_date < ?",
        (start_date, end_date),
    ).fetchall()
    schedule: dict[int, dict[str, str]] = {}
    for r in rows:
        schedule.setdefault(r["employee_id"], {})[r["work_date"]] = r["shift_code"] or ""
    return schedule


def save_month_schedule(
    conn: sqlite3.Connection, entries: list[tuple[int, str, str]], user_id: int
) -> None:
    """entries: (employee_id, work_date, shift_code) triples for one grid save.
    Blank shift_code deletes the cell. One commit for the whole grid."""
    for employee_id, work_date, shift_code in entries:
        shift_code = (shift_code or "").strip().upper()
        if not shift_code:
            conn.execute(
                "DELETE FROM planned_shifts WHERE employee_id = ? AND work_date = ?", (employee_id, work_date)
            )
        else:
            conn.execute(
                """INSERT INTO planned_shifts (employee_id, work_date, shift_code, created_by)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(employee_id, work_date) DO UPDATE SET
                       shift_code = excluded.shift_code,
                       created_by = excluded.created_by,
                       updated_at = CURRENT_TIMESTAMP""",
                (employee_id, work_date, shift_code, user_id),
            )
    conn.commit()


def _shift_windows(conn: sqlite3.Connection) -> dict[str, tuple[int, int, bool]]:
    return {
        r["code"]: (int(r["start_time"].split(":")[0]), int(r["end_time"].split(":")[0]), bool(r["crosses_midnight"]))
        for r in conn.execute("SELECT code, start_time, end_time, crosses_midnight FROM shift_definitions")
    }


def _hour_in_window(hour: int, window: tuple[int, int, bool]) -> bool:
    start_h, end_h, crosses = window
    return hour >= start_h or hour < end_h if crosses else start_h <= hour < end_h


def generate_swap_suggestions(conn: sqlite3.Connection, start_date: str, end_date: str) -> int:
    """Scans [start_date, end_date) for scheduled-but-absent employees and
    inserts a pending shift_swap_suggestions row per plausible covering
    match found. Returns how many new suggestions were created. Idempotent:
    skips a (work_date, absent_employee) pair that already has a pending
    suggestion."""
    windows = _shift_windows(conn)

    planned = conn.execute(
        """SELECT ps.employee_id, ps.work_date, ps.shift_code FROM planned_shifts ps
           JOIN employees e ON e.id = ps.employee_id
           WHERE ps.work_date >= ? AND ps.work_date < ? AND e.active = 1
             AND ps.shift_code IN ('M', 'E', 'N')""",
        (start_date, end_date),
    ).fetchall()

    created = 0
    for p in planned:
        window = windows.get(p["shift_code"])
        if window is None:
            continue

        showed_up = conn.execute(
            "SELECT id FROM daily_attendance WHERE employee_id = ? AND work_date = ? AND status = 'ok'",
            (p["employee_id"], p["work_date"]),
        ).fetchone()
        if showed_up is not None:
            continue

        already = conn.execute(
            """SELECT id FROM shift_swap_suggestions
               WHERE work_date = ? AND absent_employee_id = ? AND status = 'pending'""",
            (p["work_date"], p["employee_id"]),
        ).fetchone()
        if already is not None:
            continue

        candidates = conn.execute(
            """SELECT da.employee_id, da.first_in, da.last_out FROM daily_attendance da
               JOIN employees e ON e.id = da.employee_id
               LEFT JOIN planned_shifts ps2 ON ps2.employee_id = da.employee_id AND ps2.work_date = da.work_date
               WHERE da.work_date = ? AND da.status = 'ok' AND da.employee_id != ? AND e.active = 1
                 AND (ps2.shift_code IS NULL OR ps2.shift_code != ?)""",
            (p["work_date"], p["employee_id"], p["shift_code"]),
        ).fetchall()

        covering = next(
            (c for c in candidates if c["first_in"] and _hour_in_window(
                datetime.strptime(c["first_in"], "%Y-%m-%d %H:%M:%S").hour, window
            )),
            None,
        )
        if covering is None:
            continue

        conn.execute(
            """INSERT INTO shift_swap_suggestions
                   (work_date, absent_employee_id, covering_employee_id, planned_shift_code,
                    covering_punch_in, covering_punch_out)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (p["work_date"], p["employee_id"], covering["employee_id"], p["shift_code"],
             covering["first_in"], covering["last_out"]),
        )
        created += 1

    conn.commit()
    return created


def list_swap_suggestions(
    conn: sqlite3.Connection, start_date: str | None = None, end_date: str | None = None, status: str | None = None
) -> list[sqlite3.Row]:
    q = """SELECT s.*, ea.full_name AS absent_name, ec.full_name AS covering_name
           FROM shift_swap_suggestions s
           JOIN employees ea ON ea.id = s.absent_employee_id
           JOIN employees ec ON ec.id = s.covering_employee_id
           WHERE 1=1"""
    params: list = []
    if start_date is not None:
        q += " AND s.work_date >= ?"
        params.append(start_date)
    if end_date is not None:
        q += " AND s.work_date < ?"
        params.append(end_date)
    if status is not None:
        q += " AND s.status = ?"
        params.append(status)
    q += " ORDER BY s.work_date DESC, s.id DESC"
    return conn.execute(q, params).fetchall()


def decide_swap_suggestion(conn: sqlite3.Connection, suggestion_id: int, approve: bool, user_id: int) -> None:
    conn.execute(
        """UPDATE shift_swap_suggestions SET status = ?, decided_by = ?, decided_at = CURRENT_TIMESTAMP
           WHERE id = ? AND status = 'pending'""",
        ("approved" if approve else "rejected", user_id, suggestion_id),
    )
    conn.commit()
