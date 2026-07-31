"""Shared bits between webapp route modules -- one Jinja2 environment, one
page-context builder, so every module renders through the same base.html
shell with consistent role/nav/user info."""
from datetime import date

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.core.jalali import to_jalali_str
from webapp.auth import CurrentUser

templates = Jinja2Templates(directory="webapp/templates")


def _jalali_filter(iso_date: str | None) -> str:
    """Template filter: {{ some_iso_date | jalali }} -- every ISO Gregorian
    date column (period_start, received_date, ...) gets converted at render
    time instead of in every route, since Row objects from app.core queries
    are immutable and can't be pre-converted in place."""
    if not iso_date:
        return ""
    return to_jalali_str(date.fromisoformat(iso_date))


templates.env.filters["jalali"] = _jalali_filter


def ctx(request: Request, active: str, page_title: str, user: CurrentUser) -> dict:
    return {
        "request": request, "active": active, "page_title": page_title,
        "role": user.role, "role_label": user.role_label,
        "user_name": user.full_name, "user_initials": user.initials,
    }
