"""
Database bootstrap for the Clinic Payroll & Attendance system.
Uses a single local SQLite file — fully offline, no server required.
"""

from __future__ import annotations
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "clinic.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_connection(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str | Path = DB_PATH, schema_path: str | Path = SCHEMA_PATH) -> None:
    conn = get_connection(db_path)
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    conn.executescript(schema_sql)

    # Seed default shift time windows if not already present
    conn.execute(
        """
        INSERT OR IGNORE INTO shift_definitions (code, label, start_time, end_time, crosses_midnight)
        VALUES
            ('M', 'Morning', '07:00', '13:30', 0),
            ('E', 'Evening', '13:30', '20:00', 0),
            ('N', 'Night',   '20:00', '07:00', 1)
        """
    )

    # Seed default global config values (Owner can edit these later via the dashboard)
    default_config = [
        ("base_monthly_hours", "192", "int", "Base Monthly Hours", "Standard hours/month for insured staff", "payroll"),
        ("overtime_premium_pct", "40", "int", "Overtime Premium (%)", "Extra % over base hourly rate for hours beyond base_monthly_hours ('H')", "payroll"),
        ("holiday_premium_pct", "30", "int", "Holiday Premium (%)", "Extra % over base hourly rate for holiday shifts ('ت', non-insured)", "payroll"),
        ("insurance_deduction_pct", "7", "int", "Insurance Deduction (%)", "Deducted from insured staff's total earnings, excluding child allowance & overtime", "payroll"),
        ("fixed_marriage_allowance", "0", "int", "Marriage Allowance (fixed)", "Flat amount added if employee.is_married = 1", "allowances"),
        ("fixed_child_allowance", "0", "int", "Child Allowance (per child)", "Multiplied by employee.number_of_children", "allowances"),
        ("fixed_housing_allowance", "30000000", "int", "Housing Allowance (fixed, insured)", "Flat monthly amount for all insured staff -- one global rate, edit here instead of per employee", "allowances"),
        ("fixed_food_allowance", "22000000", "int", "Food Allowance (fixed, insured)", "Flat monthly amount for all insured staff -- one global rate, edit here instead of per employee", "allowances"),
        ("housing_allowance_per_hour", "156250", "int", "Housing Allowance (per hour, non-insured)", "Multiplied by worked hours for all non-insured staff -- one global rate", "allowances"),
        ("food_allowance_per_hour", "114500", "int", "Food Allowance (per hour, non-insured)", "Multiplied by worked hours for all non-insured staff -- one global rate", "allowances"),
        ("medical_leave_paid_days_cap", "3", "int", "Medical Leave Paid Days/Month", "Days/month covered by clinic before becoming unpaid", "leave"),
        ("piercing_commission_pct", "30", "int", "Piercing Commission (%)", "Direct commission rate for piercing service", "commissions"),
        ("fast_blood_test_commission_pct", "20", "int", "Fast Blood Test Commission (%)", "Direct commission rate for fast blood test service", "commissions"),
    ]
    conn.executemany(
        """INSERT OR IGNORE INTO system_config (key, value, value_type, label, description, category)
           VALUES (?, ?, ?, ?, ?, ?)""",
        default_config,
    )

    # Seed starting job roles (Owner-editable/extensible from the Employees tab -- not hardcoded elsewhere)
    conn.executemany(
        "INSERT OR IGNORE INTO roles (name) VALUES (?)",
        [("بهیار",), ("پذیرش",)],
    )

    # Seed default allowance rule definitions (flexible — Owner can re-toggle applies_to_* later)
    default_allowances = [
        # code, label, applies_to_insured, applies_to_non_insured, enabled, amount_type, config_key, employee_field, condition_field, excluded_from_insurance_base, sort_order
        ("marriage", "Marriage Allowance", 1, 0, 1, "config_flat", "fixed_marriage_allowance", None, "is_married", 0, 10),
        ("child", "Child Allowance", 1, 0, 1, "config_per_child", "fixed_child_allowance", None, None, 1, 20),
        ("housing_fixed", "Housing Allowance (fixed)", 1, 0, 1, "config_flat", "fixed_housing_allowance", None, None, 0, 30),
        ("food_fixed", "Food Allowance (fixed)", 1, 0, 1, "config_flat", "fixed_food_allowance", None, None, 0, 40),
        ("seniority_fixed", "Seniority Allowance", 1, 0, 1, "employee_field_flat", None, "seniority_allowance", None, 0, 50),
        ("housing_hourly", "Housing Allowance (hourly)", 0, 1, 1, "config_per_hour", "housing_allowance_per_hour", None, None, 0, 60),
        ("food_hourly", "Food Allowance (hourly)", 0, 1, 1, "config_per_hour", "food_allowance_per_hour", None, None, 0, 70),
    ]
    conn.executemany(
        """INSERT OR IGNORE INTO allowance_definitions
           (code, label, applies_to_insured, applies_to_non_insured, enabled, amount_type,
            config_key, employee_field, condition_employee_field, excluded_from_insurance_base, sort_order)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        default_allowances,
    )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at: {DB_PATH}")