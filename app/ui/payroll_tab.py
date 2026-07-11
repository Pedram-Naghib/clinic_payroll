from __future__ import annotations
import sqlite3
from datetime import datetime, time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QMessageBox, QHeaderView, QLabel, QComboBox,
)

from app.core.attendance_engine import compute_and_persist_attendance, build_payroll_inputs
from app.core.payroll_engine import PayrollResult
from app.core.pay_rounding import calculate_payroll_batch  # rounds total_pay up to 1,000 Rial
from app.core.payroll_runs import find_existing_run, save_payroll_run
from app.core.jalali import jalali_to_gregorian
from app.ui.payslip_view import open_payslip_dialog
from app.ui import strings_fa as S


def _numeric_item(value: int | float | None, display: str | None = None) -> QTableWidgetItem:
    item = QTableWidgetItem()
    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
    if value is None or value == "":
        item.setData(Qt.DisplayRole, "")
        item.setData(Qt.EditRole, 0)
    else:
        item.setData(Qt.EditRole, float(value))
        item.setData(Qt.DisplayRole, display if display is not None else f"{int(value):,}")
    return item


def _text_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
    return item


# Store the employee DB id in this Qt role on the first column's cell item,
# so it survives column sorting (vertical header items do NOT move with
# rows when QTableWidget sorts -- only cell items do; see employees_tab.py
# for the same fix applied there).
_EMP_ID_ROLE = Qt.UserRole


class PayrollTab(QWidget):
    COLUMNS = [
        S.COL_PR_NAME, S.COL_PR_TYPE, S.COL_PR_REGULAR_HOURS, S.COL_PR_OVERTIME_HOURS,
        S.COL_PR_HOLIDAY_HOURS, S.COL_PR_BASE_PAY, S.COL_PR_OVERTIME_PAY,
        S.COL_PR_HOLIDAY_PAY, S.COL_PR_ALLOWANCES, S.COL_PR_LEAVE_COVERED,
        S.COL_PR_UNDER_HOURS, S.COL_PR_INSURANCE, S.COL_PR_TOTAL,
    ]

    def __init__(self, conn: sqlite3.Connection):
        super().__init__()
        self.conn = conn
        self.setLayoutDirection(Qt.RightToLeft)
        self._last_results: list[PayrollResult] = []
        self._last_period: tuple[str, str] | None = None  # (period_start, period_end) ISO
        self._last_period_dt: tuple[datetime, datetime] | None = None
        self._last_period_label: str = ""

        layout = QVBoxLayout(self)

        info = QLabel(S.PAYROLL_INFO)
        info.setWordWrap(True)
        layout.addWidget(info)

        # --- Top controls row ---
        controls = QHBoxLayout()

        controls.addWidget(QLabel(S.LBL_YEAR + ":"))
        self.year_combo = QComboBox()
        for y in range(1402, 1410):
            self.year_combo.addItem(str(y), userData=y)
        controls.addWidget(self.year_combo)

        controls.addWidget(QLabel(S.LBL_MONTH + ":"))
        self.month_combo = QComboBox()
        for i, name in enumerate(S.PERSIAN_MONTHS, start=1):
            self.month_combo.addItem(name, userData=i)
        controls.addWidget(self.month_combo)

        run_btn = QPushButton(S.BTN_RUN_PAYROLL)
        run_btn.clicked.connect(self.on_run)
        controls.addWidget(run_btn)

        controls.addStretch()

        self.payslip_btn = QPushButton(S.BTN_SHOW_PAYSLIP)
        self.payslip_btn.clicked.connect(self.on_payslip)
        self.payslip_btn.setEnabled(False)
        controls.addWidget(self.payslip_btn)

        self.save_btn = QPushButton(S.BTN_SAVE_PAYROLL_RUN)
        self.save_btn.clicked.connect(self.on_save)
        self.save_btn.setEnabled(False)
        controls.addWidget(self.save_btn)

        layout.addLayout(controls)

        # --- Warnings (skipped employees) ---
        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet("color: #b35900;")
        layout.addWidget(self.warning_label)

        # --- Results table ---
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        # Interactive (draggable) on every column, including the name column --
        # it used to be forced to Stretch, which squeezed it down to near-zero
        # width whenever the other 12 columns didn't all fit the viewport.
        # Widths are auto-sized to content once results are rendered (see
        # _render_results), and the user can still drag any border afterwards.
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        # --- Total summary ---
        self.total_label = QLabel("")
        self.total_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.total_label)

    # ----------- Period helpers -----------

    def _current_period(self) -> tuple[int, int, datetime, datetime] | None:
        jy = self.year_combo.currentData()
        jm = self.month_combo.currentData()
        if jy is None or jm is None:
            return None
        period_start_d = jalali_to_gregorian(jy, jm, 1)
        if jm < 12:
            period_end_d = jalali_to_gregorian(jy, jm + 1, 1)
        else:
            period_end_d = jalali_to_gregorian(jy + 1, 1, 1)
        period_start = datetime.combine(period_start_d, time(0, 0, 0))
        period_end = datetime.combine(period_end_d, time(0, 0, 0))
        return jy, jm, period_start, period_end

    # ----------- Actions -----------

    def on_run(self):
        period = self._current_period()
        if period is None:
            return
        jy, jm, period_start, period_end = period

        # Re-derive daily_attendance from raw punches for this period first,
        # per standing instruction, so payroll never runs against stale hours.
        compute_and_persist_attendance(self.conn, period_start, period_end)

        inputs = build_payroll_inputs(self.conn, period_start, period_end)
        results, skipped_ids = calculate_payroll_batch(self.conn, inputs)

        self._last_results = results
        self._last_period = (period_start.date().isoformat(), period_end.date().isoformat())
        self._last_period_dt = (period_start, period_end)
        self._last_period_label = f"{self.month_combo.currentText()} {jy}"

        self._render_results(results)
        self._render_skipped(skipped_ids)

        self.save_btn.setEnabled(bool(results))
        self.payslip_btn.setEnabled(bool(results))

    def _render_skipped(self, skipped_ids: list[int]):
        if not skipped_ids:
            self.warning_label.setText("")
            return
        names = []
        for emp_id in skipped_ids:
            row = self.conn.execute(
                "SELECT full_name FROM employees WHERE id = ?", (emp_id,)
            ).fetchone()
            names.append(row["full_name"] if row else str(emp_id))
        self.warning_label.setText(
            S.MSG_SKIPPED_EMPLOYEES.format(n=len(skipped_ids), names="، ".join(names))
        )

    def _render_results(self, results: list[PayrollResult]):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(results))
        gray = QBrush(QColor(160, 160, 160))

        grand_total = 0
        for r, res in enumerate(results):
            grand_total += res.total_pay
            # Vertical header is a display-only convenience -- the row's real
            # employee id is stored in the name cell's UserRole below, since
            # vertical header items don't move with rows when the table is
            # sorted (see _selected_employee_id / employees_tab.py).
            self.table.setVerticalHeaderItem(r, QTableWidgetItem(str(res.employee_id)))

            type_display = S.EMP_TYPE_DISPLAY.get(res.employment_type, res.employment_type)

            name_item = _text_item(res.full_name)
            name_item.setData(_EMP_ID_ROLE, res.employee_id)

            cells = [
                name_item,
                _text_item(type_display),
                _numeric_item(res.regular_hours, display=f"{res.regular_hours:g}"),
                _numeric_item(res.overtime_hours, display=f"{res.overtime_hours:g}"),
                _numeric_item(res.holiday_hours, display=f"{res.holiday_hours:g}"),
                _numeric_item(res.base_pay),
                _numeric_item(res.overtime_pay),
                _numeric_item(res.holiday_pay),
                _numeric_item(res.allowances_total),
                _numeric_item(res.leave_days_covered, display=f"{res.leave_days_covered:g}"),
                _numeric_item(res.under_hours_deduction),
                _numeric_item(res.insurance_deduction),
                _numeric_item(res.total_pay),
            ]
            if res.allowances:
                cells[8].setToolTip(
                    "\n".join(f"{a.label}: {a.amount:,}" for a in res.allowances)
                )
            if res.leave_days_covered:
                cells[9].setToolTip(S.TOOLTIP_LEAVE_COVERED)
            if res.under_hours_deduction:
                cells[10].setToolTip(S.TOOLTIP_UNDER_HOURS)
            for c, item in enumerate(cells):
                if res.pay_mode == "fixed_no_clocking":
                    item.setForeground(gray)
                self.table.setItem(r, c, item)

        self.table.setSortingEnabled(True)

        # Auto-size every column to its content/header now that the table is
        # populated (columns stay Interactive afterwards, so the user can
        # still drag any border to fine-tune). The name column gets an extra
        # floor width since full_name is the one users complained was
        # unreadable when squeezed.
        self.table.resizeColumnsToContents()
        if self.table.columnWidth(0) < 130:
            self.table.setColumnWidth(0, 130)

        self.total_label.setText(S.LBL_PAYROLL_TOTAL.format(total=grand_total))

    def _selected_employee_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        name_item = self.table.item(row, 0)
        if name_item is None:
            return None
        emp_id = name_item.data(_EMP_ID_ROLE)
        return int(emp_id) if emp_id is not None else None

    def on_payslip(self):
        if not self._last_results or self._last_period_dt is None:
            QMessageBox.information(self, S.MSG_NO_SELECTION, S.MSG_NO_RESULTS_TO_SAVE)
            return
        emp_id = self._selected_employee_id()
        if emp_id is None:
            QMessageBox.information(self, S.MSG_NO_SELECTION, S.MSG_SELECT_EMPLOYEE_FIRST)
            return
        period_start, period_end = self._last_period_dt
        open_payslip_dialog(self.conn, emp_id, period_start, period_end, self._last_period_label, parent=self)

    def on_save(self):
        if not self._last_results or self._last_period is None:
            QMessageBox.information(self, S.MSG_NO_SELECTION, S.MSG_NO_RESULTS_TO_SAVE)
            return

        period_start, period_end = self._last_period
        existing = find_existing_run(self.conn, period_start, period_end)
        overwrite_run_id = None
        if existing is not None:
            jy = self.year_combo.currentData()
            month_label = self.month_combo.currentText()
            confirm = QMessageBox.question(
                self, S.MSG_CONFIRM_DELETE,
                S.MSG_CONFIRM_OVERWRITE_RUN.format(
                    month_label=month_label, year=jy, generated_at=existing["generated_at"],
                ),
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return
            overwrite_run_id = existing["id"]

        run_id = save_payroll_run(
            self.conn, period_start, period_end, self._last_results,
            overwrite_run_id=overwrite_run_id,
        )
        QMessageBox.information(self, S.SAVED, S.MSG_PAYROLL_RUN_SAVED.format(run_id=run_id))