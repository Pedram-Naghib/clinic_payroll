"""
Job Roles (Behyar, Paziresh, etc.) — dynamic, owner-defined, many-to-many.

Role names are NEVER hardcoded in Python. They live in the `roles` table and
are typed freely by the manager in the Employees tab; an employee can hold
any number of roles at once via the `employee_roles` junction table.

The starting rows 'Behyar' and 'Paziresh' are seeded once in
app/db/database.py (INSERT OR IGNORE, same pattern as shift_definitions /
system_config defaults) purely as a convenience starting point -- the Owner
can rename, add, or remove roles freely from then on with no code change.
"""

from __future__ import annotations
import sqlite3


def list_all_roles(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM roles ORDER BY name").fetchall()
    return [r["name"] for r in rows]


def get_or_create_role(conn: sqlite3.Connection, name: str) -> int:
    name = name.strip()
    conn.execute("INSERT OR IGNORE INTO roles (name) VALUES (?)", (name,))
    row = conn.execute("SELECT id FROM roles WHERE name = ?", (name,)).fetchone()
    return row["id"]


def get_employee_roles(conn: sqlite3.Connection, employee_id: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT r.name FROM roles r
        JOIN employee_roles er ON er.role_id = r.id
        WHERE er.employee_id = ?
        ORDER BY r.name
        """,
        (employee_id,),
    ).fetchall()
    return [r["name"] for r in rows]


def get_employee_roles_map(conn: sqlite3.Connection) -> dict[int, list[str]]:
    """All employee_id -> [role names] in one query, for table rendering."""
    rows = conn.execute(
        """
        SELECT er.employee_id, r.name FROM employee_roles er
        JOIN roles r ON r.id = er.role_id
        ORDER BY r.name
        """
    ).fetchall()
    result: dict[int, list[str]] = {}
    for row in rows:
        result.setdefault(row["employee_id"], []).append(row["name"])
    return result


def set_employee_roles(conn: sqlite3.Connection, employee_id: int, role_names: list[str]) -> None:
    """Replaces this employee's full role set. Any new role names are created
    on the fly (get_or_create_role) -- this is the one place free-typed role
    text from the UI turns into rows, matching the "type to define" requirement."""
    conn.execute("DELETE FROM employee_roles WHERE employee_id = ?", (employee_id,))
    seen = set()
    for raw_name in role_names:
        name = raw_name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        role_id = get_or_create_role(conn, name)
        conn.execute(
            "INSERT OR IGNORE INTO employee_roles (employee_id, role_id) VALUES (?, ?)",
            (employee_id, role_id),
        )
    conn.commit()


def get_employees_with_role(
    conn: sqlite3.Connection, role_name: str, active_only: bool = True
) -> list[sqlite3.Row]:
    """Exact (case-sensitive) match on role name, e.g. for filtering the
    Commissions tab dropdown to current 'Behyar' holders."""
    q = """
        SELECT e.* FROM employees e
        JOIN employee_roles er ON er.employee_id = e.id
        JOIN roles r ON r.id = er.role_id
        WHERE r.name = ?
    """
    params: list = [role_name]
    if active_only:
        q += " AND e.active = 1"
    q += " ORDER BY e.full_name"
    return conn.execute(q, params).fetchall()