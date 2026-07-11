from __future__ import annotations
import sqlite3
from datetime import date, datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrinter, QPrintDialog
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QFileDialog, QMessageBox,
)

from app.core.payslip import Payslip, build_payslip
from app.ui import strings_fa as S

_EMP_TYPE_DISPLAY = {"insured": "بیمه‌شده", "non_insured": "بیمه نشده"}


def _fmt(n: int | float) -> str:
    return f"{n:,.0f}"


def _row(label: str, amount: int, bold: bool = False) -> str:
    style = "font-weight:bold;" if bold else ""
    return (
        f"<tr><td style='padding:4px 8px;{style}'>{label}</td>"
        f"<td style='padding:4px 8px;text-align:left;{style}' dir='ltr'>{_fmt(amount)}</td></tr>"
    )


def _section_table(title: str, lines: list, total: int, total_label: str) -> str:
    if not lines:
        rows = "<tr><td style='padding:4px 8px;color:#888;'>—</td><td></td></tr>"
    else:
        rows = "".join(_row(l.label, l.amount) for l in lines)
    return f"""
    <table width="100%" cellspacing="0" style="border:1px solid #ccc; margin-bottom:10px;">
      <tr><td colspan="2" style="background:#f0f0f0; padding:6px 8px; font-weight:bold;">{title}</td></tr>
      {rows}
      <tr style="border-top:1px solid #ccc;">{_row(total_label, total, bold=True)}</tr>
    </table>
    """


def build_payslip_html(payslip: Payslip, clinic_name: str = "درمانگاه") -> str:
    leave_rows = ""
    if payslip.leave_days_covered:
        leave_rows += (
            f"<tr><td style='padding:4px 8px;'>پوشش کسری کارکرد از موجودی مرخصی</td>"
            f"<td style='padding:4px 8px;text-align:left;' dir='ltr'>"
            f"{payslip.leave_days_covered:g} روز</td></tr>"
        )
    if payslip.uncovered_shortfall_hours:
        leave_rows += (
            f"<tr><td style='padding:4px 8px;'>کمبود کارکرد پوشش‌داده‌نشده (کسر از حقوق)</td>"
            f"<td style='padding:4px 8px;text-align:left;' dir='ltr'>"
            f"{payslip.uncovered_shortfall_hours:g} ساعت</td></tr>"
        )
    if payslip.explicit_leave_days_taken:
        leave_rows += (
            f"<tr><td style='padding:4px 8px;'>مرخصی صریح استفاده‌شده در این دوره</td>"
            f"<td style='padding:4px 8px;text-align:left;' dir='ltr'>"
            f"{payslip.explicit_leave_days_taken:g} روز</td></tr>"
        )
    if not leave_rows:
        leave_rows = "<tr><td style='padding:4px 8px;color:#888;'>موردی ثبت نشده</td><td></td></tr>"

    earnings_html = _section_table("درآمدها (Earnings)", payslip.earnings, payslip.earnings_total, "جمع درآمدها")
    allowances_html = _section_table("مزایا (Allowances)", payslip.allowances, payslip.allowances_total, "جمع مزایا")
    deductions_html = _section_table("کسورات (Deductions)", payslip.deductions, payslip.deductions_total, "جمع کسورات")

    return f"""
    <div dir="rtl" style="font-family: Tahoma, sans-serif; font-size: 11pt;">
      <div style="text-align:center; margin-bottom: 14px;">
        <div style="font-size:14pt; font-weight:bold;">{clinic_name} — فیش حقوقی</div>
        <div style="color:#555;">دوره: {payslip.period_label}</div>
      </div>

      <table width="100%" style="margin-bottom:14px;">
        <tr>
          <td style="padding:2px 8px;"><b>نام و نام خانوادگی:</b> {payslip.full_name}</td>
          <td style="padding:2px 8px;"><b>نوع استخدام:</b> {_EMP_TYPE_DISPLAY.get(payslip.employment_type, payslip.employment_type)}</td>
        </tr>
        <tr>
          <td style="padding:2px 8px;"><b>ساعات عادی:</b> {payslip.regular_hours:g}</td>
          <td style="padding:2px 8px;"><b>ساعات اضافه‌کاری:</b> {payslip.overtime_hours:g}</td>
        </tr>
        <tr>
          <td style="padding:2px 8px;"><b>ساعات تعطیل:</b> {payslip.holiday_hours:g}</td>
          <td style="padding:2px 8px;"></td>
        </tr>
      </table>

      {earnings_html}
      {allowances_html}
      {deductions_html}

      <table width="100%" cellspacing="0" style="border:1px solid #ccc; margin-bottom:10px;">
        <tr><td colspan="2" style="background:#f0f0f0; padding:6px 8px; font-weight:bold;">مرخصی و کمبود کارکرد</td></tr>
        {leave_rows}
      </table>

      <table width="100%" cellspacing="0" style="border:2px solid #333; margin-top:6px;">
        <tr>
          <td style="padding:8px; font-size:12pt; font-weight:bold;">خالص پرداختی</td>
          <td style="padding:8px; font-size:12pt; font-weight:bold; text-align:left;" dir="ltr">
            {_fmt(payslip.net_pay)} ریال
          </td>
        </tr>
      </table>
    </div>
    """


class PayslipDialog(QDialog):
    def __init__(self, conn: sqlite3.Connection, payslip: Payslip, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.payslip = payslip
        self.setWindowTitle(f"فیش حقوقی — {payslip.full_name}")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(650, 780)

        layout = QVBoxLayout(self)

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
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

    def on_print(self):
        printer = QPrinter(QPrinter.HighResolution)
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
        printer = QPrinter(QPrinter.HighResolution)
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
