"""Payroll module routes: Employees, Attendance/punch import, Payroll runs, Payslips."""
from __future__ import annotations
import os
import tempfile
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse

from app.core import roles as roles_core
from app.core.attendance_engine import (
    build_payroll_inputs, compute_and_persist_attendance,
    delete_manual_month_attendance, manual_attendance_month_totals, save_manual_month_attendance,
)
from app.core.commissions import (
    CommissionInput, SERVICE_TYPES, add_commission, compute_commission_amount,
    delete_commission, get_commission_rate, list_commissions,
)
from app.core.config import add_config, get_all_config, get_config, set_config
from app.core.employees import EmployeeInput, add_employee, delete_employee, list_employees, update_employee
from app.core.jalali import gregorian_to_jalali, jalali_to_gregorian, parse_jalali_str, to_jalali_str
from app.core.leave import (
    LeaveRequestInput, cancel_leave_request, compute_year_end_payout, create_leave_request,
    days_used_this_jalali_year, get_leave_balance, list_leave_requests, settle_year_end_payout,
)
from app.core.num2fa import amount_in_words_rials
from app.core.pay_rounding import calculate_payroll_batch, calculate_payroll_for_employee
from app.core.payslip import build_payslip
from app.core.payroll_runs import find_existing_run, save_payroll_run
from app.core.punch_importer import (
    delete_all_punches, delete_punches_in_period, import_punches_file,
    punch_summary as get_punch_summary, relink_unmatched_punches,
)
from app.core.roles import get_employees_with_role
from app.db.database import get_connection
from app.ui import strings_fa as S
from webapp.auth import CurrentUser, require_role
from webapp.helpers import ctx, templates

router = APIRouter()

PERSIAN_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
                  "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
YEAR_RANGE = list(range(1402, 1410))


def _default_period() -> tuple[int, int]:
    today = date.today()
    jy, jm, _ = gregorian_to_jalali(today.year, today.month, today.day)
    return jy, jm


def _jalali_period(year: int, month: int) -> tuple[datetime, datetime]:
    period_start_d = jalali_to_gregorian(year, month, 1)
    period_end_d = jalali_to_gregorian(year, month + 1, 1) if month < 12 else jalali_to_gregorian(year + 1, 1, 1)
    return datetime.combine(period_start_d, time(0, 0, 0)), datetime.combine(period_end_d, time(0, 0, 0))


# ============================================================
# Employees
# ============================================================

def _employee_to_dict(row, roles_map: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["full_name"],
        "roles": roles_map.get(row["id"], []),
        "type": row["employment_type"],
        "device": row["device_enroll_no"] or "",
        "exempt": bool(row["is_exempt_from_shifts"]),
        "fixed_salary": row["fixed_monthly_salary"],
        "hourly_rate": row["base_hourly_rate"],
        "married": bool(row["is_married"]),
        "children": row["number_of_children"] or 0,
        "seniority": row["seniority_allowance"] or 0,
        "vacation_balance": row["vacation_balance_days"] or 0,
        "notes": row["notes"] or "",
        "active": bool(row["active"]),
    }


def _int_or_none(text: str) -> int | None:
    text = (text or "").strip().replace(",", "")
    return int(text) if text else None


def _employee_input_from_form(
    full_name: str, employment_type: str, device_enroll_no: str,
    is_exempt_from_shifts: str | None, fixed_monthly_salary: str, base_hourly_rate: str,
    is_married: str | None, number_of_children: int, seniority_allowance: str,
    vacation_balance_days: str, notes: str,
) -> EmployeeInput:
    return EmployeeInput(
        full_name=full_name.strip(),
        employment_type=employment_type,
        device_enroll_no=device_enroll_no.strip() or None,
        is_exempt_from_shifts=bool(is_exempt_from_shifts),
        fixed_monthly_salary=_int_or_none(fixed_monthly_salary),
        base_hourly_rate=_int_or_none(base_hourly_rate),
        is_married=bool(is_married),
        number_of_children=number_of_children,
        seniority_allowance=_int_or_none(seniority_allowance) or 0,
        vacation_balance_days=float(vacation_balance_days) if (vacation_balance_days or "").strip() else 0.0,
        notes=notes.strip() or None,
    )


@router.get("/payroll/employees")
def payroll_employees(request: Request, user: CurrentUser = Depends(require_role("owner"))):
    conn = get_connection()
    try:
        rows = list_employees(conn, active_only=False)
        roles_map = roles_core.get_employee_roles_map(conn)
        all_roles = roles_core.list_all_roles(conn)
    finally:
        conn.close()
    c = ctx(request, "employees", "پرسنل", user)
    c["employees"] = [_employee_to_dict(r, roles_map) for r in rows]
    c["all_roles"] = all_roles
    return templates.TemplateResponse(request, "payroll_employees.html", c)


@router.post("/payroll/employees/new")
def payroll_employees_create(
    user: CurrentUser = Depends(require_role("owner")),
    full_name: str = Form(...), employment_type: str = Form(...), device_enroll_no: str = Form(""),
    is_exempt_from_shifts: str | None = Form(None), fixed_monthly_salary: str = Form(""),
    base_hourly_rate: str = Form(""), is_married: str | None = Form(None),
    number_of_children: int = Form(0), seniority_allowance: str = Form("0"),
    vacation_balance_days: str = Form("0"), roles: list[str] = Form([]), notes: str = Form(""),
):
    emp_input = _employee_input_from_form(
        full_name, employment_type, device_enroll_no, is_exempt_from_shifts, fixed_monthly_salary,
        base_hourly_rate, is_married, number_of_children, seniority_allowance, vacation_balance_days, notes,
    )
    if not emp_input.full_name:
        raise HTTPException(400, "نام الزامی است")
    conn = get_connection()
    try:
        new_id = add_employee(conn, emp_input)
        roles_core.set_employee_roles(conn, new_id, [r.strip() for r in roles if r.strip()])
    finally:
        conn.close()
    return RedirectResponse(url="/payroll/employees", status_code=303)


@router.post("/payroll/employees/{employee_id}/edit")
def payroll_employees_update(
    employee_id: int, user: CurrentUser = Depends(require_role("owner")),
    full_name: str = Form(...), employment_type: str = Form(...), device_enroll_no: str = Form(""),
    is_exempt_from_shifts: str | None = Form(None), fixed_monthly_salary: str = Form(""),
    base_hourly_rate: str = Form(""), is_married: str | None = Form(None),
    number_of_children: int = Form(0), seniority_allowance: str = Form("0"),
    vacation_balance_days: str = Form("0"), roles: list[str] = Form([]), notes: str = Form(""),
):
    emp_input = _employee_input_from_form(
        full_name, employment_type, device_enroll_no, is_exempt_from_shifts, fixed_monthly_salary,
        base_hourly_rate, is_married, number_of_children, seniority_allowance, vacation_balance_days, notes,
    )
    if not emp_input.full_name:
        raise HTTPException(400, "نام الزامی است")
    conn = get_connection()
    try:
        update_employee(conn, employee_id, emp_input)
        roles_core.set_employee_roles(conn, employee_id, [r.strip() for r in roles if r.strip()])
    finally:
        conn.close()
    return RedirectResponse(url="/payroll/employees", status_code=303)


@router.post("/payroll/employees/{employee_id}/toggle-active")
def payroll_employees_toggle_active(employee_id: int, user: CurrentUser = Depends(require_role("owner"))):
    conn = get_connection()
    try:
        row = conn.execute("SELECT active FROM employees WHERE id = ?", (employee_id,)).fetchone()
        if row is None:
            raise HTTPException(404)
        if row["active"]:
            delete_employee(conn, employee_id, hard_delete=False)
        else:
            conn.execute("UPDATE employees SET active = 1 WHERE id = ?", (employee_id,))
            conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/payroll/employees", status_code=303)


# ============================================================
# Attendance / punch import
# ============================================================

def _attendance_base_ctx(request: Request, user: CurrentUser, conn, sel_year: int, sel_month: int) -> dict:
    period_start, period_end = _jalali_period(sel_year, sel_month)
    totals = manual_attendance_month_totals(conn, period_start.date().isoformat(), period_end.date().isoformat())
    manual_entries = [{"employee_id": emp_id, **data} for emp_id, data in totals.items()]
    manual_entries.sort(key=lambda e: e["employee_name"])

    c = ctx(request, "attendance", "تردد و حضور", user)
    c.update({
        "punch_summary": get_punch_summary(conn),
        "sel_year": sel_year, "sel_month": sel_month,
        "year_range": YEAR_RANGE, "jalali_months": list(enumerate(PERSIAN_MONTHS, start=1)),
        "import_result": None, "relink_result": None, "clear_result": None, "attendance_results": None,
        "manual_employees": list_employees(conn, active_only=True),
        "manual_entries": manual_entries,
        "manual_saved": False, "manual_error": None, "manual_preview": None,
    })
    return c


@router.get("/payroll/attendance")
def attendance_page(
    request: Request, user: CurrentUser = Depends(require_role("owner")),
    year: int | None = None, month: int | None = None,
):
    sel_year, sel_month = (year, month) if (year and month) else _default_period()
    conn = get_connection()
    try:
        c = _attendance_base_ctx(request, user, conn, sel_year, sel_month)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "attendance.html", c)


@router.post("/payroll/attendance/import")
async def attendance_import(
    request: Request, user: CurrentUser = Depends(require_role("owner")), file: UploadFile = File(...),
):
    content = await file.read()
    fd, tmp_path = tempfile.mkstemp(suffix=".TXT")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        conn = get_connection()
        try:
            result = import_punches_file(conn, tmp_path)
            sel_year, sel_month = _default_period()
            c = _attendance_base_ctx(request, user, conn, sel_year, sel_month)
        finally:
            conn.close()
    finally:
        os.unlink(tmp_path)
    c["import_result"] = result
    return templates.TemplateResponse(request, "attendance.html", c)


@router.post("/payroll/attendance/relink")
def attendance_relink(request: Request, user: CurrentUser = Depends(require_role("owner"))):
    conn = get_connection()
    try:
        n = relink_unmatched_punches(conn)
        sel_year, sel_month = _default_period()
        c = _attendance_base_ctx(request, user, conn, sel_year, sel_month)
    finally:
        conn.close()
    c["relink_result"] = n
    return templates.TemplateResponse(request, "attendance.html", c)


@router.post("/payroll/attendance/clear-month")
def attendance_clear_month(
    request: Request, user: CurrentUser = Depends(require_role("owner")),
    year: int = Form(...), month: int = Form(...),
):
    period_start, period_end = _jalali_period(year, month)
    conn = get_connection()
    try:
        deleted = delete_punches_in_period(conn, period_start, period_end)
        c = _attendance_base_ctx(request, user, conn, year, month)
    finally:
        conn.close()
    c["clear_result"] = f"{deleted:,} رکورد برای {PERSIAN_MONTHS[month - 1]} {year} حذف شد."
    return templates.TemplateResponse(request, "attendance.html", c)


@router.post("/payroll/attendance/clear-all")
def attendance_clear_all(request: Request, user: CurrentUser = Depends(require_role("owner"))):
    conn = get_connection()
    try:
        deleted = delete_all_punches(conn)
        sel_year, sel_month = _default_period()
        c = _attendance_base_ctx(request, user, conn, sel_year, sel_month)
    finally:
        conn.close()
    c["clear_result"] = f"همهٔ {deleted:,} رکورد حذف شد."
    return templates.TemplateResponse(request, "attendance.html", c)


@router.post("/payroll/attendance/compute")
def attendance_compute(
    request: Request, user: CurrentUser = Depends(require_role("owner")),
    year: int = Form(...), month: int = Form(...),
):
    period_start, period_end = _jalali_period(year, month)
    conn = get_connection()
    try:
        results = compute_and_persist_attendance(conn, period_start, period_end)
        c = _attendance_base_ctx(request, user, conn, year, month)
    finally:
        conn.close()
    c["attendance_results"] = results
    return templates.TemplateResponse(request, "attendance.html", c)


# ============================================================
# Manual attendance entry -- for a month the Owner doesn't trust (or doesn't
# have) device punch data for. Entered as whole-month totals (total hours +
# hours worked on a holiday), not day by day. See
# app.core.attendance_engine.save_manual_month_attendance.
# ============================================================

def _manual_preview(conn, employee_id: int, year: int, month: int):
    """Recomputes this Jalali month's payroll for just this one employee, so
    the Owner immediately sees what the entry they just saved translates to
    -- without running the full monthly payroll batch."""
    period_start, period_end = _jalali_period(year, month)
    inputs = build_payroll_inputs(conn, period_start, period_end)
    worked_hours, holiday_hours = inputs.get(employee_id, (0.0, 0.0))
    employee = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    return calculate_payroll_for_employee(conn, employee, worked_hours, holiday_hours) if employee else None


@router.post("/payroll/attendance/manual/save")
def attendance_manual_save(
    request: Request, user: CurrentUser = Depends(require_role("owner")),
    year: int = Form(...), month: int = Form(...),
    employee_id: int = Form(...), total_hours: str = Form(...), holiday_hours: str = Form("0"),
    note: str = Form(""),
):
    conn = get_connection()
    try:
        try:
            total_val = float(total_hours.strip())
            holiday_val = float(holiday_hours.strip() or "0")
        except ValueError:
            c = _attendance_base_ctx(request, user, conn, year, month)
            c["manual_error"] = "ساعت کارکرد باید عدد باشد."
            return templates.TemplateResponse(request, "attendance.html", c)

        period_start, period_end = _jalali_period(year, month)
        try:
            save_manual_month_attendance(
                conn, employee_id, period_start.date().isoformat(), period_end.date().isoformat(),
                total_val, holiday_val, note.strip() or None,
            )
        except ValueError as e:
            c = _attendance_base_ctx(request, user, conn, year, month)
            c["manual_error"] = str(e)
            return templates.TemplateResponse(request, "attendance.html", c)

        c = _attendance_base_ctx(request, user, conn, year, month)
        c["manual_saved"] = True
        c["manual_preview"] = _manual_preview(conn, employee_id, year, month)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "attendance.html", c)


@router.post("/payroll/attendance/manual/{employee_id}/delete")
def attendance_manual_delete(
    employee_id: int, request: Request,
    user: CurrentUser = Depends(require_role("owner")),
    year: int = Form(...), month: int = Form(...),
):
    period_start, period_end = _jalali_period(year, month)
    conn = get_connection()
    try:
        delete_manual_month_attendance(conn, employee_id, period_start.date().isoformat(), period_end.date().isoformat())
    finally:
        conn.close()
    return RedirectResponse(url=f"/payroll/attendance?year={year}&month={month}", status_code=303)


# ============================================================
# Payroll runs
# ============================================================

def _run_payroll(conn, year: int, month: int):
    period_start, period_end = _jalali_period(year, month)
    compute_and_persist_attendance(conn, period_start, period_end)
    inputs = build_payroll_inputs(conn, period_start, period_end)
    results, skipped_ids = calculate_payroll_batch(conn, inputs)
    skipped_names = []
    for emp_id in skipped_ids:
        row = conn.execute("SELECT full_name FROM employees WHERE id = ?", (emp_id,)).fetchone()
        skipped_names.append(row["full_name"] if row else str(emp_id))
    return period_start, period_end, results, skipped_names


def _runs_base_ctx(request: Request, user: CurrentUser, sel_year: int, sel_month: int) -> dict:
    c = ctx(request, "payroll_runs", "اجرای حقوق", user)
    c.update({
        "sel_year": sel_year, "sel_month": sel_month,
        "year_range": YEAR_RANGE, "jalali_months": list(enumerate(PERSIAN_MONTHS, start=1)),
        "results": None, "skipped_names": [], "grand_total": 0,
        "existing_run": None, "just_saved": False,
    })
    return c


@router.get("/payroll/runs")
def payroll_runs_page(request: Request, user: CurrentUser = Depends(require_role("owner"))):
    sel_year, sel_month = _default_period()
    return templates.TemplateResponse(request, "payroll_runs.html", _runs_base_ctx(request, user, sel_year, sel_month))


@router.post("/payroll/runs/run")
def payroll_runs_run(
    request: Request, user: CurrentUser = Depends(require_role("owner")),
    year: int = Form(...), month: int = Form(...),
):
    conn = get_connection()
    try:
        _, _, results, skipped_names = _run_payroll(conn, year, month)
    finally:
        conn.close()
    c = _runs_base_ctx(request, user, year, month)
    c["results"] = results
    c["skipped_names"] = skipped_names
    c["grand_total"] = sum(r.total_pay for r in results)
    return templates.TemplateResponse(request, "payroll_runs.html", c)


@router.post("/payroll/runs/save")
def payroll_runs_save(
    request: Request, user: CurrentUser = Depends(require_role("owner")),
    year: int = Form(...), month: int = Form(...), confirm: str | None = Form(None),
):
    conn = get_connection()
    try:
        period_start, period_end, results, skipped_names = _run_payroll(conn, year, month)
        existing = find_existing_run(conn, period_start.date().isoformat(), period_end.date().isoformat())

        c = _runs_base_ctx(request, user, year, month)
        c["results"] = results
        c["skipped_names"] = skipped_names
        c["grand_total"] = sum(r.total_pay for r in results)

        if existing is not None and not confirm:
            c["existing_run"] = existing
            conn.close()
            return templates.TemplateResponse(request, "payroll_runs.html", c)

        run_id = save_payroll_run(
            conn, period_start.date().isoformat(), period_end.date().isoformat(), results,
            overwrite_run_id=existing["id"] if existing else None,
        )
        c["just_saved"] = run_id
    finally:
        conn.close()
    return templates.TemplateResponse(request, "payroll_runs.html", c)


# ============================================================
# Payslips
# ============================================================

@router.get("/payroll/payslip/{employee_id}")
def payroll_payslip(
    request: Request, employee_id: int, user: CurrentUser = Depends(require_role("owner")),
    year: int | None = None, month: int | None = None,
):
    conn = get_connection()
    try:
        emp = conn.execute("SELECT id, full_name FROM employees WHERE id = ?", (employee_id,)).fetchone()
        if emp is None:
            raise HTTPException(404)

        if year is None or month is None:
            latest = conn.execute(
                """SELECT pr.period_start, pr.period_end, pr.period_start AS ps
                   FROM payroll_line_items pli JOIN payroll_runs pr ON pr.id = pli.payroll_run_id
                   WHERE pli.employee_id = ? ORDER BY pr.generated_at DESC LIMIT 1""",
                (employee_id,),
            ).fetchone()
            if latest is None:
                c = ctx(request, "payroll_runs", f"فیش حقوقی — {emp['full_name']}", user)
                c["employee_name"] = emp["full_name"]
                return templates.TemplateResponse(request, "payslip_empty.html", c)
            gy, gm, gd = (int(x) for x in latest["period_start"].split("-"))
            year, month, _ = gregorian_to_jalali(gy, gm, gd)

        period_start, period_end = _jalali_period(year, month)
        period_label = f"{PERSIAN_MONTHS[month - 1]} {year}"
        payslip = build_payslip(conn, employee_id, period_start, period_end, period_label)
    finally:
        conn.close()

    if payslip is None:
        c = ctx(request, "payroll_runs", f"فیش حقوقی — {emp['full_name']}", user)
        c["employee_name"] = emp["full_name"]
        return templates.TemplateResponse(request, "payslip_empty.html", c)

    c = ctx(request, "payroll_runs", f"فیش حقوقی — {payslip.full_name}", user)
    c["payslip"] = payslip
    c["employment_type_label"] = "بیمه‌شده" if payslip.employment_type == "insured" else "غیر بیمه‌شده"
    c["words"] = amount_in_words_rials(payslip.net_pay)
    today = date.today()
    ty, tm, td = gregorian_to_jalali(today.year, today.month, today.day)
    c["today_jalali"] = f"{ty:04d}/{tm:02d}/{td:02d}"
    return templates.TemplateResponse(request, "payslip.html", c)


# ============================================================
# System Config
# ============================================================

@router.get("/payroll/config")
def payroll_config(request: Request, user: CurrentUser = Depends(require_role("owner")), saved: bool = False):
    conn = get_connection()
    try:
        rows = get_all_config(conn)
    finally:
        conn.close()
    c = ctx(request, "config", "تنظیمات سیستم", user)
    c["config_rows"] = [
        {
            "key": r["key"], "value": r["value"], "value_type": r["value_type"],
            "label_fa": S.t_config_label(r["key"], r["label"]),
            "desc_fa": S.t_config_desc(r["key"], r["description"] or ""),
            "category_fa": S.t_category(r["category"] or ""),
        }
        for r in rows
    ]
    c["saved"] = saved
    c["error"] = None
    return templates.TemplateResponse(request, "payroll_config.html", c)


@router.post("/payroll/config/save")
async def payroll_config_save(request: Request, user: CurrentUser = Depends(require_role("owner"))):
    form = await request.form()
    conn = get_connection()
    try:
        rows = get_all_config(conn)
        for r in rows:
            value = form.get(f"value__{r['key']}")
            if value is None:
                continue
            try:
                if r["value_type"] == "int":
                    int(value)
                elif r["value_type"] == "float":
                    float(value)
            except ValueError:
                c = ctx(request, "config", "تنظیمات سیستم", user)
                c["config_rows"] = [
                    {
                        "key": rr["key"], "value": rr["value"], "value_type": rr["value_type"],
                        "label_fa": S.t_config_label(rr["key"], rr["label"]),
                        "desc_fa": S.t_config_desc(rr["key"], rr["description"] or ""),
                        "category_fa": S.t_category(rr["category"] or ""),
                    }
                    for rr in rows
                ]
                c["saved"] = False
                c["error"] = f"مقدار «{S.t_config_label(r['key'], r['label'])}» با نوع داده '{r['value_type']}' سازگار نیست."
                return templates.TemplateResponse(request, "payroll_config.html", c)
            set_config(conn, r["key"], value)
    finally:
        conn.close()
    return RedirectResponse(url="/payroll/config?saved=1", status_code=303)


@router.post("/payroll/config/add")
def payroll_config_add(
    user: CurrentUser = Depends(require_role("owner")),
    key: str = Form(...), label: str = Form(...), value: str = Form(...),
    value_type: str = Form("int"), category: str = Form("general"), description: str = Form(""),
):
    key = key.strip()
    label = label.strip()
    if not key or not label:
        raise HTTPException(400, "کلید و عنوان الزامی هستند.")
    try:
        if value_type == "int":
            int(value)
        elif value_type == "float":
            float(value)
    except ValueError:
        raise HTTPException(400, f"مقدار با نوع داده '{value_type}' سازگار نیست.")
    conn = get_connection()
    try:
        add_config(conn, key, value.strip(), value_type, label, description.strip(), category.strip() or "general")
    finally:
        conn.close()
    return RedirectResponse(url="/payroll/config", status_code=303)


# ============================================================
# Allowance Rules
# ============================================================

def _amount_source_label(row) -> str:
    amount_type = row["amount_type"]
    if amount_type == "config_flat":
        return S.SRC_CONFIG.format(key=S.t_config_label(row["config_key"], row["config_key"]))
    if amount_type == "config_per_child":
        return S.SRC_CONFIG_PER_CHILD.format(key=S.t_config_label(row["config_key"], row["config_key"]))
    if amount_type == "config_per_hour":
        return S.SRC_CONFIG.format(key=S.t_config_label(row["config_key"], row["config_key"]))
    if amount_type == "employee_field_flat":
        return S.SRC_EMP_FIELD.format(field=S.t_emp_field(row["employee_field"]))
    if amount_type == "employee_field_per_hour":
        return S.SRC_EMP_FIELD_PER_HOUR.format(field=S.t_emp_field(row["employee_field"]))
    return amount_type


@router.get("/payroll/allowance-rules")
def allowance_rules_page(request: Request, user: CurrentUser = Depends(require_role("owner")), saved: bool = False):
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM allowance_definitions ORDER BY sort_order").fetchall()
    finally:
        conn.close()
    c = ctx(request, "allowance_rules", "قوانین مزایا", user)
    c["allowances"] = [
        {
            "code": r["code"], "label_fa": S.t_allowance_label(r["code"], r["label"]),
            "enabled": bool(r["enabled"]), "applies_insured": bool(r["applies_to_insured"]),
            "applies_non_insured": bool(r["applies_to_non_insured"]), "source_fa": _amount_source_label(r),
        }
        for r in rows
    ]
    c["saved"] = saved
    return templates.TemplateResponse(request, "payroll_allowance_rules.html", c)


@router.post("/payroll/allowance-rules/save")
async def allowance_rules_save(request: Request, user: CurrentUser = Depends(require_role("owner"))):
    form = await request.form()
    conn = get_connection()
    try:
        codes = [r["code"] for r in conn.execute("SELECT code FROM allowance_definitions").fetchall()]
        for code in codes:
            enabled = int(form.get(f"enabled__{code}") is not None)
            applies_insured = int(form.get(f"insured__{code}") is not None)
            applies_non_insured = int(form.get(f"non_insured__{code}") is not None)
            conn.execute(
                """UPDATE allowance_definitions
                   SET enabled = ?, applies_to_insured = ?, applies_to_non_insured = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE code = ?""",
                (enabled, applies_insured, applies_non_insured, code),
            )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/payroll/allowance-rules?saved=1", status_code=303)


# ============================================================
# Leave
# ============================================================

def _leave_page_ctx(request: Request, user: CurrentUser, conn, sel_employee_id: int | None) -> dict:
    employees = list_employees(conn, active_only=True)
    cap = int(get_config(conn, "annual_paid_leave_days_cap", default=30))
    today = date.today()
    jy, _, _ = gregorian_to_jalali(today.year, today.month, today.day)

    balances = []
    for emp in employees:
        balance = get_leave_balance(conn, emp["id"])
        used = days_used_this_jalali_year(conn, emp["id"], jy)
        balances.append({"id": emp["id"], "name": emp["full_name"], "balance": balance, "cap": cap, "used": used})

    history = list_leave_requests(conn, employee_id=sel_employee_id)

    c = ctx(request, "leave", "مرخصی", user)
    c.update({
        "employees": employees, "balances": balances, "history": history,
        "sel_employee_id": sel_employee_id, "today_jalali_str": to_jalali_str(today),
        "error": None, "saved": False, "settle_result": None,
    })
    return c


@router.get("/payroll/leave")
def leave_page(request: Request, user: CurrentUser = Depends(require_role("owner")), employee_id: int | None = None):
    conn = get_connection()
    try:
        c = _leave_page_ctx(request, user, conn, employee_id)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "payroll_leave.html", c)


@router.post("/payroll/leave/new")
def leave_new(
    request: Request, user: CurrentUser = Depends(require_role("owner")),
    employee_id: int = Form(...), leave_type: str = Form(...),
    start_date: str = Form(...), end_date: str = Form(...),
    days_count: str = Form(...), notes: str = Form(""),
):
    conn = get_connection()
    try:
        try:
            start_iso = parse_jalali_str(start_date).isoformat()
            end_iso = parse_jalali_str(end_date).isoformat()
        except Exception:
            c = _leave_page_ctx(request, user, conn, employee_id)
            c["error"] = "تاریخ را به فرم ۱۴۰۵/۰۳/۱۵ وارد کنید."
            return templates.TemplateResponse(request, "payroll_leave.html", c)

        try:
            days = float(days_count.strip() or "0")
        except ValueError:
            days = 0
        if days <= 0:
            c = _leave_page_ctx(request, user, conn, employee_id)
            c["error"] = "تعداد روز نامعتبر است."
            return templates.TemplateResponse(request, "payroll_leave.html", c)

        try:
            create_leave_request(
                conn,
                LeaveRequestInput(
                    employee_id=employee_id, leave_type=leave_type,
                    start_date=start_iso, end_date=end_iso,
                    days_count=days, notes=notes.strip() or None,
                ),
            )
        except ValueError as e:
            c = _leave_page_ctx(request, user, conn, employee_id)
            c["error"] = str(e)
            return templates.TemplateResponse(request, "payroll_leave.html", c)

        c = _leave_page_ctx(request, user, conn, employee_id)
        c["saved"] = True
    finally:
        conn.close()
    return templates.TemplateResponse(request, "payroll_leave.html", c)


@router.post("/payroll/leave/{request_id}/cancel")
def leave_cancel(request_id: int, user: CurrentUser = Depends(require_role("owner")), employee_id: int | None = Form(None)):
    conn = get_connection()
    try:
        try:
            cancel_leave_request(conn, request_id)
        except ValueError:
            pass  # auto_shortfall rows refuse direct cancellation, matching desktop behavior
    finally:
        conn.close()
    url = f"/payroll/leave?employee_id={employee_id}" if employee_id else "/payroll/leave"
    return RedirectResponse(url=url, status_code=303)


@router.post("/payroll/leave/{employee_id}/settle")
def leave_settle(request: Request, employee_id: int, user: CurrentUser = Depends(require_role("owner"))):
    conn = get_connection()
    try:
        paid = settle_year_end_payout(conn, employee_id)
        c = _leave_page_ctx(request, user, conn, employee_id)
        c["settle_result"] = paid
    finally:
        conn.close()
    return templates.TemplateResponse(request, "payroll_leave.html", c)


# ============================================================
# Direct Commissions
# ============================================================

BEHYAR_ROLE_NAME = "بهیار"


def _commissions_page_ctx(request: Request, user: CurrentUser, conn, sel_employee_id: int | None) -> dict:
    eligible_employees = get_employees_with_role(conn, BEHYAR_ROLE_NAME, active_only=True)
    all_employees = list_employees(conn, active_only=True)
    history = list_commissions(conn, employee_id=sel_employee_id)
    rates = {code: get_commission_rate(conn, code) for code in SERVICE_TYPES}

    c = ctx(request, "commissions", "کمیسیون‌های مستقیم", user)
    c.update({
        "eligible_employees": eligible_employees, "all_employees": all_employees, "history": history,
        "sel_employee_id": sel_employee_id, "rates": rates,
        "service_types": [(code, S.SERVICE_TYPE_DISPLAY.get(code, code)) for code in SERVICE_TYPES],
        "today_jalali_str": to_jalali_str(date.today()), "error": None, "saved": False,
    })
    return c


@router.get("/payroll/commissions")
def commissions_page(request: Request, user: CurrentUser = Depends(require_role("owner")), employee_id: int | None = None):
    conn = get_connection()
    try:
        c = _commissions_page_ctx(request, user, conn, employee_id)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "payroll_commissions.html", c)


@router.post("/payroll/commissions/new")
def commissions_new(
    request: Request, user: CurrentUser = Depends(require_role("owner")),
    employee_id: int = Form(...), service_type: str = Form(...),
    fee_rial: str = Form(...), service_date: str = Form(...), notes: str = Form(""),
):
    conn = get_connection()
    try:
        fee_rial_clean = fee_rial.strip().replace(",", "")
        try:
            fee_rial_val = int(fee_rial_clean)
        except ValueError:
            fee_rial_val = 0
        if fee_rial_val <= 0:
            c = _commissions_page_ctx(request, user, conn, employee_id)
            c["error"] = "مبلغ دریافتی باید عددی بزرگ‌تر از صفر باشد."
            return templates.TemplateResponse(request, "payroll_commissions.html", c)

        try:
            service_date_iso = parse_jalali_str(service_date).isoformat()
        except Exception:
            c = _commissions_page_ctx(request, user, conn, employee_id)
            c["error"] = "تاریخ را به فرم ۱۴۰۵/۰۳/۱۵ وارد کنید."
            return templates.TemplateResponse(request, "payroll_commissions.html", c)

        add_commission(
            conn,
            CommissionInput(
                employee_id=employee_id, service_type=service_type,
                fee_received=fee_rial_val, service_date=service_date_iso,
                notes=notes.strip() or None,
            ),
        )
        c = _commissions_page_ctx(request, user, conn, employee_id)
        c["saved"] = True
    finally:
        conn.close()
    return templates.TemplateResponse(request, "payroll_commissions.html", c)


@router.post("/payroll/commissions/{commission_id}/delete")
def commissions_delete(commission_id: int, user: CurrentUser = Depends(require_role("owner")), employee_id: int | None = Form(None)):
    conn = get_connection()
    try:
        delete_commission(conn, commission_id)
    finally:
        conn.close()
    url = f"/payroll/commissions?employee_id={employee_id}" if employee_id else "/payroll/commissions"
    return RedirectResponse(url=url, status_code=303)
