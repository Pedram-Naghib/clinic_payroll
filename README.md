# Clinic Payroll & Attendance System

100% local, offline Python application. No cloud dependency.

## Setup

```bash
pip install -r requirements.txt
python -m app.db.database              # creates/initializes data/clinic.db
python -m app.core.import_employees data/updated_employees.xlsx   # import your personnel
```

## Run the Owner Dashboard

```bash
python -m app.ui.main_window
```

This opens three tabs:
- **Employees** — add/edit/deactivate personnel
- **Allowance Rules** — toggle which employment type gets which allowance, enable/disable any allowance
- **System Config** — edit every global constant (allowance amounts, overtime %, insurance %, commission %, etc.)

## Testing the payroll engine directly (no UI)

```python
from app.db.database import get_connection
from app.core.payroll_engine import calculate_payroll_for_employee

conn = get_connection()
emp = conn.execute("SELECT * FROM employees WHERE full_name = ?", ("Leila Ranjkesh",)).fetchone()
result = calculate_payroll_for_employee(conn, emp, worked_hours=192)
print(result.to_dict())
```

## What's implemented so far

- SQLite schema: employees, system_config, allowance_definitions, attendance,
  shift planning, leave, direct commissions, payroll runs.
- Zaman Pardaz `.TXT` device export parser.
- Jalali (Persian) <-> Gregorian date conversion.
- Flexible allowance engine — no hardcoded "marriage allowance = insured only"
  logic; it's all driven by the `allowance_definitions` table, editable from
  the Owner dashboard.
- Payroll calculation engine for both insured and non-insured employees,
  including the dual-role manager case (flat fixed_monthly_salary add-on
  without double-counting fixed housing/food allowances).
- Owner dashboard (PySide6): Employee CRUD, Allowance Rules toggles, System
  Config editor.

## Known data note

"Isa Rahmani" (per the spreadsheet) has `is_exempt_from_shifts = 1`, but his
payroll formula requires his nursing hours to be tracked hourly. These two
are in tension — flip `is_exempt_from_shifts` to 0 once you confirm his
attendance should be tracked, otherwise his nursing-hours portion will have
no hours to calculate from.

## Not yet built

- Shift schedule importer (digitizing the manual M/E/N/H/ت grid)
- Fact-checking engine (planned shifts vs. device punches, shift-swap detection)
- Leave management workflow
- Direct commissions tracking UI
- Login/role-based access (Owner / Manager / Staff)
- Device EnNo -> employee name mapping import
