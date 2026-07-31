"""nutrition department module

Doctor/contract, revenue, expense, and monthly settlement tables for the
Nutrition Department financial management feature. Web-only, same shape as
the Insurance module (0878d89777a8) -- no desktop-app / schema.sql
counterpart needed.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-31 00:00:00.000000
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE nutrition_doctors (
            id             INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            full_name      TEXT NOT NULL,
            phone          TEXT,
            contract_start TEXT,
            contract_end   TEXT,
            active         INTEGER NOT NULL DEFAULT 0,
            notes          TEXT,
            created_at     TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)::text
        )
    """)

    op.execute("""
        CREATE TABLE nutrition_contracts (
            id                 INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            doctor_id          INTEGER NOT NULL UNIQUE REFERENCES nutrition_doctors(id),
            doctor_percentage  INTEGER NOT NULL DEFAULT 50 CHECK (doctor_percentage BETWEEN 0 AND 100),
            clinic_percentage  INTEGER NOT NULL DEFAULT 50 CHECK (clinic_percentage BETWEEN 0 AND 100),
            partner_percentage INTEGER NOT NULL DEFAULT 50 CHECK (partner_percentage BETWEEN 0 AND 100),
            notes              TEXT,
            created_at         TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)::text
        )
    """)

    op.execute("""
        CREATE TABLE nutrition_revenues (
            id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            date         TEXT NOT NULL,
            patient_name TEXT,
            service_type TEXT,
            amount       INTEGER NOT NULL CHECK (amount >= 0),
            doctor_id    INTEGER NOT NULL REFERENCES nutrition_doctors(id),
            created_by   INTEGER REFERENCES users(id),
            created_at   TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)::text
        )
    """)

    op.execute("""
        CREATE TABLE nutrition_expenses (
            id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            date          TEXT NOT NULL,
            title         TEXT NOT NULL,
            amount        INTEGER NOT NULL CHECK (amount >= 0),
            expense_type  TEXT NOT NULL CHECK (expense_type IN ('consumable', 'non_consumable')),
            created_by    INTEGER REFERENCES users(id),
            created_at    TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)::text
        )
    """)

    op.execute("""
        CREATE TABLE nutrition_settlements (
            id                       INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            period_start             TEXT NOT NULL,
            period_end               TEXT NOT NULL,
            doctor_id                INTEGER NOT NULL REFERENCES nutrition_doctors(id),
            gross_revenue            INTEGER NOT NULL,
            consumable_expenses      INTEGER NOT NULL,
            non_consumable_expenses  INTEGER NOT NULL,
            doctor_share             INTEGER NOT NULL,
            clinic_share             INTEGER NOT NULL,
            partner_share            INTEGER NOT NULL,
            generated_by             INTEGER REFERENCES users(id),
            generated_at             TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)::text,
            UNIQUE (period_start, period_end)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE nutrition_settlements")
    op.execute("DROP TABLE nutrition_expenses")
    op.execute("DROP TABLE nutrition_revenues")
    op.execute("DROP TABLE nutrition_contracts")
    op.execute("DROP TABLE nutrition_doctors")
