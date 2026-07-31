"""initial schema

Port of app/db/schema.sql (as it actually lives in production, including the
ad-hoc ALTER TABLEs from app/db/migrations/migrate_v2_*.py and
migrate_v3_*.py -- schema.sql itself is stale for leave_requests and
payroll_line_items) to Postgres, plus brand-new tables for the Insurance
module.

Type choices, and why:
  - id columns: INTEGER GENERATED ALWAYS AS IDENTITY (SQL-standard identity
    column) instead of SERIAL -- same practical effect, modern spelling.
  - REAL -> DOUBLE PRECISION: SQLite's REAL is always 8-byte; Postgres's REAL
    is 4-byte single precision. DOUBLE PRECISION is the accurate match for
    hour/day-fraction columns like vacation_balance_days.
  - 0/1 flag columns (is_married, active, confirmed, ...) stay INTEGER, not
    BOOLEAN -- app/core/*.py reads them with Python's bool()/int(), which
    behaves identically either way, and this keeps the port mechanical.
  - TEXT date/datetime columns (work_date, punch_datetime, period_start...)
    stay TEXT -- app/core always writes these via .isoformat()/.strftime(),
    never relies on a DB type, and several places do string comparison
    (work_date >= ?) that a native DATE/TIMESTAMP column would still support
    but isn't worth the risk of changing for this port.
  - datetime('now') defaults -> (CURRENT_TIMESTAMP)::text -- these are
    write-once audit columns (created_at/updated_at/generated_at/...),
    nothing in app/core parses their exact format, only orders by them.

Revision ID: 0878d89777a8
Revises:
Create Date: 2026-07-23 19:03:30.950745

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0878d89777a8'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE employees (
            id                    INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            full_name             TEXT NOT NULL,
            device_enroll_no      TEXT,
            employment_type       TEXT NOT NULL CHECK (employment_type IN ('insured', 'non_insured')),
            is_exempt_from_shifts INTEGER NOT NULL DEFAULT 0,
            fixed_monthly_salary  INTEGER,
            base_hourly_rate      INTEGER,
            is_married            INTEGER DEFAULT 0,
            number_of_children    INTEGER DEFAULT 0,
            seniority_allowance   INTEGER DEFAULT 0,
            vacation_balance_days DOUBLE PRECISION DEFAULT 0,
            active                INTEGER NOT NULL DEFAULT 1,
            notes                 TEXT,
            created_at            TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)::text
        )
    """)

    op.execute("""
        CREATE TABLE roles (
            id   INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        )
    """)

    op.execute("""
        CREATE TABLE users (
            id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            username      TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role          TEXT NOT NULL CHECK (role IN ('owner', 'accountant')),
            employee_id   INTEGER REFERENCES employees(id),
            active        INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)::text
        )
    """)

    op.execute("""
        CREATE TABLE employee_roles (
            employee_id INTEGER NOT NULL REFERENCES employees(id),
            role_id     INTEGER NOT NULL REFERENCES roles(id),
            PRIMARY KEY (employee_id, role_id)
        )
    """)

    op.execute("""
        CREATE TABLE system_config (
            key         TEXT PRIMARY KEY,
            value       TEXT NOT NULL,
            value_type  TEXT NOT NULL DEFAULT 'int' CHECK (value_type IN ('int','float','text')),
            label       TEXT NOT NULL,
            description TEXT,
            category    TEXT DEFAULT 'general',
            updated_at  TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)::text
        )
    """)

    op.execute("""
        CREATE TABLE allowance_definitions (
            code                          TEXT PRIMARY KEY,
            label                         TEXT NOT NULL,
            applies_to_insured            INTEGER NOT NULL DEFAULT 0,
            applies_to_non_insured        INTEGER NOT NULL DEFAULT 0,
            enabled                       INTEGER NOT NULL DEFAULT 1,
            amount_type                   TEXT NOT NULL CHECK (amount_type IN (
                                               'config_flat',
                                               'config_per_child',
                                               'config_per_hour',
                                               'employee_field_flat',
                                               'employee_field_per_hour'
                                           )),
            config_key                    TEXT,
            employee_field                TEXT,
            condition_employee_field      TEXT,
            excluded_from_insurance_base  INTEGER NOT NULL DEFAULT 0,
            sort_order                    INTEGER DEFAULT 0,
            updated_at                    TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)::text
        )
    """)

    op.execute("""
        CREATE TABLE shift_definitions (
            code             TEXT PRIMARY KEY,
            label            TEXT NOT NULL,
            start_time       TEXT NOT NULL,
            end_time         TEXT NOT NULL,
            crosses_midnight INTEGER NOT NULL DEFAULT 0
        )
    """)

    op.execute("""
        CREATE TABLE planned_shifts (
            id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            employee_id   INTEGER NOT NULL REFERENCES employees(id),
            work_date     TEXT NOT NULL,
            shift_code    TEXT,
            planned_start TEXT,
            planned_end   TEXT,
            created_by    INTEGER REFERENCES users(id),
            updated_at    TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)::text,
            UNIQUE(employee_id, work_date)
        )
    """)

    op.execute("""
        CREATE TABLE raw_punches (
            id                 INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            device_enroll_no   TEXT NOT NULL,
            employee_id        INTEGER REFERENCES employees(id),
            punch_datetime     TEXT NOT NULL,
            raw_mode           TEXT,
            raw_inout_flag     TEXT,
            inferred_direction TEXT CHECK (inferred_direction IN ('IN','OUT')),
            source_file        TEXT,
            imported_at        TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)::text,
            UNIQUE(device_enroll_no, punch_datetime, raw_mode)
        )
    """)
    op.execute("CREATE INDEX idx_raw_punches_emp_date ON raw_punches (employee_id, punch_datetime)")

    op.execute("""
        CREATE TABLE daily_attendance (
            id                  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            employee_id         INTEGER NOT NULL REFERENCES employees(id),
            work_date           TEXT NOT NULL,
            first_in            TEXT,
            last_out            TEXT,
            worked_hours        DOUBLE PRECISION DEFAULT 0,
            planned_shift_code  TEXT,
            status              TEXT,
            manager_reviewed    INTEGER NOT NULL DEFAULT 0,
            manager_note        TEXT,
            UNIQUE(employee_id, work_date)
        )
    """)

    op.execute("""
        CREATE TABLE shift_swap_suggestions (
            id                   INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            work_date            TEXT NOT NULL,
            absent_employee_id   INTEGER NOT NULL REFERENCES employees(id),
            covering_employee_id INTEGER NOT NULL REFERENCES employees(id),
            planned_shift_code   TEXT,
            covering_punch_in    TEXT,
            covering_punch_out   TEXT,
            status               TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
            decided_by           INTEGER REFERENCES users(id),
            decided_at           TEXT
        )
    """)

    op.execute("""
        CREATE TABLE payroll_runs (
            id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            period_start  TEXT NOT NULL,
            period_end    TEXT NOT NULL,
            generated_at  TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)::text,
            generated_by  INTEGER REFERENCES users(id),
            notes         TEXT
        )
    """)

    # leave_requests as it actually exists in production today: schema.sql's
    # original columns plus notes/source/payroll_run_id, added later by
    # app/db/migrations/migrate_v3_leave_payslip.py.
    op.execute("""
        CREATE TABLE leave_requests (
            id                  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            employee_id         INTEGER NOT NULL REFERENCES employees(id),
            leave_type          TEXT NOT NULL CHECK (leave_type IN ('vacation','medical')),
            start_date          TEXT NOT NULL,
            end_date            TEXT NOT NULL,
            days_count          DOUBLE PRECISION NOT NULL,
            status              TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
            paid_by_clinic_days DOUBLE PRECISION DEFAULT 0,
            unpaid_days         DOUBLE PRECISION DEFAULT 0,
            requested_at        TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)::text,
            decided_by          INTEGER REFERENCES users(id),
            notes               TEXT,
            source              TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','auto_shortfall')),
            payroll_run_id      INTEGER REFERENCES payroll_runs(id)
        )
    """)

    # payroll_line_items likewise includes leave_days_covered, added later by
    # migrate_v3_leave_payslip.py -- not present in the stale schema.sql.
    op.execute("""
        CREATE TABLE payroll_line_items (
            id                             INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            payroll_run_id                 INTEGER NOT NULL REFERENCES payroll_runs(id),
            employee_id                    INTEGER NOT NULL REFERENCES employees(id),
            total_hours                    DOUBLE PRECISION,
            overtime_hours                 DOUBLE PRECISION DEFAULT 0,
            holiday_hours                  DOUBLE PRECISION DEFAULT 0,
            base_pay                       INTEGER DEFAULT 0,
            overtime_pay                   INTEGER DEFAULT 0,
            holiday_premium_pay            INTEGER DEFAULT 0,
            housing_allowance              INTEGER DEFAULT 0,
            food_allowance                 INTEGER DEFAULT 0,
            child_allowance                INTEGER DEFAULT 0,
            seniority_allowance            INTEGER DEFAULT 0,
            family_allowance               INTEGER DEFAULT 0,
            under_hours_deduction          INTEGER DEFAULT 0,
            insurance_deduction            INTEGER DEFAULT 0,
            unpaid_medical_leave_deduction INTEGER DEFAULT 0,
            total_pay                      INTEGER DEFAULT 0,
            breakdown_json                 TEXT,
            leave_days_covered             DOUBLE PRECISION DEFAULT 0
        )
    """)

    op.execute("""
        CREATE TABLE direct_commissions (
            id                 INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            employee_id        INTEGER NOT NULL REFERENCES employees(id),
            service_type       TEXT NOT NULL CHECK (service_type IN ('piercing','fast_blood_test')),
            fee_received       INTEGER NOT NULL,
            commission_rate    DOUBLE PRECISION NOT NULL,
            commission_amount  INTEGER NOT NULL,
            service_date       TEXT NOT NULL,
            notes              TEXT,
            recorded_by        INTEGER REFERENCES users(id),
            created_at         TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)::text
        )
    """)

    op.execute("""
        CREATE TABLE iranian_holidays (
            work_date TEXT PRIMARY KEY,
            label     TEXT NOT NULL,
            source    TEXT NOT NULL CHECK (source IN ('computed_fixed', 'computed_lunar_estimate', 'manual')),
            confirmed INTEGER NOT NULL DEFAULT 1
        )
    """)

    # ------------------------------------------------------------------
    # Insurance module (new)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE insurance_companies (
            id                   INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name                 TEXT UNIQUE NOT NULL,
            contact_person       TEXT,
            phone                TEXT,
            contract_start_date  TEXT,
            active               INTEGER NOT NULL DEFAULT 1,
            notes                TEXT,
            created_at           TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)::text
        )
    """)

    op.execute("""
        CREATE TABLE insurance_invoices (
            id             INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            company_id     INTEGER NOT NULL REFERENCES insurance_companies(id),
            invoice_number TEXT,
            period_start   TEXT NOT NULL,
            period_end     TEXT NOT NULL,
            amount         INTEGER NOT NULL,
            issued_date    TEXT,
            notes          TEXT,
            created_by     INTEGER REFERENCES users(id),
            created_at     TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)::text
        )
    """)

    op.execute("""
        CREATE TABLE insurance_payments (
            id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            company_id    INTEGER NOT NULL REFERENCES insurance_companies(id),
            amount        INTEGER NOT NULL,
            received_date TEXT NOT NULL,
            reference_no  TEXT,
            notes         TEXT,
            created_by    INTEGER REFERENCES users(id),
            created_at    TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)::text
        )
    """)

    # Many-to-many: a payment may be split across invoices, an invoice may
    # receive multiple payments. allocated_amount lets the reconciliation
    # engine (and manual confirmation) record partial matches, not just
    # whole-payment-to-whole-invoice links. confidence_score is set by the
    # suggestion engine and left NULL for purely manual matches.
    op.execute("""
        CREATE TABLE invoice_payment_matches (
            id                INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            invoice_id        INTEGER NOT NULL REFERENCES insurance_invoices(id),
            payment_id        INTEGER NOT NULL REFERENCES insurance_payments(id),
            allocated_amount  INTEGER NOT NULL,
            confidence_score  DOUBLE PRECISION,
            status            TEXT NOT NULL DEFAULT 'confirmed' CHECK (status IN ('suggested','confirmed')),
            matched_by        INTEGER REFERENCES users(id),
            matched_at        TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)::text,
            UNIQUE(invoice_id, payment_id)
        )
    """)

    # ------------------------------------------------------------------
    # Seed data -- mirrors app/db/database.py's init_db() defaults exactly,
    # so a fresh Postgres install behaves the same as a fresh SQLite one.
    # No user accounts here -- credentials don't belong in a migration.
    # ------------------------------------------------------------------
    op.execute("""
        INSERT INTO shift_definitions (code, label, start_time, end_time, crosses_midnight) VALUES
            ('M', 'Morning', '08:00', '14:00', 0),
            ('E', 'Evening', '14:00', '20:00', 0),
            ('N', 'Night',   '20:00', '08:00', 1)
    """)

    op.execute("""
        INSERT INTO system_config (key, value, value_type, label, description, category) VALUES
            ('base_monthly_hours', '192', 'int', 'Base Monthly Hours', 'Standard hours/month for insured staff', 'payroll'),
            ('overtime_premium_pct', '40', 'int', 'Overtime Premium (%)', 'Extra % over base hourly rate for hours worked beyond base_monthly_hours', 'payroll'),
            ('holiday_premium_pct', '30', 'int', 'Holiday Premium (%)', 'Extra % over base hourly rate for hours worked on an official holiday date -- both employment types, but never for night (''N'') shifts', 'payroll'),
            ('insurance_deduction_pct', '7', 'int', 'Insurance Deduction (%)', 'Deducted from insured staff''s total earnings, excluding child allowance & overtime', 'payroll'),
            ('fixed_marriage_allowance', '0', 'int', 'Marriage Allowance (fixed)', 'Flat amount added if employee.is_married = 1', 'allowances'),
            ('fixed_child_allowance', '0', 'int', 'Child Allowance (per child)', 'Multiplied by employee.number_of_children', 'allowances'),
            ('fixed_housing_allowance', '30000000', 'int', 'Housing Allowance (fixed, insured)', 'Flat monthly amount for all insured staff -- one global rate, edit here instead of per employee', 'allowances'),
            ('fixed_food_allowance', '22000000', 'int', 'Food Allowance (fixed, insured)', 'Flat monthly amount for all insured staff -- one global rate, edit here instead of per employee', 'allowances'),
            ('housing_allowance_per_hour', '156250', 'int', 'Housing Allowance (per hour, non-insured)', 'Multiplied by worked hours for all non-insured staff -- one global rate', 'allowances'),
            ('food_allowance_per_hour', '114500', 'int', 'Food Allowance (per hour, non-insured)', 'Multiplied by worked hours for all non-insured staff -- one global rate', 'allowances'),
            ('medical_leave_paid_days_cap', '3', 'int', 'Medical Leave Paid Days/Month', 'Days/month covered by clinic before becoming unpaid', 'leave'),
            ('piercing_commission_pct', '30', 'int', 'Piercing Commission (%)', 'Direct commission rate for piercing service', 'commissions'),
            ('fast_blood_test_commission_pct', '20', 'int', 'Fast Blood Test Commission (%)', 'Direct commission rate for fast blood test service', 'commissions')
    """)

    op.execute("""
        INSERT INTO roles (name) VALUES ('بهیار'), ('پذیرش')
    """)

    op.execute("""
        INSERT INTO allowance_definitions
            (code, label, applies_to_insured, applies_to_non_insured, enabled, amount_type,
             config_key, employee_field, condition_employee_field, excluded_from_insurance_base, sort_order)
        VALUES
            ('marriage', 'Marriage Allowance', 1, 0, 1, 'config_flat', 'fixed_marriage_allowance', NULL, 'is_married', 0, 10),
            ('child', 'Child Allowance', 1, 0, 1, 'config_per_child', 'fixed_child_allowance', NULL, NULL, 1, 20),
            ('housing_fixed', 'Housing Allowance (fixed)', 1, 0, 1, 'config_flat', 'fixed_housing_allowance', NULL, NULL, 0, 30),
            ('food_fixed', 'Food Allowance (fixed)', 1, 0, 1, 'config_flat', 'fixed_food_allowance', NULL, NULL, 0, 40),
            ('seniority_fixed', 'Seniority Allowance', 1, 0, 1, 'employee_field_flat', NULL, 'seniority_allowance', NULL, 0, 50),
            ('housing_hourly', 'Housing Allowance (hourly)', 0, 1, 1, 'config_per_hour', 'housing_allowance_per_hour', NULL, NULL, 0, 60),
            ('food_hourly', 'Food Allowance (hourly)', 0, 1, 1, 'config_per_hour', 'food_allowance_per_hour', NULL, NULL, 0, 70)
    """)


def downgrade() -> None:
    for table in [
        "invoice_payment_matches", "insurance_payments", "insurance_invoices", "insurance_companies",
        "iranian_holidays", "direct_commissions", "payroll_line_items", "leave_requests", "payroll_runs",
        "shift_swap_suggestions", "daily_attendance", "raw_punches", "planned_shifts", "shift_definitions",
        "allowance_definitions", "system_config", "employee_roles", "users", "roles", "employees",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
