"""
Import employees from a CSV file into the database.

Expected CSV columns (header row required, order doesn't matter):

    full_name, employment_type, device_enroll_no, is_exempt_from_shifts,
    fixed_monthly_salary, base_hourly_rate,
    housing_allowance_per_hour, food_allowance_per_hour,
    fixed_housing_allowance, fixed_food_allowance,
    child_allowance_per_child, number_of_children,
    seniority_allowance, marriage_family_allowance,
    vacation_balance_days, notes

Notes:
- employment_type must be exactly 'insured' or 'non_insured'
- is_exempt_from_shifts: 1 or 0 (use 1 for Pegah Naghib-style exemptions)
- Leave numeric fields blank for "not applicable" -> imported as 0 / NULL
- For insured staff: fill fixed_monthly_salary; base_hourly_rate will be
  auto-computed as fixed_monthly_salary / 192 if left blank.
- For non-insured staff: fill base_hourly_rate directly.
- device_enroll_no should match the Zaman Pardaz device's enrollment number
  for that person (leave blank for staff not tracked by the device, e.g.
  Pegah Naghib / Rahmani).
"""

from __future__ import annotations
import csv
import sqlite3
from pathlib import Path

from app.core.employees import EmployeeInput, add_employee


def _to_int(val) -> int | None:
    if val is None:
        return None
    val = str(val).strip().replace(",", "")
    return int(float(val)) if val else None


def _to_float(val) -> float:
    if val is None:
        return 0.0
    val = str(val).strip()
    return float(val) if val else 0.0


def _to_bool_int(val) -> bool:
    if val is None:
        return False
    val = str(val).strip()
    return val not in ("", "0", "0.0", "False", "false")


def _row_to_employee_input(row: dict) -> EmployeeInput:
    name = str(row.get("full_name") or "").strip()
    emp = EmployeeInput(
        full_name=name,
        employment_type=str(row.get("employment_type") or "").strip(),
        device_enroll_no=(str(row.get("device_enroll_no")).strip() if row.get("device_enroll_no") else None),
        is_exempt_from_shifts=_to_bool_int(row.get("is_exempt_from_shifts")),
        fixed_monthly_salary=_to_int(row.get("fixed_monthly_salary")),
        base_hourly_rate=_to_int(row.get("base_hourly_rate")),
        housing_allowance_per_hour=_to_int(row.get("housing_allowance_per_hour")) or 0,
        food_allowance_per_hour=_to_int(row.get("food_allowance_per_hour")) or 0,
        fixed_housing_allowance=_to_int(row.get("fixed_housing_allowance")) or 0,
        fixed_food_allowance=_to_int(row.get("fixed_food_allowance")) or 0,
        is_married=_to_bool_int(row.get("is_married")),
        number_of_children=_to_int(row.get("number_of_children")) or 0,
        seniority_allowance=_to_int(row.get("seniority_allowance")) or 0,
        vacation_balance_days=_to_float(row.get("vacation_balance_days")),
        notes=(str(row.get("notes")).strip() if row.get("notes") else None),
    )
    if emp.employment_type not in ("insured", "non_insured"):
        raise ValueError(
            f"Row for '{name}': employment_type must be 'insured' or "
            f"'non_insured', got '{emp.employment_type}'"
        )
    return emp


def import_employees_csv(conn: sqlite3.Connection, csv_path: str | Path) -> list[tuple[str, int]]:
    """Returns list of (full_name, new_employee_id) for imported rows."""
    csv_path = Path(csv_path)
    imported: list[tuple[str, int]] = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not (row.get("full_name") or "").strip():
                continue
            emp = _row_to_employee_input(row)
            new_id = add_employee(conn, emp)
            imported.append((emp.full_name, new_id))

    return imported


def import_employees_xlsx(conn: sqlite3.Connection, xlsx_path: str | Path) -> list[tuple[str, int]]:
    """Same as import_employees_csv but reads directly from an .xlsx file (first sheet)."""
    import openpyxl

    xlsx_path = Path(xlsx_path)
    imported: list[tuple[str, int]] = []

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.worksheets[0]
    rows_iter = ws.iter_rows(values_only=True)
    headers = [str(h).strip() if h is not None else "" for h in next(rows_iter)]

    for row_values in rows_iter:
        row = dict(zip(headers, row_values))
        if not (row.get("full_name") or "").strip() if isinstance(row.get("full_name"), str) else not row.get("full_name"):
            continue
        emp = _row_to_employee_input(row)
        new_id = add_employee(conn, emp)
        imported.append((emp.full_name, new_id))

    return imported


def write_template(csv_path: str | Path) -> None:
    headers = [
        "full_name", "employment_type", "device_enroll_no", "is_exempt_from_shifts",
        "fixed_monthly_salary", "base_hourly_rate",
        "housing_allowance_per_hour", "food_allowance_per_hour",
        "fixed_housing_allowance", "fixed_food_allowance",
        "is_married", "number_of_children",
        "seniority_allowance",
        "vacation_balance_days", "notes",
    ]
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerow([
            "Example Insured Person", "insured", "29", "0",
            "5542000", "",
            "", "",
            "30000000", "22000000",
            "1", "1",
            "10000000",
            "0", "",
        ])
        writer.writerow([
            "Example Non-Insured Person", "non_insured", "10", "0",
            "", "756000",
            "156250", "114500",
            "", "",
            "0", "0",
            "0",
            "0", "",
        ])


if __name__ == "__main__":
    import sys
    from app.db.database import get_connection

    if len(sys.argv) > 1 and sys.argv[1] == "template":
        out_path = sys.argv[2] if len(sys.argv) > 2 else "employees_template.csv"
        write_template(out_path)
        print(f"Template written to {out_path}")
    elif len(sys.argv) > 1:
        conn = get_connection()
        path = sys.argv[1]
        if path.lower().endswith(".xlsx"):
            results = import_employees_xlsx(conn, path)
        else:
            results = import_employees_csv(conn, path)
        print(f"Imported {len(results)} employees:")
        for name, emp_id in results:
            print(f"  [{emp_id}] {name}")
    else:
        print("Usage:")
        print("  python -m app.core.import_employees template [output.csv]")
        print("  python -m app.core.import_employees <employees.csv|employees.xlsx>")
