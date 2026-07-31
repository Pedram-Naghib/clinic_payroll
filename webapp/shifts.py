"""Shift schedule module routes: manual M/E/N grid, shift-window definitions,
and swap suggestions. Owner-only, same as Employees/Attendance/Leave."""
from __future__ import annotations
from datetime import timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.core import shifts as shifts_core
from app.core.employees import list_employees
from app.db.database import get_connection
from webapp.auth import CurrentUser, require_role
from webapp.helpers import ctx, templates
from webapp.payroll import PERSIAN_MONTHS, YEAR_RANGE, _default_period, _jalali_period

router = APIRouter()


def _month_days(year: int, month: int) -> list[tuple[int, str]]:
    """[(jalali day number, ISO Gregorian work_date), ...] for the whole month."""
    period_start, period_end = _jalali_period(year, month)
    day_count = (period_end - period_start).days
    return [(d + 1, (period_start + timedelta(days=d)).date().isoformat()) for d in range(day_count)]


def _shifts_page_ctx(request: Request, user: CurrentUser, conn, year: int, month: int) -> dict:
    days = _month_days(year, month)
    period_start_iso, period_end_iso = days[0][1], (
        _jalali_period(year, month)[1].date().isoformat()
    )
    employees = [e for e in list_employees(conn, active_only=True) if not e["is_exempt_from_shifts"]]
    schedule = shifts_core.get_schedule(conn, period_start_iso, period_end_iso)
    suggestions = shifts_core.list_swap_suggestions(conn, period_start_iso, period_end_iso)

    c = ctx(request, "shifts", "برنامهٔ شیفت", user)
    c.update({
        "sel_year": year, "sel_month": month,
        "year_range": YEAR_RANGE, "jalali_months": list(enumerate(PERSIAN_MONTHS, start=1)),
        "days": days, "employees": employees, "schedule": schedule,
        "shift_defs": shifts_core.get_shift_definitions(conn),
        "suggestions": suggestions, "saved": False, "generated_count": None,
    })
    return c


@router.get("/payroll/shifts")
def shifts_page(request: Request, user: CurrentUser = Depends(require_role("owner", "manager")), year: int | None = None, month: int | None = None):
    if year is None or month is None:
        year, month = _default_period()
    conn = get_connection()
    try:
        c = _shifts_page_ctx(request, user, conn, year, month)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "payroll_shifts.html", c)


@router.post("/payroll/shifts/save")
async def shifts_save(request: Request, user: CurrentUser = Depends(require_role("owner", "manager"))):
    form = await request.form()
    year = int(form["year"])
    month = int(form["month"])
    days = _month_days(year, month)
    conn = get_connection()
    try:
        employees = [e for e in list_employees(conn, active_only=True) if not e["is_exempt_from_shifts"]]
        entries = []
        for emp in employees:
            for _, work_date in days:
                key = f"shift__{emp['id']}__{work_date}"
                if key in form:
                    entries.append((emp["id"], work_date, form[key]))
        shifts_core.save_month_schedule(conn, entries, user.id)
        c = _shifts_page_ctx(request, user, conn, year, month)
    finally:
        conn.close()
    c["saved"] = True
    return templates.TemplateResponse(request, "payroll_shifts.html", c)


@router.post("/payroll/shifts/definitions/save")
async def shift_definitions_save(request: Request, user: CurrentUser = Depends(require_role("owner", "manager"))):
    form = await request.form()
    year = int(form.get("year") or 0)
    month = int(form.get("month") or 0)
    if not (year and month):
        year, month = _default_period()
    conn = get_connection()
    try:
        for row in shifts_core.get_shift_definitions(conn):
            code = row["code"]
            shifts_core.update_shift_definition(
                conn, code,
                form.get(f"label__{code}", row["label"]),
                form.get(f"start__{code}", row["start_time"]),
                form.get(f"end__{code}", row["end_time"]),
                form.get(f"crosses__{code}") is not None,
            )
        c = _shifts_page_ctx(request, user, conn, year, month)
    finally:
        conn.close()
    c["saved"] = True
    return templates.TemplateResponse(request, "payroll_shifts.html", c)


@router.post("/payroll/shifts/swaps/generate")
def swaps_generate(
    request: Request, user: CurrentUser = Depends(require_role("owner", "manager")),
    year: int = Form(...), month: int = Form(...),
):
    period_start, period_end = _jalali_period(year, month)
    conn = get_connection()
    try:
        count = shifts_core.generate_swap_suggestions(conn, period_start.date().isoformat(), period_end.date().isoformat())
        c = _shifts_page_ctx(request, user, conn, year, month)
    finally:
        conn.close()
    c["generated_count"] = count
    return templates.TemplateResponse(request, "payroll_shifts.html", c)


@router.post("/payroll/shifts/swaps/{suggestion_id}/decide")
def swaps_decide(
    suggestion_id: int, user: CurrentUser = Depends(require_role("owner", "manager")),
    decision: str = Form("approve"), year: int = Form(...), month: int = Form(...),
):
    if decision not in ("approve", "reject"):
        raise HTTPException(400)
    conn = get_connection()
    try:
        shifts_core.decide_swap_suggestion(conn, suggestion_id, approve=(decision == "approve"), user_id=user.id)
    finally:
        conn.close()
    return RedirectResponse(url=f"/payroll/shifts?year={year}&month={month}", status_code=303)
