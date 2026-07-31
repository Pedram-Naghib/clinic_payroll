"""daily_attendance.source (device vs manual entry)

Adds a `source` column to `daily_attendance` so a manually-entered row (the
Owner overriding/filling in attendance they don't trust the device for) can
survive attendance_engine.persist_daily_attendance()'s per-employee/period
DELETE-then-reinsert, which previously had no way to distinguish "recomputed
from punches" from "the Owner typed this in by hand" and would silently wipe
manual entries on the next "Compute attendance" click.

Revision ID: a1b2c3d4e5f6
Revises: 0878d89777a8
Create Date: 2026-07-24 10:00:00.000000
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "0878d89777a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE daily_attendance ADD COLUMN source TEXT NOT NULL DEFAULT 'device'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE daily_attendance DROP COLUMN source")
