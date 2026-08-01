"""Nutrition department module routes: Doctors/contracts, Revenues, Expenses, Settlement."""
from __future__ import annotations
import csv
import io

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse

from app.core.jalali import parse_jalali_str
from app.core.num2fa import amount_in_words_rials
from app.core.nutrition import (
    ContractInput, DoctorInput, EXPENSE_TYPES, ExpenseInput, RevenueInput,
    add_doctor, add_expense, add_revenue, compute_settlement_for_period,
    delete_expense, delete_revenue, find_existing_settlement, get_active_doctor,
    get_doctor, get_expense, get_partner_doctor, get_revenue, list_doctors, list_expenses,
    list_revenues, list_settlements, save_settlement, set_doctor_active,
    update_contract, update_doctor, update_expense, update_revenue,
)
from app.db.database import get_connection
from webapp.auth import CurrentUser, require_role
from webapp.helpers import ctx, templates
from webapp.payroll import PERSIAN_MONTHS, YEAR_RANGE, _default_period, _jalali_period

router = APIRouter()


def _parse_amount(text: str) -> int:
    try:
        val = int(text.strip().replace(",", ""))
    except ValueError:
        raise HTTPException(400, "مبلغ نامعتبر است.")
    if val < 0:
        raise HTTPException(400, "مبلغ نمی‌تواند منفی باشد.")
    return val


def _parse_signed_amount(text: str) -> int:
    try:
        return int(text.strip().replace(",", ""))
    except ValueError:
        raise HTTPException(400, "مبلغ تعدیل نامعتبر است.")


def _parse_date(text: str) -> str:
    try:
        return parse_jalali_str(text).isoformat()
    except Exception:
        raise HTTPException(400, "تاریخ را به فرم ۱۴۰۵/۰۳/۱۵ وارد کنید.")


# ============================================================
# Dashboard
# ============================================================

@router.get("/nutrition")
def dashboard(request: Request, user: CurrentUser = Depends(require_role("owner", "accountant", "manager"))):
    conn = get_connection()
    try:
        year, month = _default_period()
        period_start, period_end = _jalali_period(year, month)
        active_doctor = get_active_doctor(conn)
        breakdown = None
        if active_doctor is not None:
            breakdown = compute_settlement_for_period(
                conn, period_start.date().isoformat(), period_end.date().isoformat(), active_doctor["id"]
            )
    finally:
        conn.close()

    c = ctx(request, "nutrition_dashboard", "داشبورد بخش تغذیه", user)
    c.update({
        "month_label": PERSIAN_MONTHS[month - 1],
        "active_doctor": active_doctor,
        "breakdown": breakdown,
    })
    return templates.TemplateResponse(request, "nutrition_dashboard.html", c)


# ============================================================
# Doctors + contracts
# ============================================================

@router.get("/nutrition/doctors")
def doctors_page(request: Request, user: CurrentUser = Depends(require_role("owner", "accountant"))):
    conn = get_connection()
    try:
        doctors = list_doctors(conn)
    finally:
        conn.close()
    c = ctx(request, "nutrition_doctors", "پزشکان و قراردادهای تغذیه", user)
    c["doctors"] = doctors
    return templates.TemplateResponse(request, "nutrition_doctors.html", c)


def _check_percentages(clinic_pct: int, partner_pct: int) -> None:
    if clinic_pct + partner_pct != 100:
        raise HTTPException(400, "درصد سهم کلینیک و شریک بخش تغذیه باید مجموعاً ۱۰۰ باشد.")


@router.post("/nutrition/doctors/new")
def doctors_new(
    user: CurrentUser = Depends(require_role("owner", "accountant")),
    full_name: str = Form(...), phone: str = Form(""),
    contract_start: str = Form(""), contract_end: str = Form(""), notes: str = Form(""),
    doctor_percentage: int = Form(50), clinic_percentage: int = Form(50), partner_percentage: int = Form(50),
    contract_notes: str = Form(""), is_partner_self: str | None = Form(None),
):
    full_name = full_name.strip()
    if not full_name:
        raise HTTPException(400, "نام پزشک الزامی است.")
    _check_percentages(clinic_percentage, partner_percentage)
    conn = get_connection()
    try:
        doctor_id = add_doctor(
            conn,
            DoctorInput(
                full_name=full_name, phone=phone.strip() or None,
                contract_start=_parse_date(contract_start) if contract_start.strip() else None,
                contract_end=_parse_date(contract_end) if contract_end.strip() else None,
                notes=notes.strip() or None, is_partner_self=bool(is_partner_self),
            ),
            ContractInput(
                doctor_percentage=doctor_percentage, clinic_percentage=clinic_percentage,
                partner_percentage=partner_percentage, notes=contract_notes.strip() or None,
            ),
        )
        if len(list_doctors(conn)) == 1:
            # First doctor ever added -- activate automatically, nothing to conflict with.
            set_doctor_active(conn, doctor_id, True)
    finally:
        conn.close()
    return RedirectResponse(url="/nutrition/doctors", status_code=303)


@router.post("/nutrition/doctors/{doctor_id}/edit")
def doctors_edit(
    doctor_id: int, user: CurrentUser = Depends(require_role("owner", "accountant")),
    full_name: str = Form(...), phone: str = Form(""),
    contract_start: str = Form(""), contract_end: str = Form(""), notes: str = Form(""),
    doctor_percentage: int = Form(50), clinic_percentage: int = Form(50), partner_percentage: int = Form(50),
    contract_notes: str = Form(""), is_partner_self: str | None = Form(None),
):
    full_name = full_name.strip()
    if not full_name:
        raise HTTPException(400, "نام پزشک الزامی است.")
    _check_percentages(clinic_percentage, partner_percentage)
    conn = get_connection()
    try:
        if get_doctor(conn, doctor_id) is None:
            raise HTTPException(404)
        update_doctor(conn, doctor_id, DoctorInput(
            full_name=full_name, phone=phone.strip() or None,
            contract_start=_parse_date(contract_start) if contract_start.strip() else None,
            contract_end=_parse_date(contract_end) if contract_end.strip() else None,
            notes=notes.strip() or None, is_partner_self=bool(is_partner_self),
        ))
        update_contract(conn, doctor_id, ContractInput(
            doctor_percentage=doctor_percentage, clinic_percentage=clinic_percentage,
            partner_percentage=partner_percentage, notes=contract_notes.strip() or None,
        ))
    finally:
        conn.close()
    return RedirectResponse(url="/nutrition/doctors", status_code=303)


@router.post("/nutrition/doctors/{doctor_id}/activate")
def doctors_activate(doctor_id: int, user: CurrentUser = Depends(require_role("owner", "accountant"))):
    conn = get_connection()
    try:
        if get_doctor(conn, doctor_id) is None:
            raise HTTPException(404)
        set_doctor_active(conn, doctor_id, True)
    finally:
        conn.close()
    return RedirectResponse(url="/nutrition/doctors", status_code=303)


@router.post("/nutrition/doctors/{doctor_id}/deactivate")
def doctors_deactivate(doctor_id: int, user: CurrentUser = Depends(require_role("owner", "accountant"))):
    conn = get_connection()
    try:
        if get_doctor(conn, doctor_id) is None:
            raise HTTPException(404)
        set_doctor_active(conn, doctor_id, False)
    finally:
        conn.close()
    return RedirectResponse(url="/nutrition/doctors", status_code=303)


# ============================================================
# Revenues
# ============================================================

@router.get("/nutrition/revenues")
def revenues_page(request: Request, user: CurrentUser = Depends(require_role("owner", "accountant"))):
    conn = get_connection()
    try:
        revenues = list_revenues(conn)
        doctors = list_doctors(conn)
    finally:
        conn.close()
    c = ctx(request, "nutrition_revenues", "درآمد بخش تغذیه", user)
    c["revenues"] = revenues
    c["doctors"] = doctors
    c["total_amount"] = sum(r["amount"] for r in revenues)
    return templates.TemplateResponse(request, "nutrition_revenues.html", c)


@router.post("/nutrition/revenues/new")
def revenues_new(
    user: CurrentUser = Depends(require_role("owner", "accountant")),
    date: str = Form(...), amount: str = Form(...), doctor_id: int = Form(...),
    patient_name: str = Form(""), service_type: str = Form(""),
):
    date_iso = _parse_date(date)
    amount_val = _parse_amount(amount)
    conn = get_connection()
    try:
        add_revenue(conn, RevenueInput(
            date=date_iso, amount=amount_val, doctor_id=doctor_id,
            patient_name=patient_name.strip() or None, service_type=service_type.strip() or None,
        ), user.id)
    finally:
        conn.close()
    return RedirectResponse(url="/nutrition/revenues", status_code=303)


@router.post("/nutrition/revenues/{revenue_id}/edit")
def revenues_edit(
    revenue_id: int, user: CurrentUser = Depends(require_role("owner", "accountant")),
    date: str = Form(...), amount: str = Form(...), doctor_id: int = Form(...),
    patient_name: str = Form(""), service_type: str = Form(""),
):
    date_iso = _parse_date(date)
    amount_val = _parse_amount(amount)
    conn = get_connection()
    try:
        if get_revenue(conn, revenue_id) is None:
            raise HTTPException(404)
        update_revenue(conn, revenue_id, RevenueInput(
            date=date_iso, amount=amount_val, doctor_id=doctor_id,
            patient_name=patient_name.strip() or None, service_type=service_type.strip() or None,
        ))
    finally:
        conn.close()
    return RedirectResponse(url="/nutrition/revenues", status_code=303)


@router.post("/nutrition/revenues/{revenue_id}/delete")
def revenues_delete(revenue_id: int, user: CurrentUser = Depends(require_role("owner", "accountant"))):
    conn = get_connection()
    try:
        if get_revenue(conn, revenue_id) is None:
            raise HTTPException(404)
        delete_revenue(conn, revenue_id)
    finally:
        conn.close()
    return RedirectResponse(url="/nutrition/revenues", status_code=303)


# ============================================================
# Expenses
# ============================================================

@router.get("/nutrition/expenses")
def expenses_page(request: Request, user: CurrentUser = Depends(require_role("owner", "accountant")), expense_type: str | None = None):
    conn = get_connection()
    try:
        expenses = list_expenses(conn, expense_type=expense_type)
    finally:
        conn.close()
    c = ctx(request, "nutrition_expenses", "هزینه‌های بخش تغذیه", user)
    c["expenses"] = expenses
    c["expense_types"] = EXPENSE_TYPES
    c["sel_expense_type"] = expense_type
    c["total_consumable"] = sum(e["amount"] for e in expenses if e["expense_type"] == "consumable")
    c["total_non_consumable"] = sum(e["amount"] for e in expenses if e["expense_type"] == "non_consumable")
    return templates.TemplateResponse(request, "nutrition_expenses.html", c)


@router.post("/nutrition/expenses/new")
def expenses_new(
    user: CurrentUser = Depends(require_role("owner", "accountant")),
    date: str = Form(...), title: str = Form(...), amount: str = Form(...), expense_type: str = Form(...),
):
    title = title.strip()
    if not title:
        raise HTTPException(400, "عنوان هزینه الزامی است.")
    if expense_type not in EXPENSE_TYPES:
        raise HTTPException(400, "نوع هزینه نامعتبر است.")
    date_iso = _parse_date(date)
    amount_val = _parse_amount(amount)
    conn = get_connection()
    try:
        add_expense(conn, ExpenseInput(date=date_iso, title=title, amount=amount_val, expense_type=expense_type), user.id)
    finally:
        conn.close()
    return RedirectResponse(url="/nutrition/expenses", status_code=303)


@router.post("/nutrition/expenses/{expense_id}/edit")
def expenses_edit(
    expense_id: int, user: CurrentUser = Depends(require_role("owner", "accountant")),
    date: str = Form(...), title: str = Form(...), amount: str = Form(...), expense_type: str = Form(...),
):
    title = title.strip()
    if not title:
        raise HTTPException(400, "عنوان هزینه الزامی است.")
    if expense_type not in EXPENSE_TYPES:
        raise HTTPException(400, "نوع هزینه نامعتبر است.")
    date_iso = _parse_date(date)
    amount_val = _parse_amount(amount)
    conn = get_connection()
    try:
        if get_expense(conn, expense_id) is None:
            raise HTTPException(404)
        update_expense(conn, expense_id, ExpenseInput(date=date_iso, title=title, amount=amount_val, expense_type=expense_type))
    finally:
        conn.close()
    return RedirectResponse(url="/nutrition/expenses", status_code=303)


@router.post("/nutrition/expenses/{expense_id}/delete")
def expenses_delete(expense_id: int, user: CurrentUser = Depends(require_role("owner", "accountant"))):
    conn = get_connection()
    try:
        if get_expense(conn, expense_id) is None:
            raise HTTPException(404)
        delete_expense(conn, expense_id)
    finally:
        conn.close()
    return RedirectResponse(url="/nutrition/expenses", status_code=303)


# ============================================================
# Settlement
# ============================================================

def _settlement_ctx(request: Request, user: CurrentUser, conn, year: int, month: int) -> dict:
    period_start, period_end = _jalali_period(year, month)
    period_start_iso, period_end_iso = period_start.date().isoformat(), period_end.date().isoformat()
    active_doctor = get_active_doctor(conn)
    breakdown = None
    if active_doctor is not None:
        breakdown = compute_settlement_for_period(conn, period_start_iso, period_end_iso, active_doctor["id"])
    existing = find_existing_settlement(conn, period_start_iso, period_end_iso)

    c = ctx(request, "nutrition_settlement", "تسویه ماهانه بخش تغذیه", user)
    c.update({
        "sel_year": year, "sel_month": month,
        "year_range": YEAR_RANGE, "jalali_months": list(enumerate(PERSIAN_MONTHS, start=1)),
        "month_label": PERSIAN_MONTHS[month - 1],
        "active_doctor": active_doctor, "breakdown": breakdown,
        "already_saved": existing is not None,
        "existing_adjustment_amount": existing["adjustment_amount"] if existing else 0,
        "existing_adjustment_note": existing["adjustment_note"] if existing else "",
        "past_settlements": list_settlements(conn),
    })
    return c


@router.get("/nutrition/settlement")
def settlement_page(request: Request, user: CurrentUser = Depends(require_role("owner", "accountant")), year: int | None = None, month: int | None = None):
    sel_year, sel_month = (year, month) if (year and month) else _default_period()
    conn = get_connection()
    try:
        c = _settlement_ctx(request, user, conn, sel_year, sel_month)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "nutrition_settlement.html", c)


@router.post("/nutrition/settlement/save")
def settlement_save(
    user: CurrentUser = Depends(require_role("owner", "accountant")), year: int = Form(...), month: int = Form(...),
    adjustment_amount: str = Form("0"), adjustment_note: str = Form(""),
):
    period_start, period_end = _jalali_period(year, month)
    adjustment_val = _parse_signed_amount(adjustment_amount) if adjustment_amount.strip() else 0
    conn = get_connection()
    try:
        active_doctor = get_active_doctor(conn)
        if active_doctor is None:
            raise HTTPException(400, "هیچ پزشک فعالی برای بخش تغذیه ثبت نشده است.")
        breakdown = compute_settlement_for_period(conn, period_start.date().isoformat(), period_end.date().isoformat(), active_doctor["id"])
        save_settlement(
            conn, period_start.date().isoformat(), period_end.date().isoformat(), breakdown, user.id,
            adjustment_amount=adjustment_val, adjustment_note=adjustment_note.strip() or None,
        )
    finally:
        conn.close()
    return RedirectResponse(url=f"/nutrition/settlement?year={year}&month={month}", status_code=303)


@router.get("/nutrition/settlement/export.csv")
def settlement_export_csv(user: CurrentUser = Depends(require_role("owner", "accountant")), year: int | None = None, month: int | None = None):
    sel_year, sel_month = (year, month) if (year and month) else _default_period()
    period_start, period_end = _jalali_period(sel_year, sel_month)
    conn = get_connection()
    try:
        active_doctor = get_active_doctor(conn)
        if active_doctor is None:
            raise HTTPException(400, "هیچ پزشک فعالی برای بخش تغذیه ثبت نشده است.")
        b = compute_settlement_for_period(conn, period_start.date().isoformat(), period_end.date().isoformat(), active_doctor["id"])
    finally:
        conn.close()

    buf = io.StringIO()
    buf.write("﻿")  # BOM so Excel opens Persian text as UTF-8, not the system codepage
    w = csv.writer(buf)
    w.writerow(["تسویه ماهانه بخش تغذیه", f"{PERSIAN_MONTHS[sel_month - 1]} {sel_year}"])
    w.writerow(["پزشک", b["doctor_name"]])
    w.writerow([])
    w.writerow(["ردیف", "مبلغ (ریال)"])
    w.writerow(["درآمد ناخالص", b["gross_revenue"]])
    w.writerow(["هزینه‌های مصرفی", b["consumable_expenses"]])
    w.writerow(["هزینه‌های غیرمصرفی", b["non_consumable_expenses"]])
    w.writerow(["سهم پزشک از هزینه مصرفی", b["doctor_consumable_cut"]])
    w.writerow(["سهم پزشک", b["doctor_share"]])
    w.writerow(["باقیمانده پس از کسورات", b["remaining"]])
    w.writerow(["سهم کلینیک", b["clinic_share"]])
    w.writerow(["سهم شریک بخش تغذیه", b["partner_share"]])

    filename = f"nutrition-settlement-{sel_year}-{sel_month:02d}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/nutrition/settlement/invoice")
def settlement_invoice(request: Request, user: CurrentUser = Depends(require_role("owner", "accountant")), year: int | None = None, month: int | None = None):
    """Formal, printable settlement invoice to hand over to the nutrition
    partner -- separate from the internal breakdown on the settlement page."""
    sel_year, sel_month = (year, month) if (year and month) else _default_period()
    period_start, period_end = _jalali_period(sel_year, sel_month)
    period_start_iso, period_end_iso = period_start.date().isoformat(), period_end.date().isoformat()
    conn = get_connection()
    try:
        active_doctor = get_active_doctor(conn)
        if active_doctor is None:
            raise HTTPException(400, "هیچ پزشک فعالی برای بخش تغذیه ثبت نشده است.")
        breakdown = compute_settlement_for_period(conn, period_start_iso, period_end_iso, active_doctor["id"])
        existing = find_existing_settlement(conn, period_start_iso, period_end_iso)
        partner_doctor = get_partner_doctor(conn)
    finally:
        conn.close()

    adjustment_amount = existing["adjustment_amount"] if existing else 0
    adjustment_note = existing["adjustment_note"] if existing else None
    payable = breakdown["partner_share"] + adjustment_amount

    c = ctx(request, "nutrition_settlement", "فاکتور تسویه — شریک بخش تغذیه", user)
    c.update({
        "sel_year": sel_year, "sel_month": sel_month, "month_label": PERSIAN_MONTHS[sel_month - 1],
        "breakdown": breakdown, "adjustment_amount": adjustment_amount, "adjustment_note": adjustment_note,
        "partner_name": partner_doctor["full_name"] if partner_doctor else "شریک بخش تغذیه",
        "payable": payable, "payable_words": amount_in_words_rials(payable),
        "already_saved": existing is not None,
    })
    return templates.TemplateResponse(request, "nutrition_settlement_invoice.html", c)
