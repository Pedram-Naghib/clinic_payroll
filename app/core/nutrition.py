"""Nutrition department module: doctor/contract, revenue, expense, and
monthly settlement. Web-only (like app.core.insurance) -- raw SQL via a
connection object, dataclass inputs, plain functions, same shape as the
rest of app/core.

Business model: exactly one nutrition doctor is "active" at a time (the one
currently under contract). Activating a doctor auto-deactivates the others
-- enforced here, not just in the UI, so the settlement calculation always
has a single unambiguous doctor to attribute a month's numbers to. Each
doctor has exactly one contract row (percentages), edited in place rather
than versioned -- past settlements already snapshot their own numbers
(gross_revenue, shares, ...) so editing today's percentages never rewrites
history.

Settlement formula (contract math, see the clinic's actual paper contracts):
  doctor_share = gross_revenue - consumable_expenses * doctor_pct
  remaining    = doctor_share - consumable_expenses * (1 - doctor_pct) - non_consumable_expenses
  clinic_share  = remaining * clinic_pct
  partner_share = remaining * partner_pct
doctor_pct/clinic_pct/partner_pct default to 50/50/50, which reduces this
exactly to the fixed halves/50-50 split described in the contracts;
clinic_pct + partner_pct must sum to 100 (validated on save).
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class DoctorInput:
    full_name: str
    phone: str | None = None
    contract_start: str | None = None
    contract_end: str | None = None
    notes: str | None = None


@dataclass
class ContractInput:
    doctor_percentage: int = 50
    clinic_percentage: int = 50
    partner_percentage: int = 50
    notes: str | None = None


@dataclass
class RevenueInput:
    date: str
    amount: int
    doctor_id: int
    patient_name: str | None = None
    service_type: str | None = None


EXPENSE_TYPES = {"consumable": "مصرفی", "non_consumable": "غیرمصرفی"}


@dataclass
class ExpenseInput:
    date: str
    title: str
    amount: int
    expense_type: str


# ============================================================
# Doctors + contracts
# ============================================================

def list_doctors(conn):
    return conn.execute(
        """SELECT d.*, c.id AS contract_id, c.doctor_percentage, c.clinic_percentage,
                  c.partner_percentage, c.notes AS contract_notes
           FROM nutrition_doctors d
           LEFT JOIN nutrition_contracts c ON c.doctor_id = d.id
           ORDER BY d.active DESC, d.full_name"""
    ).fetchall()


def get_doctor(conn, doctor_id: int):
    return conn.execute("SELECT * FROM nutrition_doctors WHERE id = ?", (doctor_id,)).fetchone()


def get_contract_for_doctor(conn, doctor_id: int):
    return conn.execute(
        "SELECT * FROM nutrition_contracts WHERE doctor_id = ?", (doctor_id,)
    ).fetchone()


def get_active_doctor(conn):
    """The single doctor currently under contract, with their percentages.
    None if no doctor has been activated yet."""
    return conn.execute(
        """SELECT d.*, c.doctor_percentage, c.clinic_percentage, c.partner_percentage
           FROM nutrition_doctors d
           JOIN nutrition_contracts c ON c.doctor_id = d.id
           WHERE d.active = 1 LIMIT 1"""
    ).fetchone()


def add_doctor(conn, d: DoctorInput, contract: ContractInput) -> int:
    cur = conn.execute(
        """INSERT INTO nutrition_doctors (full_name, phone, contract_start, contract_end, notes, active)
           VALUES (?, ?, ?, ?, ?, 0)""",
        (d.full_name, d.phone, d.contract_start, d.contract_end, d.notes),
    )
    doctor_id = cur.lastrowid
    conn.execute(
        """INSERT INTO nutrition_contracts (doctor_id, doctor_percentage, clinic_percentage, partner_percentage, notes)
           VALUES (?, ?, ?, ?, ?)""",
        (doctor_id, contract.doctor_percentage, contract.clinic_percentage, contract.partner_percentage, contract.notes),
    )
    conn.commit()
    return doctor_id


def update_doctor(conn, doctor_id: int, d: DoctorInput) -> None:
    conn.execute(
        """UPDATE nutrition_doctors SET full_name = ?, phone = ?, contract_start = ?,
               contract_end = ?, notes = ? WHERE id = ?""",
        (d.full_name, d.phone, d.contract_start, d.contract_end, d.notes, doctor_id),
    )
    conn.commit()


def update_contract(conn, doctor_id: int, contract: ContractInput) -> None:
    conn.execute(
        """UPDATE nutrition_contracts SET doctor_percentage = ?, clinic_percentage = ?,
               partner_percentage = ?, notes = ? WHERE doctor_id = ?""",
        (contract.doctor_percentage, contract.clinic_percentage, contract.partner_percentage, contract.notes, doctor_id),
    )
    conn.commit()


def set_doctor_active(conn, doctor_id: int, active: bool) -> None:
    """Activating a doctor deactivates every other doctor first, so at most
    one is ever active -- settlement calculation relies on this invariant."""
    if active:
        conn.execute("UPDATE nutrition_doctors SET active = 0 WHERE id != ?", (doctor_id,))
    conn.execute("UPDATE nutrition_doctors SET active = ? WHERE id = ?", (1 if active else 0, doctor_id))
    conn.commit()


# ============================================================
# Revenues
# ============================================================

def list_revenues(conn, period_start: str | None = None, period_end: str | None = None):
    q = """SELECT r.*, d.full_name AS doctor_name FROM nutrition_revenues r
           JOIN nutrition_doctors d ON d.id = r.doctor_id"""
    params: list = []
    if period_start and period_end:
        q += " WHERE r.date >= ? AND r.date < ?"
        params += [period_start, period_end]
    q += " ORDER BY r.date DESC, r.id DESC"
    return conn.execute(q, params).fetchall()


def get_revenue(conn, revenue_id: int):
    return conn.execute("SELECT * FROM nutrition_revenues WHERE id = ?", (revenue_id,)).fetchone()


def add_revenue(conn, r: RevenueInput, created_by: int | None) -> int:
    cur = conn.execute(
        """INSERT INTO nutrition_revenues (date, patient_name, service_type, amount, doctor_id, created_by)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (r.date, r.patient_name, r.service_type, r.amount, r.doctor_id, created_by),
    )
    conn.commit()
    return cur.lastrowid


def update_revenue(conn, revenue_id: int, r: RevenueInput) -> None:
    conn.execute(
        """UPDATE nutrition_revenues SET date = ?, patient_name = ?, service_type = ?,
               amount = ?, doctor_id = ? WHERE id = ?""",
        (r.date, r.patient_name, r.service_type, r.amount, r.doctor_id, revenue_id),
    )
    conn.commit()


def delete_revenue(conn, revenue_id: int) -> None:
    conn.execute("DELETE FROM nutrition_revenues WHERE id = ?", (revenue_id,))
    conn.commit()


# ============================================================
# Expenses
# ============================================================

def list_expenses(conn, period_start: str | None = None, period_end: str | None = None, expense_type: str | None = None):
    q = "SELECT * FROM nutrition_expenses WHERE 1=1"
    params: list = []
    if period_start and period_end:
        q += " AND date >= ? AND date < ?"
        params += [period_start, period_end]
    if expense_type:
        q += " AND expense_type = ?"
        params.append(expense_type)
    q += " ORDER BY date DESC, id DESC"
    return conn.execute(q, params).fetchall()


def get_expense(conn, expense_id: int):
    return conn.execute("SELECT * FROM nutrition_expenses WHERE id = ?", (expense_id,)).fetchone()


def add_expense(conn, e: ExpenseInput, created_by: int | None) -> int:
    cur = conn.execute(
        """INSERT INTO nutrition_expenses (date, title, amount, expense_type, created_by)
           VALUES (?, ?, ?, ?, ?)""",
        (e.date, e.title, e.amount, e.expense_type, created_by),
    )
    conn.commit()
    return cur.lastrowid


def update_expense(conn, expense_id: int, e: ExpenseInput) -> None:
    conn.execute(
        "UPDATE nutrition_expenses SET date = ?, title = ?, amount = ?, expense_type = ? WHERE id = ?",
        (e.date, e.title, e.amount, e.expense_type, expense_id),
    )
    conn.commit()


def delete_expense(conn, expense_id: int) -> None:
    conn.execute("DELETE FROM nutrition_expenses WHERE id = ?", (expense_id,))
    conn.commit()


# ============================================================
# Settlement
# ============================================================

def compute_shares(
    gross_revenue: int, consumable_expenses: int, non_consumable_expenses: int,
    doctor_pct: int = 50, clinic_pct: int = 50, partner_pct: int = 50,
) -> dict:
    """Full breakdown, every intermediate number included -- the settlement
    page shows this whole dict, not just the three final shares."""
    doctor_frac = doctor_pct / 100
    doctor_consumable_cut = consumable_expenses * doctor_frac
    other_consumable_cut = consumable_expenses - doctor_consumable_cut
    doctor_share = gross_revenue - doctor_consumable_cut
    remaining = doctor_share - other_consumable_cut - non_consumable_expenses
    clinic_share = remaining * (clinic_pct / 100)
    partner_share = remaining * (partner_pct / 100)
    return {
        "gross_revenue": gross_revenue,
        "consumable_expenses": consumable_expenses,
        "non_consumable_expenses": non_consumable_expenses,
        "doctor_consumable_cut": round(doctor_consumable_cut),
        "other_consumable_cut": round(other_consumable_cut),
        "doctor_share": round(doctor_share),
        "remaining": round(remaining),
        "clinic_share": round(clinic_share),
        "partner_share": round(partner_share),
    }


def compute_settlement_for_period(conn, period_start: str, period_end: str, doctor_id: int) -> dict:
    doctor = get_doctor(conn, doctor_id)
    contract = get_contract_for_doctor(conn, doctor_id)
    gross_revenue = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS s FROM nutrition_revenues WHERE doctor_id = ? AND date >= ? AND date < ?",
        (doctor_id, period_start, period_end),
    ).fetchone()["s"]
    consumable = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS s FROM nutrition_expenses WHERE expense_type = 'consumable' AND date >= ? AND date < ?",
        (period_start, period_end),
    ).fetchone()["s"]
    non_consumable = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS s FROM nutrition_expenses WHERE expense_type = 'non_consumable' AND date >= ? AND date < ?",
        (period_start, period_end),
    ).fetchone()["s"]
    breakdown = compute_shares(
        gross_revenue, consumable, non_consumable,
        contract["doctor_percentage"], contract["clinic_percentage"], contract["partner_percentage"],
    )
    breakdown["doctor_id"] = doctor_id
    breakdown["doctor_name"] = doctor["full_name"]
    breakdown["doctor_pct"] = contract["doctor_percentage"]
    breakdown["clinic_pct"] = contract["clinic_percentage"]
    breakdown["partner_pct"] = contract["partner_percentage"]
    return breakdown


def find_existing_settlement(conn, period_start: str, period_end: str):
    return conn.execute(
        "SELECT * FROM nutrition_settlements WHERE period_start = ? AND period_end = ?",
        (period_start, period_end),
    ).fetchone()


def save_settlement(conn, period_start: str, period_end: str, breakdown: dict, generated_by: int | None) -> int:
    existing = find_existing_settlement(conn, period_start, period_end)
    if existing is not None:
        conn.execute(
            """UPDATE nutrition_settlements SET doctor_id = ?, gross_revenue = ?, consumable_expenses = ?,
                   non_consumable_expenses = ?, doctor_share = ?, clinic_share = ?, partner_share = ?,
                   generated_by = ?, generated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (
                breakdown["doctor_id"], breakdown["gross_revenue"], breakdown["consumable_expenses"],
                breakdown["non_consumable_expenses"], breakdown["doctor_share"], breakdown["clinic_share"],
                breakdown["partner_share"], generated_by, existing["id"],
            ),
        )
        conn.commit()
        return existing["id"]
    cur = conn.execute(
        """INSERT INTO nutrition_settlements (period_start, period_end, doctor_id, gross_revenue,
               consumable_expenses, non_consumable_expenses, doctor_share, clinic_share, partner_share, generated_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            period_start, period_end, breakdown["doctor_id"], breakdown["gross_revenue"],
            breakdown["consumable_expenses"], breakdown["non_consumable_expenses"],
            breakdown["doctor_share"], breakdown["clinic_share"], breakdown["partner_share"], generated_by,
        ),
    )
    conn.commit()
    return cur.lastrowid


def list_settlements(conn):
    return conn.execute(
        """SELECT s.*, d.full_name AS doctor_name FROM nutrition_settlements s
           JOIN nutrition_doctors d ON d.id = s.doctor_id
           ORDER BY s.period_start DESC"""
    ).fetchall()
