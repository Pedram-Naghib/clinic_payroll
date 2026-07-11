-- Clinic Payroll & Attendance System — SQLite Schema
-- All monetary values stored as INTEGER (Rials, no decimals) to avoid float errors.

PRAGMA foreign_keys = ON;

-- ===================== USERS / AUTH =====================
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('owner', 'manager', 'staff')),
    employee_id     INTEGER REFERENCES employees(id),  -- NULL for owner/manager not tied to a staff record
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ===================== EMPLOYEES =====================
CREATE TABLE IF NOT EXISTS employees (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name           TEXT NOT NULL,
    device_enroll_no    TEXT,                 -- EnNo from Zaman Pardaz device (links punches to person)
    employment_type     TEXT NOT NULL CHECK (employment_type IN ('insured', 'non_insured')),
    is_exempt_from_shifts INTEGER NOT NULL DEFAULT 0,  -- e.g. Pegah Naghib (no shift tracking)
    fixed_monthly_salary INTEGER,             -- insured: base monthly salary. non_insured: flat add-on (e.g. Rahmani mgmt pay)
    base_hourly_rate     INTEGER,             -- explicit hourly rate (esp. non_insured); auto-derived for insured if blank
    is_married                   INTEGER DEFAULT 0,  -- structural flag, replaces hardcoded marriage_allowance
    number_of_children           INTEGER DEFAULT 0,  -- multiplied by System_Config.fixed_child_allowance
    seniority_allowance          INTEGER DEFAULT 0,  -- سنوات
    vacation_balance_days        REAL DEFAULT 0,     -- persistent paid-vacation balance
    active                       INTEGER NOT NULL DEFAULT 1,  -- soft-delete flag; intentionally hidden from the main UI grid, not removed from the DB
    notes                        TEXT,
    created_at                   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ===================== JOB ROLES (dynamic, many-to-many) =====================
-- Owner-defined role names (e.g. 'Behyar', 'Paziresh'), typed freely in the UI --
-- never hardcoded in Python. An employee can hold any number of roles at once.
CREATE TABLE IF NOT EXISTS roles (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS employee_roles (
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    role_id     INTEGER NOT NULL REFERENCES roles(id),
    PRIMARY KEY (employee_id, role_id)
);

-- ===================== GLOBAL CONFIG (Owner-editable, no code changes needed) =====================
CREATE TABLE IF NOT EXISTS system_config (
    key           TEXT PRIMARY KEY,
    value         TEXT NOT NULL,           -- stored as text, cast per value_type at read time
    value_type    TEXT NOT NULL DEFAULT 'int' CHECK (value_type IN ('int','float','text')),
    label         TEXT NOT NULL,           -- human-readable label for the dashboard
    description   TEXT,
    category      TEXT DEFAULT 'general',  -- groups related settings in the UI
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ===================== FLEXIBLE ALLOWANCE ENGINE =====================
-- Lets the Owner toggle which employment types receive which allowance,
-- and where the amount comes from, without any code changes.
CREATE TABLE IF NOT EXISTS allowance_definitions (
    code                    TEXT PRIMARY KEY,   -- e.g. 'marriage', 'child', 'housing_fixed', 'food_fixed', 'seniority_fixed', 'housing_hourly', 'food_hourly'
    label                   TEXT NOT NULL,
    applies_to_insured      INTEGER NOT NULL DEFAULT 0,
    applies_to_non_insured  INTEGER NOT NULL DEFAULT 0,
    enabled                 INTEGER NOT NULL DEFAULT 1,
    amount_type             TEXT NOT NULL CHECK (amount_type IN (
                                 'config_flat',
                                 'config_per_child',
                                 'config_per_hour',
                                 'employee_field_flat',
                                 'employee_field_per_hour'
                             )),
    config_key              TEXT,
    employee_field          TEXT,
    condition_employee_field TEXT,
    excluded_from_insurance_base INTEGER NOT NULL DEFAULT 0,
    sort_order               INTEGER DEFAULT 0,
    updated_at                TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ===================== PLANNED SHIFTS (manager's manual schedule) =====================
-- One row per employee per calendar day. shift_code meaning, per the
-- manager's paper shift grid: M=Morning, E=Evening, N=Night, H=Holiday (a
-- full calendar day the manager has marked as a clinic holiday) -- also ت,
-- V(acation), S(ick), A(bsent), null=off. Can hold combos like 'M' + 'E' ->
-- store as 'ME'.
-- NOTE: there is currently no importer reading this table (it's a schema
-- stub for a future manual-grid entry UI) -- today, holiday-ness is instead
-- computed automatically from the `iranian_holidays` table (app.core.holidays)
-- and joined against `daily_attendance.work_date` in
-- attendance_engine.build_payroll_inputs(), which also excludes night ('N')
-- shifts from holiday premium eligibility for both employment types
-- (clinic policy: night shifts never earn the holiday premium).
CREATE TABLE IF NOT EXISTS planned_shifts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id     INTEGER NOT NULL REFERENCES employees(id),
    work_date       TEXT NOT NULL,         -- ISO date 'YYYY-MM-DD' (Gregorian, converted from Jalali on entry)
    shift_code       TEXT,                 -- M / E / N / H / ت / etc. Can hold combos like 'M' + 'E' -> store as 'ME'
    planned_start    TEXT,                 -- HH:MM, optional override of default shift times
    planned_end      TEXT,
    created_by       INTEGER REFERENCES users(id),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(employee_id, work_date)
);

-- Default shift time windows (Owner-configurable). Used both to evaluate
-- punches against M/E/N and, critically, by attendance_engine's night-shift
-- classifier (_is_night_shift) to decide holiday-premium eligibility -- a
-- session clocking in within the 'N' window is never treated as a holiday
-- shift, regardless of what calendar date it falls on.
CREATE TABLE IF NOT EXISTS shift_definitions (
    code        TEXT PRIMARY KEY,   -- M, E, N
    label       TEXT NOT NULL,
    start_time  TEXT NOT NULL,      -- HH:MM
    end_time    TEXT NOT NULL,      -- HH:MM (may cross midnight for N)
    crosses_midnight INTEGER NOT NULL DEFAULT 0
);

-- ===================== RAW DEVICE PUNCHES =====================
CREATE TABLE IF NOT EXISTS raw_punches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    device_enroll_no TEXT NOT NULL,        -- EnNo as it appears in the device export
    employee_id      INTEGER REFERENCES employees(id),  -- resolved link, nullable until matched
    punch_datetime    TEXT NOT NULL,       -- ISO 'YYYY-MM-DD HH:MM:SS'
    raw_mode          TEXT,                -- Mode column from device (1=fingerprint,3=card,...)
    raw_inout_flag    TEXT,                -- INOUT column as exported (unreliable; kept for audit)
    inferred_direction TEXT CHECK (inferred_direction IN ('IN','OUT')),  -- computed by parser
    source_file       TEXT,
    imported_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(device_enroll_no, punch_datetime, raw_mode)
);

CREATE INDEX IF NOT EXISTS idx_raw_punches_emp_date
    ON raw_punches (employee_id, punch_datetime);

-- ===================== DERIVED DAILY ATTENDANCE (after fact-checking) =====================
CREATE TABLE IF NOT EXISTS daily_attendance (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id     INTEGER NOT NULL REFERENCES employees(id),
    work_date       TEXT NOT NULL,
    first_in        TEXT,           -- earliest IN punch time that day
    last_out        TEXT,           -- latest OUT punch time that day
    worked_hours     REAL DEFAULT 0,
    planned_shift_code TEXT,
    status            TEXT,         -- 'ok','missing_punch','absent','swap_suggested','manager_approved', etc.
    manager_reviewed  INTEGER NOT NULL DEFAULT 0,
    manager_note      TEXT,
    UNIQUE(employee_id, work_date)
);

-- ===================== SHIFT SWAP SUGGESTIONS =====================
CREATE TABLE IF NOT EXISTS shift_swap_suggestions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    work_date            TEXT NOT NULL,
    absent_employee_id   INTEGER NOT NULL REFERENCES employees(id),
    covering_employee_id INTEGER NOT NULL REFERENCES employees(id),
    planned_shift_code   TEXT,
    covering_punch_in    TEXT,
    covering_punch_out   TEXT,
    status               TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    decided_by           INTEGER REFERENCES users(id),
    decided_at           TEXT
);

-- ===================== LEAVE MANAGEMENT =====================
CREATE TABLE IF NOT EXISTS leave_requests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id     INTEGER NOT NULL REFERENCES employees(id),
    leave_type      TEXT NOT NULL CHECK (leave_type IN ('vacation','medical')),
    start_date      TEXT NOT NULL,
    end_date        TEXT NOT NULL,
    days_count       REAL NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    paid_by_clinic_days REAL DEFAULT 0,   -- for medical: capped at 3/month
    unpaid_days          REAL DEFAULT 0,
    requested_at         TEXT NOT NULL DEFAULT (datetime('now')),
    decided_by            INTEGER REFERENCES users(id)
);

-- ===================== DIRECT COMMISSIONS (tracked separately from payroll) =====================
CREATE TABLE IF NOT EXISTS direct_commissions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id     INTEGER NOT NULL REFERENCES employees(id),
    service_type    TEXT NOT NULL CHECK (service_type IN ('piercing','fast_blood_test')),
    fee_received    INTEGER NOT NULL,        -- total fee paid by patient
    commission_rate REAL NOT NULL,           -- 0.30 or 0.20
    commission_amount INTEGER NOT NULL,      -- computed: fee_received * commission_rate
    service_date     TEXT NOT NULL,
    notes             TEXT,
    recorded_by        INTEGER REFERENCES users(id),
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ===================== MONTHLY PAYROLL RESULTS (snapshot, for audit/history) =====================
CREATE TABLE IF NOT EXISTS payroll_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start    TEXT NOT NULL,    -- ISO date
    period_end      TEXT NOT NULL,
    generated_at     TEXT NOT NULL DEFAULT (datetime('now')),
    generated_by      INTEGER REFERENCES users(id),
    notes              TEXT
);

CREATE TABLE IF NOT EXISTS payroll_line_items (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    payroll_run_id       INTEGER NOT NULL REFERENCES payroll_runs(id),
    employee_id           INTEGER NOT NULL REFERENCES employees(id),
    total_hours            REAL,
    overtime_hours          REAL DEFAULT 0,
    holiday_hours            REAL DEFAULT 0,
    base_pay                  INTEGER DEFAULT 0,
    overtime_pay               INTEGER DEFAULT 0,
    holiday_premium_pay         INTEGER DEFAULT 0,
    housing_allowance            INTEGER DEFAULT 0,
    food_allowance                INTEGER DEFAULT 0,
    child_allowance                INTEGER DEFAULT 0,
    seniority_allowance              INTEGER DEFAULT 0,
    family_allowance                  INTEGER DEFAULT 0,
    under_hours_deduction               INTEGER DEFAULT 0,
    insurance_deduction                   INTEGER DEFAULT 0,
    unpaid_medical_leave_deduction          INTEGER DEFAULT 0,
    total_pay                                 INTEGER DEFAULT 0,
    breakdown_json                              TEXT   -- full computation trace for transparency
);