"""Users & Access management. Sibling to auth.py (which owns the `users`
table's login/session concerns) -- this is the same table's CRUD side, kept
here rather than a separate app/core module since the whole `users` table
has always lived in webapp/auth.py, not app/core (auth was never split out
desktop-app-style). Owner-only; replaces the old /coming-soon/users stub."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.core.employees import list_employees
from app.db.database import get_connection
from webapp.auth import ROLE_LABELS, CurrentUser, hash_password, require_role
from webapp.helpers import ctx, templates

router = APIRouter()

ROLES = ("owner", "accountant", "manager")


def _list_users(conn):
    return conn.execute(
        """SELECT u.id, u.username, u.role, u.active, e.full_name AS employee_name
           FROM users u LEFT JOIN employees e ON e.id = u.employee_id
           ORDER BY u.username"""
    ).fetchall()


def _users_page_ctx(request, user: CurrentUser, conn, error: str | None = None) -> dict:
    c = ctx(request, "users", "کاربران و دسترسی‌ها", user)
    c.update({
        "users": _list_users(conn),
        "employees": list_employees(conn, active_only=True),
        "roles": ROLES, "role_labels": ROLE_LABELS, "error": error, "saved": False,
    })
    return c


@router.get("/users")
def users_page(request: Request, user: CurrentUser = Depends(require_role("owner"))):
    conn = get_connection()
    try:
        c = _users_page_ctx(request, user, conn)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "users.html", c)


@router.post("/users/new")
def users_create(
    request: Request, user: CurrentUser = Depends(require_role("owner")),
    username: str = Form(...), password: str = Form(...), role: str = Form(...),
    employee_id: str = Form(""),
):
    username = username.strip()
    conn = get_connection()
    try:
        if not username or not password:
            c = _users_page_ctx(request, user, conn, error="نام کاربری و رمز عبور الزامی است.")
            return templates.TemplateResponse(request, "users.html", c)
        if role not in ROLES:
            c = _users_page_ctx(request, user, conn, error="نقش نامعتبر است.")
            return templates.TemplateResponse(request, "users.html", c)
        existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing is not None:
            c = _users_page_ctx(request, user, conn, error=f"نام کاربری «{username}» قبلاً استفاده شده است.")
            return templates.TemplateResponse(request, "users.html", c)

        conn.execute(
            "INSERT INTO users (username, password_hash, role, employee_id) VALUES (?, ?, ?, ?)",
            (username, hash_password(password), role, int(employee_id) if employee_id else None),
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/users", status_code=303)


@router.post("/users/{user_id}/toggle-active")
def users_toggle_active(user_id: int, request: Request, user: CurrentUser = Depends(require_role("owner"))):
    if user_id == user.id:
        conn = get_connection()
        try:
            c = _users_page_ctx(request, user, conn, error="امکان غیرفعال کردن حساب کاربری خودتان وجود ندارد.")
        finally:
            conn.close()
        return templates.TemplateResponse(request, "users.html", c)
    conn = get_connection()
    try:
        row = conn.execute("SELECT active FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise HTTPException(404)
        conn.execute("UPDATE users SET active = ? WHERE id = ?", (0 if row["active"] else 1, user_id))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/users", status_code=303)


@router.post("/users/{user_id}/delete")
def users_delete(user_id: int, request: Request, user: CurrentUser = Depends(require_role("owner"))):
    conn = get_connection()
    try:
        if user_id == user.id:
            c = _users_page_ctx(request, user, conn, error="امکان حذف حساب کاربری خودتان وجود ندارد.")
            return templates.TemplateResponse(request, "users.html", c)
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise HTTPException(404)
        try:
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            c = _users_page_ctx(
                request, user, conn,
                error="این کاربر سابقهٔ فعالیت (صورت‌حساب، پرداخت یا اجرای حقوق ثبت‌شده) دارد و قابل حذف نیست — به‌جایش غیرفعالش کنید.",
            )
            return templates.TemplateResponse(request, "users.html", c)
    finally:
        conn.close()
    return RedirectResponse(url="/users", status_code=303)


@router.post("/users/{user_id}/role")
def users_change_role(user_id: int, request: Request, user: CurrentUser = Depends(require_role("owner")), role: str = Form(...)):
    if role not in ROLES:
        raise HTTPException(400)
    conn = get_connection()
    try:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/users", status_code=303)


@router.post("/users/{user_id}/reset-password")
def users_reset_password(
    user_id: int, request: Request, user: CurrentUser = Depends(require_role("owner")),
    new_password: str = Form(...),
):
    conn = get_connection()
    try:
        if not new_password:
            c = _users_page_ctx(request, user, conn, error="رمز عبور جدید نمی‌تواند خالی باشد.")
            return templates.TemplateResponse(request, "users.html", c)
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new_password), user_id))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/users", status_code=303)
