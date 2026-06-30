"""
Iranian public holiday detection.

NEW FILE -- does not modify any existing module.

Two tiers, per Pedram's 2026-06-30 directive ("Smart Jalali Holidays, no
manual grid"):

  1. FIXED-DATE holidays (Nowruz, 22 Bahman, etc.) -- these are deterministic
     from the Jalali calendar alone. Computed using the project's existing
     app.core.jalali.jalali_to_gregorian(), NOT a new dependency -- keeps
     faith with jalali.py's "no external dependencies" principle.

  2. LUNAR (Hijri) holidays (Eid-e Fetr, Ashura, etc.) -- these move year to
     year on the Islamic lunar calendar and are ultimately confirmed by an
     official moon-sighting announcement, so no calculation -- this one
     included -- can guarantee the exact date. We compute a best-effort
     estimate and mark it confirmed=0 so the manager can glance at a short
     list (~8-11 rows/year) once a year and nudge any date by a day if the
     official calendar differs. This is the one deliberate exception to
     "no external dependencies": Hijri<->Gregorian conversion is genuinely
     complex (not a one-screen algorithm like Jalali), so we lean on the
     hijri-converter package (pure Python, fully offline, no network calls
     at runtime -- consistent with the project's 100% local execution rule,
     just not with jalali.py's specific "hand-rolled" approach).

     pip install hijri-converter
"""

from __future__ import annotations

import sqlite3
from datetime import date

from app.core.jalali import jalali_to_gregorian

try:
    from hijridate import Hijri
    _HIJRI_AVAILABLE = True
except ImportError:
    _HIJRI_AVAILABLE = False


# ---------------------------------------------------------------------------
# Schema -- one new table, nothing else touched
# ---------------------------------------------------------------------------

def ensure_holiday_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS iranian_holidays (
            work_date TEXT PRIMARY KEY,         -- ISO Gregorian date
            label     TEXT NOT NULL,
            source    TEXT NOT NULL CHECK (source IN
                       ('computed_fixed', 'computed_lunar_estimate', 'manual')),
            confirmed INTEGER NOT NULL DEFAULT 1   -- lunar estimates start at 0
        )
        """
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Fixed-date Jalali holidays -- fully deterministic
# ---------------------------------------------------------------------------

# (jalali_month, jalali_day, label) -- solar-fixed, never move year to year
FIXED_JALALI_HOLIDAYS = [
    (1, 1, "نوروز"),
    (1, 2, "نوروز"),
    (1, 3, "نوروز"),
    (1, 4, "نوروز"),
    (1, 12, "روز جمهوری اسلامی"),
    (1, 13, "سیزده بدر"),
    (3, 14, "رحلت امام خمینی"),
    (3, 15, "قیام ۱۵ خرداد"),
    (11, 22, "پیروزی انقلاب اسلامی"),
    (12, 29, "ملی شدن صنعت نفت"),
]


def seed_fixed_jalali_holidays(conn: sqlite3.Connection, jalali_year: int) -> None:
    """Idempotent -- safe to call every app startup."""
    for jm, jd, label in FIXED_JALALI_HOLIDAYS:
        g_date: date = jalali_to_gregorian(jalali_year, jm, jd)
        conn.execute(
            """
            INSERT OR IGNORE INTO iranian_holidays (work_date, label, source, confirmed)
            VALUES (?, ?, 'computed_fixed', 1)
            """,
            (g_date.isoformat(), label),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Lunar holiday ESTIMATE -- flagged unconfirmed until the manager reviews
# ---------------------------------------------------------------------------

# (hijri_month, hijri_day, label) -- the moving religious holidays
LUNAR_HIJRI_HOLIDAYS = [
    (1, 9, "تاسوعای حسینی"),
    (1, 10, "عاشورای حسینی"),
    (2, 20, "اربعین حسینی"),
    (3, 8, "رحلت پیامبر / شهادت امام حسن"),
    (3, 17, "میلاد پیامبر و امام جعفر صادق"),
    (6, 3, "شهادت حضرت فاطمه"),
    (9, 21, "شهادت امام علی"),
    (10, 1, "عید فطر"),
    (10, 2, "عید فطر"),
    (12, 10, "عید قربان"),
    (12, 18, "عید غدیر"),
]


def seed_lunar_holidays_estimate(conn: sqlite3.Connection, jalali_year: int) -> None:
    """Best-effort estimate only -- see module docstring. Rows go in with
    confirmed=0; surface them via get_unconfirmed_holidays() once a year."""
    if not _HIJRI_AVAILABLE:
        raise RuntimeError(
            "hijri-converter not installed -- run: pip install hijri-converter"
        )

    g_start = jalali_to_gregorian(jalali_year, 1, 1)
    g_end = jalali_to_gregorian(jalali_year, 12, 29)

    for hijri_year in range(1440, 1460):  # wide net, filtered by date range below
        for hm, hd, label in LUNAR_HIJRI_HOLIDAYS:
            try:
                g = Hijri(hijri_year, hm, hd).to_gregorian()
            except ValueError:
                continue
            g_date = date(g.year, g.month, g.day)
            if g_start <= g_date <= g_end:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO iranian_holidays
                        (work_date, label, source, confirmed)
                    VALUES (?, ?, 'computed_lunar_estimate', 0)
                    """,
                    (g_date.isoformat(), label),
                )
    conn.commit()


def get_unconfirmed_holidays(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Feed into a short once-a-year confirmation list -- not a grid, just
    'does this look right? [confirm] [adjust by 1 day]' per row."""
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "SELECT * FROM iranian_holidays WHERE confirmed = 0 ORDER BY work_date"
    ).fetchall()


def confirm_holiday(conn: sqlite3.Connection, work_date: str) -> None:
    conn.execute(
        "UPDATE iranian_holidays SET confirmed = 1 WHERE work_date = ?", (work_date,)
    )
    conn.commit()


def adjust_holiday_date(conn: sqlite3.Connection, old_date: str, new_date: str) -> None:
    """Manager nudges an estimated lunar date by a day to match the official
    announcement."""
    row = conn.execute(
        "SELECT label, source FROM iranian_holidays WHERE work_date = ?", (old_date,)
    ).fetchone()
    if row is None:
        raise ValueError(f"No holiday row for {old_date}")
    conn.execute("DELETE FROM iranian_holidays WHERE work_date = ?", (old_date,))
    conn.execute(
        """
        INSERT OR REPLACE INTO iranian_holidays (work_date, label, source, confirmed)
        VALUES (?, ?, ?, 1)
        """,
        (new_date, row["label"], row["source"]),
    )
    conn.commit()


def is_holiday(conn: sqlite3.Connection, work_date: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM iranian_holidays WHERE work_date = ?", (work_date,)
    ).fetchone()
    return row is not None


def run_startup_holiday_seed(conn: sqlite3.Connection, current_jalali_year: int) -> None:
    """Call once at app launch (e.g. top of app/ui/main_window.py, before the
    window shows). Seeds this year and next year's fixed holidays, plus
    lunar estimates if hijri-converter is installed. Idempotent."""
    ensure_holiday_table(conn)
    for year in (current_jalali_year, current_jalali_year + 1):
        seed_fixed_jalali_holidays(conn, year)
        if _HIJRI_AVAILABLE:
            seed_lunar_holidays_estimate(conn, year)