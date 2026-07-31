"""Session-based auth backed by the `users` table. A signed cookie carries
the session -- no server-side session store table, which is the right size
for a 4-5 person clinic tool (nothing to garbage-collect, no extra table).
"""
from __future__ import annotations
import logging
import os
from dataclasses import dataclass

import bcrypt
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.db.database import get_connection
from webapp.rate_limit import limiter

logger = logging.getLogger("clinic_payroll")

SESSION_COOKIE = "session"
SESSION_MAX_AGE = 60 * 60 * 24 * 14  # 14 days

ROLE_LABELS = {"owner": "دسترسی کامل", "accountant": "حسابدار", "manager": "مدیر داخلی"}

# Where each role lands right after login. Owner gets the full dashboard;
# accountant (insurance-only) and manager (shifts-only) skip straight to the
# one section they're allowed to see -- "/" is owner-only and would 403 them.
ROLE_HOME = {"manager": "/payroll/shifts", "accountant": "/insurance/invoices"}
DEFAULT_HOME = "/"

templates = Jinja2Templates(directory="webapp/templates")
router = APIRouter()


def _serializer() -> URLSafeTimedSerializer:
    secret = os.environ.get("SESSION_SECRET")
    if not secret:
        raise RuntimeError("SESSION_SECRET env var is not set")
    return URLSafeTimedSerializer(secret, salt="clinic-session")


@dataclass
class CurrentUser:
    id: int
    username: str
    role: str  # 'owner' | 'accountant' | 'manager'
    full_name: str

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)

    @property
    def initials(self) -> str:
        parts = self.full_name.split()
        return " ".join(p[0] for p in parts[:2]) if parts else self.username[:2]


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def _load_user_row(username: str):
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT u.id, u.username, u.password_hash, u.role, u.active,
                   COALESCE(e.full_name, u.username) AS full_name
            FROM users u
            LEFT JOIN employees e ON e.id = u.employee_id
            WHERE u.username = ?
            """,
            (username,),
        ).fetchone()
    finally:
        conn.close()


def authenticate(username: str, password: str) -> CurrentUser | None:
    row = _load_user_row(username)
    if row is None or not row["active"] or not verify_password(password, row["password_hash"]):
        return None
    return CurrentUser(id=row["id"], username=row["username"], role=row["role"], full_name=row["full_name"])


def set_session_cookie(response, request: Request, user: CurrentUser) -> None:
    token = _serializer().dumps({"id": user.id, "username": user.username})
    # secure=False only happens over plain http (local dev on :3000); in prod,
    # uvicorn's --proxy-headers trusts Caddy's X-Forwarded-Proto so this
    # correctly reads "https" even though Caddy talks to uvicorn over plain
    # HTTP internally.
    response.set_cookie(
        SESSION_COOKIE, token, max_age=SESSION_MAX_AGE, httponly=True, samesite="lax",
        secure=request.url.scheme == "https",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE)


def get_current_user(request: Request) -> CurrentUser:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    try:
        data = _serializer().loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        raise HTTPException(status_code=303, headers={"Location": "/login"})

    # Re-derive from the DB every request (not from the cookie payload) so a
    # role change or deactivation takes effect immediately, not after 14 days.
    row = _load_user_row(data["username"])
    if row is None or not row["active"]:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return CurrentUser(id=row["id"], username=row["username"], role=row["role"], full_name=row["full_name"])


def require_role(*roles: str):
    """Dependency factory. No roles given = any logged-in user."""
    def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if roles and user.role not in roles:
            raise HTTPException(status_code=403, detail="دسترسی مجاز نیست")
        return user
    return dependency


def _active_login_options() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT u.username, COALESCE(e.full_name, u.username) AS display_name
               FROM users u LEFT JOIN employees e ON e.id = u.employee_id
               WHERE u.active = 1 ORDER BY display_name"""
        ).fetchall()
        return [{"username": r["username"], "display_name": r["display_name"]} for r in rows]
    finally:
        conn.close()


@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None, "login_options": _active_login_options()})


@router.post("/login")
@limiter.limit("5/minute")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    user = authenticate(username, password)
    if user is None:
        logger.warning("failed login attempt: username=%r ip=%s", username, request.client.host if request.client else "?")
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "نام کاربری یا رمز عبور اشتباه است", "login_options": _active_login_options()},
            status_code=401,
        )
    response = RedirectResponse(url=ROLE_HOME.get(user.role, DEFAULT_HOME), status_code=303)
    set_session_cookie(response, request, user)
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    clear_session_cookie(response)
    return response
