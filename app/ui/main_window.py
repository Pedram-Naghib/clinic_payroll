"""
Owner Dashboard — main application entry point.

Run with:  python -m app.ui.main_window
"""

from __future__ import annotations
import sys
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget

from app.db.database import get_connection, init_db
from app.core.holidays import run_startup_holiday_seed
from app.core.jalali import gregorian_to_jalali
from app.ui.config_tab import ConfigTab
from app.ui.allowances_tab import AllowancesTab
from app.ui.employees_tab import EmployeesTab
from app.ui.attendance_tab import AttendanceTab
from app.ui.commissions_tab import CommissionsTab
from app.ui.payroll_tab import PayrollTab
from app.ui import strings_fa as S


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(S.APP_TITLE)
        self.resize(1200, 720)
        # Force RTL layout on the whole window (Persian)
        self.setLayoutDirection(Qt.RightToLeft)

        self.conn = get_connection()

        # Seed/refresh the iranian_holidays table for the current + next
        # Jalali year. Idempotent, safe to run on every launch.
        current_jy, _, _ = gregorian_to_jalali(date.today().year, date.today().month, date.today().day)
        run_startup_holiday_seed(self.conn, current_jy)

        tabs = QTabWidget()
        self.employees_tab = EmployeesTab(self.conn)
        self.attendance_tab = AttendanceTab(self.conn)
        self.allowances_tab = AllowancesTab(self.conn)
        self.commissions_tab = CommissionsTab(self.conn)
        self.payroll_tab = PayrollTab(self.conn)
        self.config_tab = ConfigTab(self.conn)

        tabs.addTab(self.employees_tab, S.TAB_EMPLOYEES)
        tabs.addTab(self.attendance_tab, S.TAB_ATTENDANCE)
        tabs.addTab(self.allowances_tab, S.TAB_ALLOWANCES)
        tabs.addTab(self.commissions_tab, S.TAB_COMMISSIONS)
        tabs.addTab(self.payroll_tab, S.TAB_PAYROLL)
        tabs.addTab(self.config_tab, S.TAB_CONFIG)

        self.setCentralWidget(tabs)


def main():
    init_db()
    app = QApplication(sys.argv)
    # App-wide RTL + a Persian-friendly font shipped on most systems.
    app.setLayoutDirection(Qt.RightToLeft)
    app.setFont(QFont("Tahoma", 10))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()