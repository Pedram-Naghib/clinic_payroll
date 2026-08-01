"""nutrition_settlements.adjustment, nutrition_doctors.is_partner_self

Some months break the normal cash-flow assumption baked into the formula
(the clinic fronts expenses out of shared revenue, then the shares get
divided). E.g. a month where the partner personally paid every expense
instead of the clinic -- the entitlement math doesn't change, but the
actual amount to hand the partner does (her formulaic share plus whatever
she fronted). adjustment_amount is a manual, signed correction applied on
top of the partner's share when the settlement is saved; adjustment_note
records why.

is_partner_self: the nutrition partner sometimes personally performs the
service herself (she's an "operator" like any doctor, selectable on a
revenue row). When she is, there's no third-party doctor to carve a cut
out for -- her revenue should skip the doctor-share step entirely and go
straight into the clinic/partner 50-50 split. Since this system only ever
has one *active* operator at a time, this flag on that operator's row is
enough to select the right formula branch -- no need to apportion a mixed
month, because a mixed month can't happen under the current model.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-01 00:00:00.000000
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE nutrition_settlements
            ADD COLUMN adjustment_amount INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN adjustment_note TEXT
    """)
    op.execute("""
        ALTER TABLE nutrition_doctors
            ADD COLUMN is_partner_self INTEGER NOT NULL DEFAULT 0
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE nutrition_settlements
            DROP COLUMN adjustment_amount,
            DROP COLUMN adjustment_note
    """)
    op.execute("""
        ALTER TABLE nutrition_doctors
            DROP COLUMN is_partner_self
    """)
