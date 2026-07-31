"""add manager role

Third role: 'manager' (مدیر داخلی) — restricted to /payroll/shifts only.
'accountant' becomes insurance-only (loses its former read-only view of
Payroll Runs, per Pedram's updated access-level spec).

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-07-24 12:00:00.000000
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "b7c8d9e0f1a2"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT users_role_check")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_role_check "
        "CHECK (role IN ('owner', 'accountant', 'manager'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT users_role_check")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_role_check "
        "CHECK (role IN ('owner', 'accountant'))"
    )
