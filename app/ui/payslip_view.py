from __future__ import annotations
import base64
import sqlite3
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument, QGuiApplication, QPageLayout, QPageSize
from PySide6.QtCore import QMarginsF
from PySide6.QtPrintSupport import QPrinter, QPrintDialog
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QFileDialog, QMessageBox,
)

from app.core.payslip import Payslip, build_payslip
from app.core.jalali import gregorian_to_jalali
from app.core.num2fa import amount_in_words_rials
from app.ui import strings_fa as S

_EMP_TYPE_DISPLAY = {"insured": "بیمه‌شده", "non_insured": "بیمه نشده"}

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
_LOGO_PATH = _ASSETS_DIR / "clinic_logo.png"


def _logo_data_uri() -> str:
    """Embeds the clinic logo as a base64 data: URI so the payslip HTML is
    fully self-contained -- no external file path to resolve at print/PDF
    time, regardless of which machine renders it."""
    try:
        data = _LOGO_PATH.read_bytes()
    except OSError:
        return ""
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def _fmt(n: int | float) -> str:
    return f"{n:,.0f}"


def _today_jalali_str() -> str:
    jy, jm, jd = gregorian_to_jalali(date.today().year, date.today().month, date.today().day)
    return f"{jy:04d}/{jm:02d}/{jd:02d}"


def _panel_rows(lines: list) -> str:
    if not lines:
        return "<tr><td style='padding:3px 6px; color:#888;'>—</td><td></td></tr>"
    return "".join(
        f"<tr>"
        f"<td style='padding:3px 6px; border-top:1px solid #ddd;'>{l.label}</td>"
        f"<td style='padding:3px 6px; border-top:1px solid #ddd; text-align:left;' dir='ltr'>{_fmt(l.amount)}</td>"
        f"</tr>"
        for l in lines
    )


def build_payslip_html(payslip: Payslip, clinic_name: str = "درمانگاه شبانه روزی رجائی شهر") -> str:
    emp_type_display = _EMP_TYPE_DISPLAY.get(payslip.employment_type, payslip.employment_type)

    # --- Leave / shortfall transparency rows (kept from the previous design --
    # useful context even though it's not on the classic paper templates) ---
    leave_rows = ""
    if payslip.leave_days_covered:
        leave_rows += (
            f"<tr><td style='padding:3px 6px; border-top:1px solid #ddd;'>پوشش کسری کارکرد از موجودی مرخصی</td>"
            f"<td style='padding:3px 6px; border-top:1px solid #ddd; text-align:left;' dir='ltr'>"
            f"{payslip.leave_days_covered:g} روز</td></tr>"
        )
    if payslip.uncovered_shortfall_hours:
        leave_rows += (
            f"<tr><td style='padding:3px 6px; border-top:1px solid #ddd;'>کمبود کارکرد پوشش‌داده‌نشده (کسر از حقوق)</td>"
            f"<td style='padding:3px 6px; border-top:1px solid #ddd; text-align:left;' dir='ltr'>"
            f"{payslip.uncovered_shortfall_hours:g} ساعت</td></tr>"
        )
    if payslip.explicit_leave_days_taken:
        leave_rows += (
            f"<tr><td style='padding:3px 6px; border-top:1px solid #ddd;'>مرخصی صریح استفاده‌شده در این دوره</td>"
            f"<td style='padding:3px 6px; border-top:1px solid #ddd; text-align:left;' dir='ltr'>"
            f"{payslip.explicit_leave_days_taken:g} روز</td></tr>"
        )
    leave_section = ""
    if leave_rows:
        leave_section = f"""
        <table width="100%" cellspacing="0" style="border:1px solid #999; border-collapse:collapse; margin-top:5px; font-size:8pt;">
          <tr><td colspan="2" style="background:#f0f0f0; font-weight:bold; padding:3px 6px; border-bottom:1px solid #999;">مرخصی و کمبود کارکرد</td></tr>
          {leave_rows}
        </table>
        """

    earnings_allowances_rows = _panel_rows(payslip.earnings + payslip.allowances)
    deductions_rows = _panel_rows(payslip.deductions)

    logo_uri = _logo_data_uri()
    logo_img = (
        f"<img src='{logo_uri}' width='40' height='35'>" if logo_uri else ""
    )

    words = amount_in_words_rials(payslip.net_pay)

    # --- Attached day-by-day attendance detail sheet (page 2) -- lets a
    # manager check exactly which date/times a disputed month's hours came
    # from. Printed on its own page (page-break-before) so it never eats
    # into the main A5 fiche's single-page layout; simply omitted for
    # fixed-no-clocking staff who have no daily_attendance rows at all. ---
    attendance_section = ""
    if payslip.daily_attendance:
        detail_rows = "".join(
            f"<tr>"
            f"<td style='padding:3px 6px; border-top:1px solid #ddd;'>{d.jalali_date}</td>"
            f"<td style='padding:3px 6px; border-top:1px solid #ddd; text-align:center;' dir='ltr'>{d.first_in}</td>"
            f"<td style='padding:3px 6px; border-top:1px solid #ddd; text-align:center;' dir='ltr'>{d.last_out}</td>"
            f"<td style='padding:3px 6px; border-top:1px solid #ddd; text-align:center;' dir='ltr'>{d.worked_hours:g}</td>"
            f"<td style='padding:3px 6px; border-top:1px solid #ddd; text-align:center;'>{d.status}</td>"
            f"</tr>"
            for d in payslip.daily_attendance
        )
        attendance_section = f"""
        <div style="page-break-before:always; font-family: Tahoma, sans-serif; font-size: 8.5pt; color:#111; padding-top:10px;">
          <div style="text-align:center; font-weight:bold; font-size:10pt; margin-bottom:6px;">
            ریز کارکرد روزانه — {payslip.full_name} — {payslip.period_label}
          </div>
          <table width="100%" cellspacing="0" style="border:1px solid #333; border-collapse:collapse;">
            <tr style="background:#f0f0f0; font-weight:bold;">
              <td style="padding:4px 6px; border-bottom:1px solid #333;">تاریخ</td>
              <td style="padding:4px 6px; border-bottom:1px solid #333; text-align:center;">ساعت ورود</td>
              <td style="padding:4px 6px; border-bottom:1px solid #333; text-align:center;">ساعت خروج</td>
              <td style="padding:4px 6px; border-bottom:1px solid #333; text-align:center;">ساعت کارکرد</td>
              <td style="padding:4px 6px; border-bottom:1px solid #333; text-align:center;">وضعیت</td>
            </tr>
            {detail_rows}
          </table>
        </div>
        """

    return f"""
    <div dir="rtl" style="font-family: Tahoma, sans-serif; font-size: 8.5pt; color:#111;">

      <table width="100%" style="border-collapse:collapse; margin-bottom:6px;">
        <tr>
          <td style="width:50px; vertical-align:middle;">{logo_img}</td>
          <td style="text-align:center; vertical-align:middle;">
            <div style="font-size:12pt; font-weight:bold;">{clinic_name}</div>
            <div style="font-size:8.5pt; color:#444;">فیش حقوقی پرسنل</div>
          </td>
          <td style="width:120px; text-align:left; vertical-align:middle; font-size:7.5pt; color:#444;" dir="ltr">
            تاریخ چاپ: {_today_jalali_str()}
          </td>
        </tr>
      </table>

      <table width="100%" cellspacing="0" style="border:1px solid #333; border-collapse:collapse; margin-bottom:6px;">
        <tr>
          <td style="border:1px solid #333; padding:3px 6px; background:#f2f2f2; font-weight:bold; width:20%;">نام و نام خانوادگی</td>
          <td style="border:1px solid #333; padding:3px 6px; width:30%;">{payslip.full_name}</td>
          <td style="border:1px solid #333; padding:3px 6px; background:#f2f2f2; font-weight:bold; width:20%;">کد پرسنلی</td>
          <td style="border:1px solid #333; padding:3px 6px;" dir="ltr">{payslip.personnel_code or "—"}</td>
        </tr>
        <tr>
          <td style="border:1px solid #333; padding:3px 6px; background:#f2f2f2; font-weight:bold;">نوع استخدام</td>
          <td style="border:1px solid #333; padding:3px 6px;">{emp_type_display}</td>
          <td style="border:1px solid #333; padding:3px 6px; background:#f2f2f2; font-weight:bold;">دوره</td>
          <td style="border:1px solid #333; padding:3px 6px;">{payslip.period_label}</td>
        </tr>
        <tr>
          <td style="border:1px solid #333; padding:3px 6px; background:#f2f2f2; font-weight:bold;">ساعات عادی</td>
          <td style="border:1px solid #333; padding:3px 6px;" dir="ltr">{payslip.regular_hours:g}</td>
          <td style="border:1px solid #333; padding:3px 6px; background:#f2f2f2; font-weight:bold;">ساعات اضافه‌کاری</td>
          <td style="border:1px solid #333; padding:3px 6px;" dir="ltr">{payslip.overtime_hours:g}</td>
        </tr>
        <tr>
          <td style="border:1px solid #333; padding:3px 6px; background:#f2f2f2; font-weight:bold;">ساعات تعطیل</td>
          <td style="border:1px solid #333; padding:3px 6px;" dir="ltr">{payslip.holiday_hours:g}</td>
          <td style="border:1px solid #333; padding:3px 6px;"></td>
          <td style="border:1px solid #333; padding:3px 6px;"></td>
        </tr>
      </table>

      <table width="100%" cellspacing="0" style="border-collapse:collapse; margin-bottom:0;">
        <tr>
          <td width="50%" style="vertical-align:top; border:1px solid #333; padding:0;">
            <table width="100%" cellspacing="0" style="border-collapse:collapse; font-size:8.5pt;">
              <tr><td colspan="2" style="background:#dce7f2; font-weight:bold; padding:4px 6px; border-bottom:1px solid #333;">حقوق و مزایا</td></tr>
              {earnings_allowances_rows}
              <tr>
                <td style="padding:4px 6px; font-weight:bold; border-top:2px solid #333; background:#eef4fa;">جمع حقوق و مزایا</td>
                <td style="padding:4px 6px; font-weight:bold; border-top:2px solid #333; background:#eef4fa; text-align:left;" dir="ltr">{_fmt(payslip.gross_pay)}</td>
              </tr>
            </table>
          </td>
          <td width="50%" style="vertical-align:top; border:1px solid #333; border-right:none; padding:0;">
            <table width="100%" cellspacing="0" style="border-collapse:collapse; font-size:8.5pt;">
              <tr><td colspan="2" style="background:#f3dbdb; font-weight:bold; padding:4px 6px; border-bottom:1px solid #333;">کسورات</td></tr>
              {deductions_rows}
              <tr>
                <td style="padding:4px 6px; font-weight:bold; border-top:2px solid #333; background:#faeeee;">جمع کسورات</td>
                <td style="padding:4px 6px; font-weight:bold; border-top:2px solid #333; background:#faeeee; text-align:left;" dir="ltr">{_fmt(payslip.total_deductions)}</td>
              </tr>
            </table>
          </td>
        </tr>
      </table>

      {leave_section}

      <table width="100%" cellspacing="0" style="border:2px solid #222; border-collapse:collapse; margin-top:6px;">
        <tr>
          <td style="padding:6px 8px; font-size:10.5pt; font-weight:bold; width:35%;">خالص پرداختی</td>
          <td style="padding:6px 8px; font-size:10.5pt; font-weight:bold; text-align:left;" dir="ltr">{_fmt(payslip.net_pay)} ریال</td>
        </tr>
        <tr>
          <td colspan="2" style="padding:4px 8px; font-size:7.5pt; color:#333; border-top:1px solid #999;">
            {words}
          </td>
        </tr>
      </table>

      <table width="100%" style="margin-top:22px;">
        <tr>
          <td style="font-size:7.5pt; color:#555;">امضا و اثر انگشت دریافت‌کننده: .......................................</td>
          <td style="font-size:7.5pt; color:#555; text-align:left;" dir="ltr">امضا و مهر واحد مالی: .......................................</td>
        </tr>
      </table>
    </div>
    {attendance_section}
    """


class PayslipDialog(QDialog):
    def __init__(self, conn: sqlite3.Connection, payslip: Payslip, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.payslip = payslip
        self.setWindowTitle(f"فیش حقوقی — {payslip.full_name}")
        self.setLayoutDirection(Qt.RightToLeft)

        # Cap the requested size to what's actually available on THIS screen
        # (minus a margin for the taskbar/title bar). Previously this was a
        # flat resize(650, 780) -- on a smaller display (e.g. a 1366x768
        # clinic PC), 780px doesn't fit, the window gets clipped by Windows,
        # and the button row (چاپ / ذخیره PDF / بستن) ends up rendered below
        # the visible screen area entirely -- present in the layout, but
        # unreachable. Capping here means the QTextEdit above the buttons
        # simply gets its own internal scrollbar instead, and the button row
        # always stays inside the visible window.
        screen = self.screen() or QGuiApplication.primaryScreen()
        avail_height = screen.availableGeometry().height() if screen else 780
        self.resize(650, min(780, max(400, avail_height - 80)))

        layout = QVBoxLayout(self)

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        # Force a light background regardless of OS/app dark theme -- this is
        # a paper document meant to be printed on white paper, so it should
        # always render light even when Pedram's other tabs stay dark-themed.
        # Without this, Windows dark mode tints the QTextEdit's palette dark,
        # and only cells with an explicit background color (set in the HTML)
        # end up readable -- e.g. the amount-in-words line was nearly
        # invisible (dark gray text on a dark background).
        self.preview.setStyleSheet("QTextEdit { background-color: white; color: #111; }")
        self.preview.setHtml(build_payslip_html(payslip))
        layout.addWidget(self.preview)

        btn_row = QHBoxLayout()
        print_btn = QPushButton("چاپ")
        print_btn.clicked.connect(self.on_print)
        btn_row.addWidget(print_btn)
        pdf_btn = QPushButton("ذخیره PDF")
        pdf_btn.clicked.connect(self.on_save_pdf)
        btn_row.addWidget(pdf_btn)
        btn_row.addStretch()
        close_btn = QPushButton(S.CANCEL)
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _make_printer(self) -> QPrinter:
        """Both print and PDF export use A5, per the requested payslip format
        -- a full A4 sheet is wasteful for a single payslip."""
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageLayout(
            QPageLayout(
                QPageSize(QPageSize.A5),
                QPageLayout.Portrait,
                QMarginsF(8, 8, 8, 8),
                QPageLayout.Millimeter,
            )
        )
        return printer

    def on_print(self):
        printer = self._make_printer()
        dialog = QPrintDialog(printer, self)
        if dialog.exec() == QDialog.Accepted:
            self.preview.document().print_(printer)

    def on_save_pdf(self):
        default_name = f"payslip_{self.payslip.full_name}_{self.payslip.period_start}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "ذخیره فیش حقوقی به‌صورت PDF", default_name, "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        printer = self._make_printer()
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        self.preview.document().print_(printer)
        QMessageBox.information(self, S.SAVED, f"فیش حقوقی در مسیر زیر ذخیره شد:\n{path}")


def open_payslip_dialog(
    conn: sqlite3.Connection,
    employee_id: int,
    period_start: datetime,
    period_end: datetime,
    period_label: str,
    parent=None,
) -> None:
    """Convenience entry point for callers (e.g. payroll_tab.py) that already
    know the period being viewed -- builds the Payslip and shows the dialog,
    or a warning if this employee has no payroll result for the period."""
    payslip = build_payslip(conn, employee_id, period_start, period_end, period_label)
    if payslip is None:
        QMessageBox.information(
            parent, S.MSG_NO_SELECTION,
            "برای این کارمند در این دوره نتیجهٔ حقوقی‌ای وجود ندارد (شمارهٔ دستگاه نامشخص است).",
        )
        return
    dlg = PayslipDialog(conn, payslip, parent)
    dlg.exec()