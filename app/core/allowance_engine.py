"""
Flexible Allowance Engine.

Rather than hardcoding "marriage allowance applies only to insured staff" in
Python, every allowance is described declaratively in the `allowance_definitions`
table. The Owner can enable/disable an allowance, or flip which employment
type(s) it applies to, entirely through the dashboard UI — no code changes.

Each allowance row computes to an amount via one of five `amount_type`s:
  - config_flat:            flat value from system_config[config_key]
  - config_per_child:       employee.number_of_children * system_config[config_key]
  - config_per_hour:        system_config[config_key] * worked_hours (global rate,
                             e.g. housing/food allowance per hour for non-insured staff)
  - employee_field_flat:    flat value from employees[employee_field]
  - employee_field_per_hour: employees[employee_field] * worked_hours

An optional `condition_employee_field` gates the allowance on a truthy
employee column (e.g. 'is_married').
"""

from __future__ import annotations
import sqlite3
from dataclasses import dataclass

from app.core.config import get_config


@dataclass
class AllowanceResult:
    code: str
    label: str
    amount: int
    excluded_from_insurance_base: bool


def get_active_allowance_definitions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM allowance_definitions WHERE enabled = 1 ORDER BY sort_order"
    ).fetchall()


def compute_allowances_for_employee(
    conn: sqlite3.Connection,
    employee: sqlite3.Row,
    worked_hours: float,
    allowance_defs: list[sqlite3.Row] | None = None,
) -> list[AllowanceResult]:
    """Compute every applicable allowance for one employee for one payroll period."""
    if allowance_defs is None:
        allowance_defs = get_active_allowance_definitions(conn)

    employment_type = employee["employment_type"]
    results: list[AllowanceResult] = []

    for rule in allowance_defs:
        applies = (
            (employment_type == "insured" and rule["applies_to_insured"])
            or (employment_type == "non_insured" and rule["applies_to_non_insured"])
        )
        if not applies:
            continue

        # Optional condition gate (e.g. only if is_married = 1)
        cond_field = rule["condition_employee_field"]
        if cond_field:
            try:
                if not employee[cond_field]:
                    continue
            except (IndexError, KeyError):
                continue  # field not present -> skip rule defensively

        amount = _compute_amount(conn, rule, employee, worked_hours)
        if amount:
            results.append(
                AllowanceResult(
                    code=rule["code"],
                    label=rule["label"],
                    amount=amount,
                    excluded_from_insurance_base=bool(rule["excluded_from_insurance_base"]),
                )
            )

    return results


def _compute_amount(conn, rule: sqlite3.Row, employee: sqlite3.Row, worked_hours: float) -> int:
    amount_type = rule["amount_type"]

    if amount_type == "config_flat":
        return int(get_config(conn, rule["config_key"], default=0) or 0)

    if amount_type == "config_per_child":
        per_child = get_config(conn, rule["config_key"], default=0) or 0
        children = employee["number_of_children"] or 0
        return int(per_child * children)

    if amount_type == "config_per_hour":
        per_hour = get_config(conn, rule["config_key"], default=0) or 0
        return round(per_hour * worked_hours)

    if amount_type == "employee_field_flat":
        field = rule["employee_field"]
        try:
            return int(employee[field] or 0)
        except (IndexError, KeyError):
            return 0

    if amount_type == "employee_field_per_hour":
        field = rule["employee_field"]
        try:
            per_hour = employee[field] or 0
        except (IndexError, KeyError):
            per_hour = 0
        return round(per_hour * worked_hours)

    return 0