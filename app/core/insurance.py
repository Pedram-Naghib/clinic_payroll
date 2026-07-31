"""
Insurance module: companies, invoices, payments, and payment<->invoice
reconciliation. New for the web app -- no desktop-app precedent -- but
follows the same shape as the rest of app/core: raw SQL via a connection
object (sqlite3.Connection or app.db.pg_compat.Connection, interchangeable),
dataclass inputs, plain functions. Kept consistent with the payroll engine's
conventions rather than introducing a second data-access style (ORM) for
just this one module.

Reconciliation is a heuristic, not ML: score = weighted(amount closeness,
date proximity) against every outstanding invoice for the same company.
Simple and explainable -- exactly the "start heuristic, not ML" approach
that's the right size for a 4-5 person clinic's payment volume. Revisit
only if it demonstrably fails on real data.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date


@dataclass
class CompanyInput:
    name: str
    contact_person: str | None = None
    phone: str | None = None
    contract_start_date: str | None = None
    notes: str | None = None


DEPARTMENTS = {"clinic": "درمانگاه", "physio": "فیزیوتراپی", "lab": "آزمایشگاه"}


@dataclass
class InvoiceInput:
    company_id: int
    period_start: str
    period_end: str
    amount: int
    department: str = "clinic"
    invoice_number: str | None = None
    issued_date: str | None = None
    notes: str | None = None
    created_by: int | None = None


@dataclass
class PaymentInput:
    company_id: int
    amount: int
    received_date: str
    reference_no: str | None = None
    notes: str | None = None
    created_by: int | None = None


# ============================================================
# Companies
# ============================================================

def list_companies(conn, active_only: bool = False):
    q = "SELECT * FROM insurance_companies"
    if active_only:
        q += " WHERE active = 1"
    q += " ORDER BY name"
    return conn.execute(q).fetchall()


def add_company(conn, c: CompanyInput) -> int:
    cur = conn.execute(
        """INSERT INTO insurance_companies (name, contact_person, phone, contract_start_date, notes)
           VALUES (?, ?, ?, ?, ?)""",
        (c.name, c.contact_person, c.phone, c.contract_start_date, c.notes),
    )
    conn.commit()
    return cur.lastrowid


def get_company(conn, company_id: int):
    return conn.execute("SELECT * FROM insurance_companies WHERE id = ?", (company_id,)).fetchone()


def update_company(conn, company_id: int, c: CompanyInput) -> None:
    conn.execute(
        """UPDATE insurance_companies SET name = ?, contact_person = ?, phone = ?,
               contract_start_date = ?, notes = ? WHERE id = ?""",
        (c.name, c.contact_person, c.phone, c.contract_start_date, c.notes, company_id),
    )
    conn.commit()


def set_company_active(conn, company_id: int, active: bool) -> None:
    conn.execute("UPDATE insurance_companies SET active = ? WHERE id = ?", (int(active), company_id))
    conn.commit()


def company_open_invoice_count(conn, company_id: int) -> int:
    row = conn.execute(
        """SELECT COUNT(*) AS n FROM insurance_invoices i
           WHERE i.company_id = ? AND (
             i.amount - i.insurer_deduction
             - COALESCE((SELECT SUM(m.allocated_amount) FROM invoice_payment_matches m
                         WHERE m.invoice_id = i.id AND m.status = 'confirmed'), 0)
           ) > 0""",
        (company_id,),
    ).fetchone()
    return row["n"]


# ============================================================
# Invoices
# ============================================================

def list_invoices(conn, company_id: int | None = None):
    q = """SELECT i.*, c.name AS company_name FROM insurance_invoices i
           JOIN insurance_companies c ON c.id = i.company_id"""
    params: list = []
    if company_id is not None:
        q += " WHERE i.company_id = ?"
        params.append(company_id)
    q += " ORDER BY i.period_start DESC, i.id DESC"
    return conn.execute(q, params).fetchall()


def get_invoice(conn, invoice_id: int):
    return conn.execute(
        """SELECT i.*, c.name AS company_name FROM insurance_invoices i
           JOIN insurance_companies c ON c.id = i.company_id WHERE i.id = ?""",
        (invoice_id,),
    ).fetchone()


def add_invoice(conn, inv: InvoiceInput) -> int:
    cur = conn.execute(
        """INSERT INTO insurance_invoices
               (company_id, invoice_number, period_start, period_end, amount, department, issued_date, notes, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (inv.company_id, inv.invoice_number, inv.period_start, inv.period_end,
         inv.amount, inv.department, inv.issued_date, inv.notes, inv.created_by),
    )
    conn.commit()
    return cur.lastrowid


def delete_invoice(conn, invoice_id: int) -> None:
    """Deletes the invoice and its payment matches. The matched payments
    themselves are untouched -- they just go back to the unmatched pool,
    ready to be re-matched against a different invoice."""
    conn.execute("DELETE FROM invoice_payment_matches WHERE invoice_id = ?", (invoice_id,))
    conn.execute("DELETE FROM insurance_invoices WHERE id = ?", (invoice_id,))
    conn.commit()


def invoice_paid_amount(conn, invoice_id: int) -> int:
    row = conn.execute(
        """SELECT COALESCE(SUM(allocated_amount), 0) AS n FROM invoice_payment_matches
           WHERE invoice_id = ? AND status = 'confirmed'""",
        (invoice_id,),
    ).fetchone()
    return row["n"]


def invoice_matches(conn, invoice_id: int):
    return conn.execute(
        """SELECT m.*, p.received_date, p.reference_no, p.amount AS payment_amount
           FROM invoice_payment_matches m JOIN insurance_payments p ON p.id = m.payment_id
           WHERE m.invoice_id = ? AND m.status = 'confirmed'
           ORDER BY p.received_date""",
        (invoice_id,),
    ).fetchall()


def set_invoice_insurer_deduction(conn, invoice_id: int, amount: int) -> None:
    """Records the amount the insurance company itself decided to disallow
    from this invoice (they think the clinic over-billed) -- a write-off,
    not an unpaid balance. Distinct from `paid`: this money will never
    arrive, whereas an unpaid balance still might."""
    conn.execute(
        "UPDATE insurance_invoices SET insurer_deduction = ? WHERE id = ?",
        (amount, invoice_id),
    )
    conn.commit()


def invoices_with_status(conn, company_id: int | None = None):
    """Each invoice row plus paid amount, the insurer's own write-off
    (insurer_deduction), remaining outstanding balance, and a status label --
    computed here (not stored) so it's never out of sync with the matches.

    کسورات (insurer_deduction) is NOT "money not yet paid" -- it's the
    portion the insurance company formally decided to disallow (their
    judgment that the clinic over-billed) and will never pay. `outstanding`
    is what's actually still expected: amount - paid - insurer_deduction."""
    rows = list_invoices(conn, company_id)
    result = []
    for r in rows:
        paid = invoice_paid_amount(conn, r["id"])
        insurer_deduction = r["insurer_deduction"] or 0
        outstanding = max(0, r["amount"] - paid - insurer_deduction)
        if outstanding == 0:
            status, status_class = "تسویه شده", "ok"
        elif paid == 0 and insurer_deduction == 0:
            status, status_class = "در انتظار پرداخت", "warn"
        else:
            status, status_class = "مغایرت", "danger"
        result.append({
            "id": r["id"], "company_name": r["company_name"], "period_start": r["period_start"],
            "period_end": r["period_end"], "invoice_number": r["invoice_number"] or "",
            "department": r["department"], "department_label": DEPARTMENTS.get(r["department"], r["department"]),
            "amount": r["amount"], "paid": paid, "insurer_deduction": insurer_deduction,
            "outstanding": outstanding, "status": status, "status_class": status_class,
        })
    return result


# ============================================================
# Payments
# ============================================================

def list_payments(conn, company_id: int | None = None, unmatched_only: bool = False):
    q = """SELECT p.*, c.name AS company_name,
                  COALESCE((SELECT SUM(m.allocated_amount) FROM invoice_payment_matches m
                            WHERE m.payment_id = p.id AND m.status = 'confirmed'), 0) AS matched_amount
           FROM insurance_payments p JOIN insurance_companies c ON c.id = p.company_id"""
    clauses = []
    params: list = []
    if company_id is not None:
        clauses.append("p.company_id = ?")
        params.append(company_id)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY p.received_date DESC, p.id DESC"
    rows = conn.execute(q, params).fetchall()
    if unmatched_only:
        rows = [r for r in rows if r["matched_amount"] < r["amount"]]
    return rows


def get_payment(conn, payment_id: int):
    return conn.execute(
        """SELECT p.*, c.name AS company_name FROM insurance_payments p
           JOIN insurance_companies c ON c.id = p.company_id WHERE p.id = ?""",
        (payment_id,),
    ).fetchone()


def add_payment(conn, p: PaymentInput) -> int:
    cur = conn.execute(
        """INSERT INTO insurance_payments (company_id, amount, received_date, reference_no, notes, created_by)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (p.company_id, p.amount, p.received_date, p.reference_no, p.notes, p.created_by),
    )
    conn.commit()
    return cur.lastrowid


def delete_payment(conn, payment_id: int) -> None:
    """Deletes the payment and its matches. Any invoice it was matched to
    just goes back to being outstanding by that amount."""
    conn.execute("DELETE FROM invoice_payment_matches WHERE payment_id = ?", (payment_id,))
    conn.execute("DELETE FROM insurance_payments WHERE id = ?", (payment_id,))
    conn.commit()


# ============================================================
# Reconciliation
# ============================================================

_AMOUNT_WEIGHT = 0.7
_DATE_WEIGHT = 0.3
_DATE_DECAY_DAYS = 30  # score halves roughly every this many days of gap


def _days_between(a: str, b: str) -> int:
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def suggest_matches_for_payment(conn, payment_id: int, top_n: int = 5) -> list[dict]:
    """Scored candidate invoices for one payment, same company only,
    restricted to invoices with an outstanding balance. Score is 0-100."""
    payment = get_payment(conn, payment_id)
    if payment is None:
        return []

    candidates = []
    for inv in list_invoices(conn, company_id=payment["company_id"]):
        paid = invoice_paid_amount(conn, inv["id"])
        balance = inv["amount"] - paid - (inv["insurer_deduction"] or 0)
        if balance <= 0:
            continue

        amount_diff = abs(payment["amount"] - balance)
        amount_score = 1.0 - min(1.0, amount_diff / max(payment["amount"], balance))

        days_gap = _days_between(payment["received_date"], inv["period_end"])
        date_score = 1.0 / (1.0 + days_gap / _DATE_DECAY_DAYS)

        score = _AMOUNT_WEIGHT * amount_score + _DATE_WEIGHT * date_score
        candidates.append({
            "invoice_id": inv["id"], "invoice_number": inv["invoice_number"] or "",
            "period_start": inv["period_start"], "period_end": inv["period_end"],
            "amount": inv["amount"], "balance": balance,
            "score": round(score * 100),
        })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates[:top_n]


def confirm_match(conn, invoice_id: int, payment_id: int, allocated_amount: int, matched_by: int | None, confidence: float | None = None) -> int:
    # Explicit RETURNING id -- the auto-lastrowid trick in pg_compat only
    # fires for bare INSERTs with no ON CONFLICT clause, and this needs the
    # upsert (re-confirming an already-suggested match updates it in place).
    # RETURNING on an ON CONFLICT DO UPDATE is supported by both SQLite
    # 3.35+ (this app requires 3.50+ already) and Postgres.
    cur = conn.execute(
        """INSERT INTO invoice_payment_matches (invoice_id, payment_id, allocated_amount, confidence_score, status, matched_by)
           VALUES (?, ?, ?, ?, 'confirmed', ?)
           ON CONFLICT (invoice_id, payment_id) DO UPDATE SET
               allocated_amount = excluded.allocated_amount, status = 'confirmed', matched_by = excluded.matched_by
           RETURNING id""",
        (invoice_id, payment_id, allocated_amount, confidence, matched_by),
    )
    conn.commit()
    row = cur.fetchone()
    return row["id"]
