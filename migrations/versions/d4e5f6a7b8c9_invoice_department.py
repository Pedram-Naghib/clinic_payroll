"""insurance_invoices.department

Insurers don't all bill the same way: some pay the clinic, physiotherapy,
and lab invoices separately, others pay two of the three together and the
third alone, in varying combinations. That's already handled by the
existing many-to-many invoice<->payment matching (one payment can be split
across several invoices). What was missing was a way to tell which
department each invoice belongs to, so invoices/reports can be read and
filtered per department.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-28 10:00:00.000000
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """ALTER TABLE insurance_invoices ADD COLUMN department TEXT NOT NULL DEFAULT 'clinic'
               CHECK (department IN ('clinic', 'physio', 'lab'))"""
    )


def downgrade() -> None:
    op.execute("ALTER TABLE insurance_invoices DROP COLUMN department")
