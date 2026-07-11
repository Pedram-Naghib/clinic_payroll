from __future__ import annotations
import sqlite3
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QMessageBox, QHeaderView, QLabel,
    QComboBox, QLineEdit,
)

from app.core.leave import (
    LeaveRequestInput, create_leave_request, cancel_leave_request, list_leave_requests,
    get_leave_balance, days_used_this_jalali_year, compute_year_end_payout, settle_year_end_payout,
)
from app.core.employees import list_employees
from app.core.config import get_config
from app.core.jalali import parse_jalali_str, to_jalali_str, gregorian_to_jalali
from app.ui import strings_fa as S


def _numeric_item(value: int | float | None, display: str | None = None) -> QTableWidgetItem:
    item = QTableWidgetItem()
    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
    if value is None or value == "":
        item.setData(Qt.DisplayRole, "")
        item.setData(Qt.EditRole, 0)
    else:
        item.setData(Qt.EditRole, float(value))
        item.setData(Qt.DisplayRole, display if display is not None else f"{value:g}")
    return item


def _text_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
    return item


class LeaveTab(QWidget):
    COLUMNS = [
        S.COL_LEAVE_EMPLOYEE, S.COL_LEAVE_TYPE, S.COL_LEAVE_START, S.COL_LEAVE_END,
        S.COL_LEAVE_DAYS, S.COL_LEAVE_STATUS, S.COL_LEAVE_SOURCE, S.COL_LEAVE_NOTES,
    ]

    def __init__(self, conn: sqlite3.Connection):
        super().__init__()
        self.conn = conn
        self.setLayoutDirection(Qt.RightToLeft)
        self._row_ids: list[int] = []
        self._row_sources: list[str] = []

        layout = QVBoxLayout(self)

        info = QLabel(S.LEAVE_INFO)
        info.setWordWrap(True)
        layout.addWidget(info)

        # --- Entry form ---
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self.employee_combo = QComboBox()
        self.employee_combo.currentIndexChanged.connect(self._update_balance_label)

        self.leave_type_combo = QComboBox()
        self.leave_type_combo.addItem(S.LEAVE_TYPE_VACATION, userData="vacation")
        self.leave_type_combo.addItem(S.LEAVE_TYPE_MEDICAL, userData="medical")

        self.start_date_edit = QLineEdit()
        self.start_date_edit.setText(to_jalali_str(date.today()))
        self.start_date_edit.setPlaceholderText(S.LBL_SERVICE_DATE_HINT)

        self.end_date_edit = QLineEdit()
        self.end_date_edit.setText(to_jalali_str(date.today()))
        self.end_date_edit.setPlaceholderText(S.LBL_SERVICE_DATE_HINT)

        self.days_edit = QLineEdit()
        self.days_edit.setPlaceholderText("1")

        self.notes_edit = QLineEdit()

        self.balance_label = QLabel(S.LBL_LEAVE_BALANCE_EMPTY)
        self.balance_label.setStyleSheet("color: #888; font-weight: bold;")

        form.addRow(S.LBL_EMPLOYEE, self.employee_combo)
        form.addRow(S.LBL_LEAVE_TYPE, self.leave_type_combo)
        form.addRow(S.LBL_START_DATE, self.start_date_edit)
        form.addRow(S.LBL_END_DATE, self.end_date_edit)
        form.addRow(S.LBL_DAYS_COUNT, self.days_edit)
        form.addRow(S.LBL_LEAVE_NOTES, self.notes_edit)
        form.addRow("", self.balance_label)

        layout.addLayout(form)

        save_row = QHBoxLayout()
        save_btn = QPushButton(S.BTN_SAVE_LEAVE)
        save_btn.clicked.connect(self.on_save)
        save_row.addWidget(save_btn)
        settle_btn = QPushButton(S.BTN_SETTLE_YEAR_END)
        settle_btn.clicked.connect(self.on_settle_year_end)
        save_row.addWidget(settle_btn)
        save_row.addStretch()
        layout.addLayout(save_row)

        # --- History ---
        history_controls = QHBoxLayout()
        history_controls.addWidget(QLabel(S.LBL_EMPLOYEE))
        self.filter_combo = QComboBox()
        self.filter_combo.currentIndexChanged.connect(self.load_history)
        history_controls.addWidget(self.filter_combo)
        history_controls.addStretch()
        self.delete_btn = QPushButton(S.BTN_DELETE_LEAVE)
        self.delete_btn.clicked.connect(self.on_delete)
        history_controls.addWidget(self.delete_btn)
        refresh_btn = QPushButton(S.REFRESH)
        refresh_btn.clicked.connect(self.load_history)
        history_controls.addWidget(refresh_btn)
        layout.addLayout(history_controls)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        self._load_employees()
        self.load_history()
        self._update_balance_label()

    # ----------- Data loading -----------

    def _load_employees(self):
        employees = list_employees(self.conn, active_only=True)
        self.employee_combo.clear()
        self.filter_combo.clear()
        self.filter_combo.addItem(S.FILTER_ALL_EMPLOYEES, userData=None)
        for emp in employees:
            self.employee_combo.addItem(emp["full_name"], userData=emp["id"])
            self.filter_combo.addItem(emp["full_name"], userData=emp["id"])

    def load_history(self):
        emp_id = self.filter_combo.currentData() if self.filter_combo.count() else None
        rows = list_leave_requests(self.conn, employee_id=emp_id)

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        self._row_ids = []
        self._row_sources = []
        gray = QBrush(QColor(160, 160, 160))

        for r, row in enumerate(rows):
            self._row_ids.append(row["id"])
            self._row_sources.append(row["source"])
            is_auto = row["source"] == "auto_shortfall"

            cells = [
                _text_item(row["employee_name"]),
                _text_item(S.LEAVE_TYPE_DISPLAY.get(row["leave_type"], row["leave_type"])),
                _text_item(to_jalali_str(date.fromisoformat(row["start_date"]))),
                _text_item(to_jalali_str(date.fromisoformat(row["end_date"]))),
                _numeric_item(row["days_count"], display=f"{row['days_count']:g}"),
                _text_item(S.LEAVE_STATUS_DISPLAY.get(row["status"], row["status"])),
                _text_item(S.LEAVE_SOURCE_DISPLAY.get(row["source"], row["source"])),
                _text_item(row["notes"] or ""),
            ]
            for c, item in enumerate(cells):
                if is_auto:
                    item.setForeground(gray)
                self.table.setItem(r, c, item)

        self.table.setSortingEnabled(True)

    # ----------- Live balance label -----------

    def _update_balance_label(self):
        emp_id = self.employee_combo.currentData()
        if emp_id is None:
            self.balance_label.setText(S.LBL_LEAVE_BALANCE_EMPTY)
            return
        name = self.employee_combo.currentText()
        balance = get_leave_balance(self.conn, emp_id)
        cap = get_config(self.conn, "annual_paid_leave_days_cap", default=30)
        jy, _, _ = gregorian_to_jalali(date.today().year, date.today().month, date.today().day)
        used = days_used_this_jalali_year(self.conn, emp_id, jy)
        self.balance_label.setText(
            S.LBL_LEAVE_BALANCE.format(name=name, balance=balance, cap=cap, used=used)
        )

    # ----------- Actions -----------

    def on_save(self):
        emp_id = self.employee_combo.currentData()
        if emp_id is None:
            QMessageBox.warning(self, S.MSG_NO_EMPLOYEE, S.MSG_SELECT_EMPLOYEE_FIRST)
            return

        try:
            start_date = parse_jalali_str(self.start_date_edit.text()).isoformat()
            end_date = parse_jalali_str(self.end_date_edit.text()).isoformat()
        except Exception:
            QMessageBox.warning(self, S.MSG_INVALID_DATE, S.MSG_DATE_FORMAT_HINT)
            return

        try:
            days_count = float(self.days_edit.text().strip() or "0")
        except ValueError:
            days_count = 0
        if days_count <= 0:
            QMessageBox.warning(self, S.MSG_INVALID_VALUE, S.LBL_DAYS_COUNT)
            return

        leave_type = self.leave_type_combo.currentData()
        notes = self.notes_edit.text().strip() or None

        try:
            create_leave_request(
                self.conn,
                LeaveRequestInput(
                    employee_id=emp_id, leave_type=leave_type,
                    start_date=start_date, end_date=end_date,
                    days_count=days_count, notes=notes,
                ),
            )
        except ValueError as e:
            QMessageBox.critical(self, S.MSG_LEAVE_ERROR, str(e))
            return

        QMessageBox.information(self, S.SAVED, S.MSG_LEAVE_SAVED)
        self.days_edit.clear()
        self.notes_edit.clear()
        self.load_history()
        self._update_balance_label()

    def on_delete(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._row_ids):
            QMessageBox.information(self, S.MSG_NO_SELECTION, S.MSG_NO_LEAVE_SELECTION)
            return
        confirm = QMessageBox.question(
            self, S.MSG_CONFIRM_DELETE, S.MSG_CONFIRM_DELETE_LEAVE,
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            cancel_leave_request(self.conn, self._row_ids[row])
        except ValueError as e:
            QMessageBox.warning(self, S.MSG_CANNOT_DELETE_LEAVE, str(e))
            return
        self.load_history()
        self._update_balance_label()

    def on_settle_year_end(self):
        emp_id = self.employee_combo.currentData()
        if emp_id is None:
            QMessageBox.warning(self, S.MSG_NO_EMPLOYEE, S.MSG_SELECT_EMPLOYEE_FIRST)
            return
        name = self.employee_combo.currentText()
        balance = get_leave_balance(self.conn, emp_id)
        amount = compute_year_end_payout(self.conn, emp_id)
        if amount <= 0:
            QMessageBox.information(self, S.MSG_NO_SELECTION, S.MSG_SETTLE_NO_BALANCE)
            return
        confirm = QMessageBox.question(
            self, S.MSG_CONFIRM_DELETE,
            S.MSG_CONFIRM_SETTLE.format(name=name, balance=balance, amount=amount),
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        paid = settle_year_end_payout(self.conn, emp_id)
        QMessageBox.information(self, S.SAVED, S.MSG_SETTLE_RESULT.format(amount=paid, name=name))
        self._update_balance_label()
