"""
Persian UI translations. The single place to edit any visible label.
Database values stay English (insured / non_insured / etc.) per project decision.
"""

# Window & tabs
APP_TITLE = "سامانه حقوق و حضور و غیاب درمانگاه"
TAB_EMPLOYEES = "کارکنان"
TAB_ALLOWANCES = "تنظیم مزایا"
TAB_CONFIG = "تنظیمات"

# Generic
SAVE_CHANGES = "ذخیره تغییرات"
REFRESH = "بازخوانی"
ADD = "افزودن"
EDIT = "ویرایش"
DELETE = "حذف"
RESTORE = "بازیابی"
OK = "تأیید"
CANCEL = "انصراف"
YES = "بله"
NO = "خیر"
SAVED = "ذخیره شد"
WARNING = "هشدار"
ERROR = "خطا"
CONFIRM = "تأیید"
SHOW_INACTIVE = "نمایش کارکنان غیرفعال"

# Employee type display names (DB stays 'insured'/'non_insured')
EMP_TYPE_INSURED = "بیمه‌شده"
EMP_TYPE_NON_INSURED = "بیمه نشده"
EMP_TYPE_DISPLAY = {"insured": EMP_TYPE_INSURED, "non_insured": EMP_TYPE_NON_INSURED}

# Employees tab
EMPLOYEES_INFO = (
    "مدیریت کارکنان. حذف یک کارمند او را غیرفعال می‌کند "
    "(سوابق حقوق و دستمزد حفظ می‌شود)."
)
ADD_EMPLOYEE = "افزودن کارمند"
EDIT_SELECTED = "ویرایش انتخاب‌شده"
DELETE_SELECTED = "حذف انتخاب‌شده"
RESTORE_SELECTED = "بازیابی انتخاب‌شده"

COL_NAME = "نام"
COL_TYPE = "نوع استخدام"
COL_DEVICE = "شماره دستگاه"
COL_EXEMPT = "معاف از شیفت"
COL_MONTHLY_SALARY = "حقوق ماهیانه"
COL_HOURLY_RATE = "دستمزد ساعتی"
COL_MARRIED = "متأهل"
COL_CHILDREN = "تعداد فرزندان"
COL_ACTIVE = "وضعیت"
STATUS_ACTIVE = "فعال"
STATUS_INACTIVE = "غیرفعال"

# Employee dialog
DLG_ADD_EMPLOYEE = "افزودن کارمند جدید"
DLG_EDIT_EMPLOYEE = "ویرایش کارمند"
LBL_FULL_NAME = "نام کامل:"
LBL_EMP_TYPE = "نوع استخدام:"
LBL_DEVICE_ID = "شماره دستگاه:"
LBL_DEVICE_ID_HINT = "خالی یا ۰ = نامشخص (در محاسبه نادیده گرفته می‌شود)؛ ۱- = بدون نیاز به ثبت ورود/خروج"
LBL_EXEMPT = "معاف از شیفت‌بندی و پایش حضور"
LBL_FIXED_SALARY = "حقوق ثابت ماهیانه:"
LBL_FIXED_SALARY_HINT = "بیمه‌شده: حقوق پایه ماه. بیمه نشده: مبلغ اضافه ثابت (مثلاً حقوق مدیریت)"
LBL_HOURLY_RATE = "دستمزد ساعتی پایه:"
LBL_HOURLY_RATE_HINT = "برای بیمه‌شده، خالی بگذارید تا از حقوق ماهانه ÷ ۱۹۲ محاسبه شود"
LBL_HOUSING_HOURLY = "حق مسکن ساعتی:"
LBL_FOOD_HOURLY = "حق خواربار ساعتی:"
LBL_HOUSING_FIXED = "حق مسکن ثابت:"
LBL_FOOD_FIXED = "حق خواربار ثابت:"
LBL_MARRIED = "متأهل"
LBL_CHILDREN = "تعداد فرزندان:"
LBL_SENIORITY = "حق سنوات:"
LBL_VACATION_BALANCE = "موجودی مرخصی (روز):"
LBL_NOTES = "یادداشت‌ها:"

MSG_MISSING_NAME = "نام وارد نشده"
MSG_NAME_REQUIRED = "وارد کردن نام کامل الزامی است."
MSG_NO_SELECTION = "هیچ موردی انتخاب نشده"
MSG_SELECT_EMPLOYEE = "ابتدا یک کارمند را از فهرست انتخاب کنید."
MSG_CONFIRM_DELETE = "تأیید حذف"
MSG_DELETE_PROMPT = "این عملیات کارمند را غیرفعال می‌کند (سوابق حفظ می‌شوند). ادامه می‌دهید؟"
MSG_EMPLOYEES_SAVED = "اطلاعات کارکنان با موفقیت ذخیره شد."

# Allowance Rules tab
ALLOWANCES_INFO = (
    "برای هر مزایا تعیین کنید که به کدام نوع استخدام تعلق می‌گیرد یا آن را کاملاً غیرفعال کنید. "
    "مثال: اگر حق ازدواج بعداً برای کارکنان بیمه نشده نیز برقرار شد، کافی است گزینهٔ مربوطه را تیک بزنید — "
    "هیچ تغییری در کد لازم نیست."
)
COL_CODE = "کد"
COL_LABEL = "عنوان"
COL_ENABLED = "فعال"
COL_APPLIES_INSURED = "برای بیمه‌شده"
COL_APPLIES_NON_INSURED = "برای بیمه نشده"
COL_AMOUNT_SOURCE = "منبع مبلغ"
SRC_CONFIG = "تنظیم سیستمی: {key}"
SRC_CONFIG_PER_CHILD = "تعداد فرزندان × تنظیم سیستمی: {key}"
SRC_EMP_FIELD = "ویژگی کارمند: {field}"
SRC_EMP_FIELD_PER_HOUR = "ویژگی کارمند: {field} × ساعات کارکرد"
MSG_ALLOWANCES_SAVED = "قوانین مزایا با موفقیت ذخیره شد."

# Config tab
CONFIG_INFO = (
    "هر متغیر سراسری را در جدول زیر ویرایش کرده و دکمهٔ «ذخیره تغییرات» را کلیک کنید. "
    "این مقادیر در تمام محاسبات حقوق در سراسر برنامه استفاده می‌شوند — نیازی به تغییر کد نیست."
)
ADD_NEW_VARIABLE = "افزودن متغیر جدید"
COL_KEY = "کلید"
COL_VALUE = "مقدار"
COL_VALUE_TYPE = "نوع داده"
COL_CATEGORY = "دسته‌بندی"
COL_DESCRIPTION = "توضیحات"
DLG_ADD_CONFIG = "افزودن متغیر تنظیمات جدید"
LBL_KEY_HINT = "کلید (بدون فاصله):"
LBL_LABEL = "عنوان:"
LBL_VALUE = "مقدار:"
LBL_TYPE = "نوع داده:"
LBL_CATEGORY = "دسته‌بندی:"
LBL_DESCRIPTION = "توضیحات:"
MSG_CONFIG_SAVED = "تنظیمات با موفقیت ذخیره شد."
MSG_INVALID_VALUE = "مقدار نامعتبر"
MSG_VALUE_TYPE_MISMATCH = "مقدار با نوع داده '{type}' سازگار نیست."
MSG_KEY_LABEL_REQUIRED = "کلید و عنوان الزامی هستند."


# ============================================================
# Persian display labels for DB-seeded identifiers.
# The DB stores stable English keys/codes/field names so other code
# can reference them; what the user sees is looked up here.
# ============================================================

CONFIG_LABELS = {
    "base_monthly_hours": "ساعات استاندارد ماهانه",
    "overtime_premium_pct": "درصد اضافه‌کاری",
    "holiday_premium_pct": "درصد تعطیل کاری",
    "insurance_deduction_pct": "درصد کسر بیمه",
    "fixed_marriage_allowance": "حق ازدواج (ثابت)",
    "fixed_child_allowance": "حق اولاد (به ازای هر فرزند)",
    "medical_leave_paid_days_cap": "سقف مرخصی استعلاجی پرداختی (روز در ماه)",
    "piercing_commission_pct": "درصد کمیسیون پیرسینگ",
    "fast_blood_test_commission_pct": "درصد کمیسیون آزمایش فوری خون",
}

CONFIG_DESCRIPTIONS = {
    "base_monthly_hours": "ساعت کاری استاندارد ماهانه برای کارکنان بیمه‌شده",
    "overtime_premium_pct": "درصد اضافه روی دستمزد ساعتی پایه برای ساعات H (Help)",
    "holiday_premium_pct": "درصد اضافه روی دستمزد ساعتی پایه برای شیفت تعطیل (ت) — بیمه نشده",
    "insurance_deduction_pct": "از کل درآمد بیمه‌شده کسر می‌شود (به جز حق اولاد و اضافه‌کاری)",
    "fixed_marriage_allowance": "مبلغ ثابتی که در صورت متأهل بودن کارمند اضافه می‌شود",
    "fixed_child_allowance": "در تعداد فرزندان کارمند ضرب می‌شود",
    "medical_leave_paid_days_cap": "سقف روزهای مرخصی استعلاجی که توسط درمانگاه پرداخت می‌شود",
    "piercing_commission_pct": "درصد کمیسیون مستقیم خدمات پیرسینگ",
    "fast_blood_test_commission_pct": "درصد کمیسیون مستقیم خدمات آزمایش فوری خون",
}

CATEGORY_LABELS = {
    "payroll": "حقوق",
    "allowances": "مزایا",
    "commissions": "کمیسیون‌ها",
    "leave": "مرخصی",
    "general": "عمومی",
}

ALLOWANCE_LABELS = {
    "marriage": "حق ازدواج",
    "child": "حق اولاد",
    "housing_fixed": "حق مسکن (ثابت)",
    "food_fixed": "حق خواربار (ثابت)",
    "seniority_fixed": "حق سنوات",
    "housing_hourly": "حق مسکن (ساعتی)",
    "food_hourly": "حق خواربار (ساعتی)",
}

# Employee column names → human Persian labels (used in "Amount Source" column)
EMPLOYEE_FIELD_LABELS = {
    "fixed_housing_allowance": "حق مسکن ثابت",
    "fixed_food_allowance": "حق خواربار ثابت",
    "seniority_allowance": "حق سنوات",
    "housing_allowance_per_hour": "حق مسکن ساعتی",
    "food_allowance_per_hour": "حق خواربار ساعتی",
    "number_of_children": "تعداد فرزندان",
    "fixed_monthly_salary": "حقوق ثابت ماهیانه",
    "base_hourly_rate": "دستمزد ساعتی پایه",
}


def t_config_label(key: str, fallback: str = "") -> str:
    return CONFIG_LABELS.get(key, fallback or key)

def t_config_desc(key: str, fallback: str = "") -> str:
    return CONFIG_DESCRIPTIONS.get(key, fallback or "")

def t_category(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)

def t_allowance_label(code: str, fallback: str = "") -> str:
    return ALLOWANCE_LABELS.get(code, fallback or code)

def t_emp_field(field: str) -> str:
    return EMPLOYEE_FIELD_LABELS.get(field, field)


# ============================================================
# Attendance tab
# ============================================================

TAB_ATTENDANCE = "حضور و غیاب"

PERSIAN_MONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]

ATTENDANCE_INFO = (
    "فایل خروجی دستگاه (GLG_xxx.TXT) را بارگذاری کنید، سپس ماه دلخواه را انتخاب "
    "و دکمهٔ «محاسبه ساعات کار» را بزنید."
)

BTN_IMPORT_PUNCHES = "بارگذاری فایل دستگاه"
BTN_COMPUTE_HOURS = "محاسبه ساعات کار"
BTN_RELINK_PUNCHES = "اتصال مجدد رکوردهای بدون مالک"
LBL_YEAR = "سال"
LBL_MONTH = "ماه"

COL_HOURS = "ساعات کارکرد"
COL_DAYS = "روزهای حضور"
COL_SESSIONS = "تعداد جلسات"
COL_STATUS = "وضعیت"
COL_ANOMALIES_COUNT = "خطاها"

STATUS_FIXED_PAY = "حقوق ثابت"
STATUS_NO_PUNCHES = "بدون ثبت"
STATUS_OK = "✓"
STATUS_HAS_ANOMALIES = "⚠ {n} مورد"

MSG_SELECT_FILE = "انتخاب فایل خروجی دستگاه"
MSG_FILE_TYPES = "فایل دستگاه (*.TXT *.txt);;همهٔ فایل‌ها (*)"
MSG_IMPORT_TITLE = "نتیجهٔ بارگذاری"
MSG_IMPORT_RESULT = (
    "{parsed} رکورد خوانده شد.\n"
    "{inserted} رکورد جدید اضافه شد.\n"
    "{duplicates} رکورد تکراری نادیده گرفته شد.\n\n"
    "{unmatched_count} رکورد به هیچ کارمندی تخصیص نیافت.\n"
    "{unmatched_section}"
)
MSG_UNMATCHED_DETAILS = (
    "شماره‌های دستگاه ناشناخته:\n  {enno_list}\n\n"
    "برای حل این مشکل، در زبانهٔ «کارکنان» شماره دستگاه صحیح را برای هر کارمند وارد کنید "
    "و سپس روی «اتصال مجدد رکوردهای بدون مالک» کلیک کنید."
)
MSG_RELINK_RESULT = "{n} رکورد به کارمندان متصل شد."
MSG_NO_DATA = "ابتدا یک فایل دستگاه بارگذاری کنید."
MSG_COMPUTATION_DONE = "محاسبه برای {month_label} {year} تکمیل شد."


# ============================================================
# Commissions tab (کمیسیون‌های مستقیم)
# ============================================================

TAB_COMMISSIONS = "کمیسیون‌های مستقیم"

COMMISSIONS_INFO = (
    "ثبت کمیسیون‌های مستقیمی که بلافاصله از درآمد بیمار به کارمند پرداخت می‌شود "
    "(پیرسینگ، آزمایش فوری خون). این مبالغ کاملاً جدا از حقوق ماهیانه محاسبه و گزارش می‌شوند."
)

SERVICE_TYPE_PIERCING = "پیرسینگ"
SERVICE_TYPE_FAST_BLOOD_TEST = "آزمایش فوری خون"
SERVICE_TYPE_DISPLAY = {
    "piercing": SERVICE_TYPE_PIERCING,
    "fast_blood_test": SERVICE_TYPE_FAST_BLOOD_TEST,
}

LBL_EMPLOYEE = "کارمند:"
LBL_SERVICE_TYPE = "نوع خدمت:"
LBL_FEE_TOMAN = "مبلغ دریافتی (تومان):"
LBL_SERVICE_DATE = "تاریخ (شمسی):"
LBL_SERVICE_DATE_HINT = "مثال: 1405/03/15"
LBL_COMMISSION_NOTES = "یادداشت (اختیاری):"
LBL_COMMISSION_PREVIEW_EMPTY = "کمیسیون: —"
LBL_COMMISSION_PREVIEW = "کمیسیون ({rate:g}٪): {amount:,} ریال"

BTN_SAVE_COMMISSION = "ثبت کمیسیون"
BTN_DELETE_COMMISSION = "حذف انتخاب‌شده"

COL_COMM_EMPLOYEE = "کارمند"
COL_COMM_SERVICE = "نوع خدمت"
COL_COMM_FEE = "مبلغ دریافتی (ریال)"
COL_COMM_RATE = "درصد"
COL_COMM_AMOUNT = "مبلغ کمیسیون (ریال)"
COL_COMM_DATE = "تاریخ"
COL_COMM_NOTES = "یادداشت"

FILTER_ALL_EMPLOYEES = "همهٔ کارکنان"

MSG_INVALID_FEE = "مبلغ نامعتبر"
MSG_FEE_REQUIRED = "مبلغ دریافتی باید عددی بزرگ‌تر از صفر باشد."
MSG_INVALID_DATE = "تاریخ نامعتبر"
MSG_DATE_FORMAT_HINT = "تاریخ را به فرم ۱۴۰۵/۰۳/۱۵ وارد کنید."
MSG_NO_EMPLOYEE = "کارمند انتخاب نشده"
MSG_SELECT_EMPLOYEE_FIRST = "ابتدا یک کارمند را انتخاب کنید."
MSG_COMMISSION_SAVED = "کمیسیون با موفقیت ثبت شد."
MSG_NO_COMMISSION_SELECTION = "ابتدا یک ردیف را از جدول انتخاب کنید."
MSG_CONFIRM_DELETE_COMMISSION = "این ردیف کمیسیون برای همیشه حذف می‌شود. ادامه می‌دهید؟"


# ============================================================
# Payroll-run tab (اجرای حقوق ماهیانه)
# ============================================================

TAB_PAYROLL = "اجرای حقوق"

PAYROLL_INFO = (
    "ماه شمسی را انتخاب کرده و «اجرای محاسبه» را بزنید. حضور و غیاب برای این بازه "
    "به‌صورت خودکار از روی رکوردهای خام دستگاه بازمحاسبه می‌شود. پس از بررسی نتایج، "
    "برای ثبت دائمی در دیتابیس روی «ذخیرهٔ این اجرا» کلیک کنید."
)

BTN_RUN_PAYROLL = "اجرای محاسبه"
BTN_SAVE_PAYROLL_RUN = "ذخیرهٔ این اجرا"

COL_PR_NAME = "نام"
COL_PR_TYPE = "نوع استخدام"
COL_PR_REGULAR_HOURS = "ساعات عادی"
COL_PR_OVERTIME_HOURS = "ساعات اضافه‌کاری"
COL_PR_HOLIDAY_HOURS = "ساعات تعطیل"
COL_PR_BASE_PAY = "حقوق پایه"
COL_PR_OVERTIME_PAY = "مزد اضافه‌کاری"
COL_PR_HOLIDAY_PAY = "مزد تعطیل‌کاری"
COL_PR_ALLOWANCES = "جمع مزایا"
COL_PR_INSURANCE = "کسر بیمه"
COL_PR_TOTAL = "خالص پرداختی"

LBL_PAYROLL_TOTAL = "جمع کل خالص پرداختی این ماه: {total:,} ریال"
MSG_SKIPPED_EMPLOYEES = (
    "{n} کارمند به دلیل نامشخص بودن شماره دستگاه (۰) از این محاسبه حذف شدند: {names}\n"
    "برای رفع این مشکل، در زبانهٔ «کارکنان» شماره دستگاه صحیح را وارد کنید."
)
MSG_NO_RESULTS_TO_SAVE = "ابتدا محاسبه را اجرا کنید."
MSG_CONFIRM_OVERWRITE_RUN = (
    "برای {month_label} {year} قبلاً یک اجرای حقوق ذخیره شده است (تاریخ ثبت: {generated_at}). "
    "ذخیرهٔ مجدد، نتایج قبلی را جایگزین می‌کند. ادامه می‌دهید؟"
)
MSG_PAYROLL_RUN_SAVED = "اجرای حقوق با شناسهٔ #{run_id} با موفقیت ذخیره شد."