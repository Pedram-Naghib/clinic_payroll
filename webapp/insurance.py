"""Insurance module routes: Companies, Invoices, Payments, Reconciliation, Reports."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.core.insurance import (
    DEPARTMENTS, CompanyInput, InvoiceInput, PaymentInput,
    add_company, add_invoice, add_payment, confirm_match, delete_invoice, delete_payment, get_company, get_invoice, get_payment,
    invoice_matches, invoices_with_status, list_companies,
    list_invoices, list_payments, set_company_active, set_invoice_insurer_deduction,
    suggest_matches_for_payment, update_company,
)
from app.core.jalali import parse_jalali_str
from app.db.database import get_connection
from webapp.auth import CurrentUser, require_role
from webapp.helpers import ctx, templates

router = APIRouter()


# ============================================================
# Companies
# ============================================================

@router.get("/insurance/companies")
def companies_page(request: Request, user: CurrentUser = Depends(require_role("owner"))):
    conn = get_connection()
    try:
        rows = list_companies(conn)
        companies = []
        for r in rows:
            open_count = conn.execute(
                """SELECT COUNT(*) AS n FROM insurance_invoices i
                   WHERE i.company_id = ? AND (
                     i.amount - COALESCE((SELECT SUM(m.allocated_amount) FROM invoice_payment_matches m
                                           WHERE m.invoice_id = i.id AND m.status = 'confirmed'), 0)
                   ) > 0""",
                (r["id"],),
            ).fetchone()["n"]
            companies.append({
                "id": r["id"], "name": r["name"], "contact": r["contact_person"] or "—",
                "phone": r["phone"] or "—", "since": r["contract_start_date"] or "—",
                "open_invoices": open_count, "active": bool(r["active"]),
                "notes": r["notes"] or "",
                "raw_contact": r["contact_person"] or "", "raw_phone": r["phone"] or "",
                "raw_since": r["contract_start_date"] or "",
            })
    finally:
        conn.close()
    c = ctx(request, "companies", "شرکت‌های بیمه", user)
    c["companies"] = companies
    return templates.TemplateResponse(request, "insurance_companies.html", c)


@router.post("/insurance/companies/new")
def companies_new(
    user: CurrentUser = Depends(require_role("owner")),
    name: str = Form(...), contact_person: str = Form(""), phone: str = Form(""),
    contract_start_date: str = Form(""), notes: str = Form(""),
):
    name = name.strip()
    if not name:
        raise HTTPException(400, "نام شرکت بیمه الزامی است.")
    conn = get_connection()
    try:
        add_company(conn, CompanyInput(
            name=name, contact_person=contact_person.strip() or None, phone=phone.strip() or None,
            contract_start_date=contract_start_date.strip() or None, notes=notes.strip() or None,
        ))
    finally:
        conn.close()
    return RedirectResponse(url="/insurance/companies", status_code=303)


@router.post("/insurance/companies/{company_id}/edit")
def companies_edit(
    company_id: int, user: CurrentUser = Depends(require_role("owner")),
    name: str = Form(...), contact_person: str = Form(""), phone: str = Form(""),
    contract_start_date: str = Form(""), notes: str = Form(""),
):
    name = name.strip()
    if not name:
        raise HTTPException(400, "نام شرکت بیمه الزامی است.")
    conn = get_connection()
    try:
        if get_company(conn, company_id) is None:
            raise HTTPException(404)
        update_company(conn, company_id, CompanyInput(
            name=name, contact_person=contact_person.strip() or None, phone=phone.strip() or None,
            contract_start_date=contract_start_date.strip() or None, notes=notes.strip() or None,
        ))
    finally:
        conn.close()
    return RedirectResponse(url="/insurance/companies", status_code=303)


@router.post("/insurance/companies/{company_id}/toggle-active")
def companies_toggle_active(company_id: int, user: CurrentUser = Depends(require_role("owner"))):
    conn = get_connection()
    try:
        row = conn.execute("SELECT active FROM insurance_companies WHERE id = ?", (company_id,)).fetchone()
        if row is None:
            raise HTTPException(404)
        set_company_active(conn, company_id, not row["active"])
    finally:
        conn.close()
    return RedirectResponse(url="/insurance/companies", status_code=303)


# ============================================================
# Invoices
# ============================================================

@router.get("/insurance/invoices")
def invoices_page(request: Request, user: CurrentUser = Depends(require_role("owner", "accountant")), company_id: int | None = None):
    conn = get_connection()
    try:
        companies = list_companies(conn, active_only=True)
        invoices = invoices_with_status(conn, company_id)
    finally:
        conn.close()
    c = ctx(request, "invoices", "صورت‌حساب‌های بیمه", user)
    c["invoices"] = invoices
    c["companies"] = companies
    c["sel_company_id"] = company_id
    c["departments"] = DEPARTMENTS
    return templates.TemplateResponse(request, "insurance_invoices.html", c)


@router.post("/insurance/invoices/new")
def invoices_new(
    user: CurrentUser = Depends(require_role("owner", "accountant")),
    company_id: int = Form(...), period_start: str = Form(...), period_end: str = Form(...),
    amount: str = Form(...), department: str = Form("clinic"),
    invoice_number: str = Form(""), issued_date: str = Form(""), notes: str = Form(""),
):
    if department not in DEPARTMENTS:
        raise HTTPException(400, "بخش نامعتبر است.")
    try:
        period_start_iso = parse_jalali_str(period_start).isoformat()
        period_end_iso = parse_jalali_str(period_end).isoformat()
    except Exception:
        raise HTTPException(400, "تاریخ را به فرم ۱۴۰۵/۰۳/۱۵ وارد کنید.")
    try:
        amount_val = int(amount.strip().replace(",", ""))
    except ValueError:
        raise HTTPException(400, "مبلغ نامعتبر است.")
    if amount_val <= 0:
        raise HTTPException(400, "مبلغ باید بزرگ‌تر از صفر باشد.")

    conn = get_connection()
    try:
        add_invoice(conn, InvoiceInput(
            company_id=company_id, period_start=period_start_iso, period_end=period_end_iso,
            amount=amount_val, department=department, invoice_number=invoice_number.strip() or None,
            issued_date=issued_date.strip() or None, notes=notes.strip() or None,
            created_by=user.id,
        ))
    finally:
        conn.close()
    return RedirectResponse(url="/insurance/invoices", status_code=303)


def _invoice_detail_ctx(request: Request, user: CurrentUser, conn, invoice_id: int, error: str | None = None) -> dict:
    inv = get_invoice(conn, invoice_id)
    if inv is None:
        raise HTTPException(404)
    matches = invoice_matches(conn, invoice_id)
    with_status = {r["id"]: r for r in invoices_with_status(conn, company_id=inv["company_id"])}
    status_row = with_status[invoice_id]

    c = ctx(request, "invoices", f"صورت‌حساب {inv['invoice_number'] or ('#' + str(inv['id']))}", user)
    c["invoice"] = {
        "id": inv["id"], "company": inv["company_name"], "period_start": inv["period_start"],
        "period_end": inv["period_end"], "number": inv["invoice_number"] or "—",
        "department_label": DEPARTMENTS.get(inv["department"], inv["department"]), "amount": inv["amount"],
        "paid": status_row["paid"], "insurer_deduction": status_row["insurer_deduction"],
        "outstanding": status_row["outstanding"], "status": status_row["status"],
        "status_class": status_row["status_class"],
        "payments": [{"id": m["payment_id"], "date": m["received_date"], "amount": m["allocated_amount"], "ref": m["reference_no"] or "—"} for m in matches],
    }
    c["error"] = error
    return c


@router.get("/insurance/invoices/{invoice_id}")
def invoice_detail(request: Request, invoice_id: int, user: CurrentUser = Depends(require_role("owner"))):
    conn = get_connection()
    try:
        c = _invoice_detail_ctx(request, user, conn, invoice_id)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "insurance_invoice_detail.html", c)


@router.post("/insurance/invoices/{invoice_id}/deduction")
def invoice_set_deduction(
    request: Request, invoice_id: int, user: CurrentUser = Depends(require_role("owner")),
    insurer_deduction: str = Form(...),
):
    conn = get_connection()
    try:
        try:
            deduction_val = int(insurer_deduction.strip().replace(",", "") or "0")
            if deduction_val < 0:
                raise ValueError
        except ValueError:
            c = _invoice_detail_ctx(request, user, conn, invoice_id, error="مبلغ کسورات نامعتبر است.")
            return templates.TemplateResponse(request, "insurance_invoice_detail.html", c)
        set_invoice_insurer_deduction(conn, invoice_id, deduction_val)
    finally:
        conn.close()
    return RedirectResponse(url=f"/insurance/invoices/{invoice_id}", status_code=303)


@router.post("/insurance/invoices/{invoice_id}/delete")
def invoice_delete(invoice_id: int, user: CurrentUser = Depends(require_role("owner"))):
    conn = get_connection()
    try:
        if get_invoice(conn, invoice_id) is None:
            raise HTTPException(404)
        delete_invoice(conn, invoice_id)
    finally:
        conn.close()
    return RedirectResponse(url="/insurance/invoices", status_code=303)


# ============================================================
# Reconciliation + record a payment
# ============================================================

@router.get("/insurance/reconciliation")
def reconciliation_page(request: Request, user: CurrentUser = Depends(require_role("owner")), payment_id: int | None = None):
    conn = get_connection()
    try:
        companies = list_companies(conn, active_only=True)
        unmatched = list_payments(conn, unmatched_only=True)

        selected = None
        suggestions = []
        if payment_id is not None:
            selected = get_payment(conn, payment_id)
            if selected is not None:
                suggestions = suggest_matches_for_payment(conn, payment_id)
                all_company_invoices = list_invoices(conn, company_id=selected["company_id"])
    finally:
        conn.close()

    c = ctx(request, "reconciliation", "تطبیق پرداخت‌ها", user)
    c["companies"] = companies
    c["unmatched_payments"] = unmatched
    c["selected_payment"] = selected
    c["suggestions"] = suggestions
    c["all_company_invoices"] = all_company_invoices if payment_id and selected else []
    return templates.TemplateResponse(request, "insurance_reconciliation.html", c)


@router.post("/insurance/reconciliation/{payment_id}/confirm")
def reconciliation_confirm(
    payment_id: int, user: CurrentUser = Depends(require_role("owner")),
    invoice_id: int = Form(...), allocated_amount: str = Form(...), score: str | None = Form(None),
):
    try:
        amount_val = int(allocated_amount.strip().replace(",", ""))
    except ValueError:
        raise HTTPException(400, "مبلغ نامعتبر است.")
    confidence = float(score) / 100 if score else None
    conn = get_connection()
    try:
        confirm_match(conn, invoice_id, payment_id, amount_val, user.id, confidence)
    finally:
        conn.close()
    return RedirectResponse(url="/insurance/reconciliation", status_code=303)


@router.post("/insurance/payments/{payment_id}/delete")
def payment_delete(
    payment_id: int, user: CurrentUser = Depends(require_role("owner")),
    next: str = Form("/insurance/reconciliation"),
):
    conn = get_connection()
    try:
        if get_payment(conn, payment_id) is None:
            raise HTTPException(404)
        delete_payment(conn, payment_id)
    finally:
        conn.close()
    if not next.startswith("/"):
        next = "/insurance/reconciliation"
    return RedirectResponse(url=next, status_code=303)


@router.post("/insurance/payments/new")
def payments_new(
    user: CurrentUser = Depends(require_role("owner")),
    company_id: int = Form(...), amount: str = Form(...), received_date: str = Form(...),
    reference_no: str = Form(""), notes: str = Form(""),
):
    try:
        received_date_iso = parse_jalali_str(received_date).isoformat()
    except Exception:
        raise HTTPException(400, "تاریخ را به فرم ۱۴۰۵/۰۳/۱۵ وارد کنید.")
    try:
        amount_val = int(amount.strip().replace(",", ""))
    except ValueError:
        raise HTTPException(400, "مبلغ نامعتبر است.")
    if amount_val <= 0:
        raise HTTPException(400, "مبلغ باید بزرگ‌تر از صفر باشد.")

    conn = get_connection()
    try:
        new_id = add_payment(conn, PaymentInput(
            company_id=company_id, amount=amount_val, received_date=received_date_iso,
            reference_no=reference_no.strip() or None, notes=notes.strip() or None, created_by=user.id,
        ))
    finally:
        conn.close()
    return RedirectResponse(url=f"/insurance/reconciliation?payment_id={new_id}", status_code=303)


# ============================================================
# Reports
# ============================================================

@router.get("/insurance/reports")
def reports_page(request: Request, user: CurrentUser = Depends(require_role("owner")), company_id: int | None = None):
    conn = get_connection()
    try:
        companies = list_companies(conn)
        rows = []
        by_department: dict[str, dict] = {}
        for co in companies:
            if company_id is not None and co["id"] != company_id:
                continue
            invoices = invoices_with_status(conn, company_id=co["id"])
            total_amount = sum(i["amount"] for i in invoices)
            if total_amount == 0:
                continue
            total_paid = sum(i["paid"] for i in invoices)
            total_deduction = sum(i["insurer_deduction"] for i in invoices)
            total_outstanding = sum(i["outstanding"] for i in invoices)
            rate = round(total_deduction / total_amount * 100, 1)
            rows.append({
                "company_name": co["name"], "total_amount": total_amount, "total_paid": total_paid,
                "deduction": total_deduction, "outstanding": total_outstanding, "rate": rate,
            })
            for i in invoices:
                d = by_department.setdefault(i["department"], {
                    "label": i["department_label"], "total_amount": 0, "total_paid": 0,
                    "deduction": 0, "outstanding": 0,
                })
                d["total_amount"] += i["amount"]
                d["total_paid"] += i["paid"]
                d["deduction"] += i["insurer_deduction"]
                d["outstanding"] += i["outstanding"]
    finally:
        conn.close()

    grand_amount = sum(r["total_amount"] for r in rows)
    grand_paid = sum(r["total_paid"] for r in rows)
    grand_deduction = sum(r["deduction"] for r in rows)
    grand_outstanding = sum(r["outstanding"] for r in rows)
    grand_rate = round(grand_deduction / grand_amount * 100, 1) if grand_amount else 0.0
    department_rows = [
        {**d, "rate": round(d["deduction"] / d["total_amount"] * 100, 1) if d["total_amount"] else 0.0}
        for d in by_department.values()
    ]

    c = ctx(request, "reports", "گزارش‌های بیمه", user)
    c.update({
        "companies": companies, "sel_company_id": company_id, "rows": rows,
        "department_rows": department_rows,
        "grand_amount": grand_amount, "grand_paid": grand_paid,
        "grand_deduction": grand_deduction, "grand_outstanding": grand_outstanding, "grand_rate": grand_rate,
    })
    return templates.TemplateResponse(request, "insurance_reports.html", c)
