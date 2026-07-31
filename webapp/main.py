import logging

from fastapi import Depends, FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.employees import list_employees
from app.core.insurance import invoices_with_status, list_payments, suggest_matches_for_payment
from app.core.payroll_runs import find_existing_run, get_payroll_run_line_items
from app.db.database import get_connection
from webapp import auth, insurance, nutrition, payroll, shifts, users
from webapp.auth import CurrentUser, require_role
from webapp.helpers import ctx, templates
from webapp.payroll import PERSIAN_MONTHS, _default_period, _jalali_period
from webapp.rate_limit import limiter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("clinic_payroll")

# docs_url/redoc_url/openapi_url off: this is a server-rendered internal
# tool with no external API consumers, so a public schema of every route
# and model field name (employee/payroll data) is pure reconnaissance
# surface with no upside.
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.mount("/static", StaticFiles(directory="webapp/static"), name="static")
app.include_router(auth.router)
app.include_router(payroll.router)
app.include_router(shifts.router)
app.include_router(insurance.router)
app.include_router(nutrition.router)
app.include_router(users.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Full traceback goes to the server log (docker logs); the browser only
    # ever sees a generic message -- never exc's str() or a stack trace.
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return PlainTextResponse("خطای داخلی سرور رخ داده است.", status_code=500)

@app.get("/")
def dashboard(request: Request, user: CurrentUser = Depends(require_role("owner"))):
    year, month = _default_period()
    period_start, period_end = _jalali_period(year, month)

    conn = get_connection()
    try:
        active_employees = len(list_employees(conn, active_only=True))

        run = find_existing_run(conn, period_start.date().isoformat(), period_end.date().isoformat())
        month_payroll_total = sum(li["total_pay"] for li in get_payroll_run_line_items(conn, run["id"])) if run else 0

        invoices = invoices_with_status(conn)
        open_invoices = [i for i in invoices if i["outstanding"] > 0]
        outstanding_balance = sum(i["outstanding"] for i in invoices)
        latest_invoices = invoices[:4]

        suggestions = []
        for p in list_payments(conn, unmatched_only=True):
            top = suggest_matches_for_payment(conn, p["id"], top_n=1)
            if top:
                suggestions.append({"payment": p, "invoice": top[0]})
        suggestions.sort(key=lambda s: s["invoice"]["score"], reverse=True)
    finally:
        conn.close()

    c = ctx(request, "dashboard", "داشبورد", user)
    c.update({
        "kpi_active_employees": active_employees,
        "kpi_month_payroll_total": month_payroll_total,
        "kpi_month_label": PERSIAN_MONTHS[month - 1],
        "kpi_open_invoices": len(open_invoices),
        "kpi_outstanding_balance": outstanding_balance,
        "latest_invoices": latest_invoices,
        "match_suggestions": suggestions[:2],
    })
    return templates.TemplateResponse(request, "dashboard.html", c)
