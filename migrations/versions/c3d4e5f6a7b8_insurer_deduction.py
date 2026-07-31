"""insurance_invoices.insurer_deduction

"کسورات" isn't an unpaid balance -- it's the amount the insurance company
formally disallows/writes off from an invoice (their decision that the
clinic over-billed), separate from "not yet paid". Previously the app
conflated the two (deduction = amount - paid). This column lets the Owner
record the insurer's actual decided write-off; outstanding balance is then
amount - paid - insurer_deduction.

Revision ID: c3d4e5f6a7b8
Revises: b7c8d9e0f1a2
Create Date: 2026-07-24 13:00:00.000000
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "c3d4e5f6a7b8"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE insurance_invoices ADD COLUMN insurer_deduction INTEGER NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE insurance_invoices DROP COLUMN insurer_deduction")
