from __future__ import annotations
import sqlite3
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QMessageBox, QHeaderView, QLabel,
    QComboBox, QLineEdit,
)

from app.core.commissions import (
    CommissionInput, add_commission, delete_commission, list_commissions,
    get_commission_rate, compute_commission_amount, SERVICE_TYPES,
)
from app.core.employees import list_employees
from app.core.roles import get_employees_with_role
from app.core.jalali import parse_jalali_str, to_jalali_str
from app.ui import strings_fa as S

BEHYAR_ROLE_NAME = "بهیار"  # the only role eligible for direct commissions per current clinic policy


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


class CommissionsTab(QWidget):
    COLUMNS = [
        S.COL_COMM_EMPLOYEE, S.COL_COMM_SERVICE, S.COL_COMM_FEE,
        S.COL_COMM_RATE, S.COL_COMM_AMOUNT, S.COL_COMM_DATE, S.COL_COMM_NOTES,
    ]

    def __init__(self, conn: sqlite3.Connection):
        super().__init__()
        self.conn = conn
        self.setLayoutDirection(Qt.RightToLeft)
        self._row_ids: list[int] = []

        layout = QVBoxLayout(self)

        info = QLabel(S.COMMISSIONS_INFO)
        info.setWordWrap(True)
        layout.addWidget(info)

        # --- Entry form ---
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self.employee_combo = QComboBox()
        self.service_combo = QComboBox()
        for code in SERVICE_TYPES:
            self.service_combo.addItem(S.SERVICE_TYPE_DISPLAY.get(code, code), userData=code)

        self.fee_edit = QLineEdit()
        self.fee_edit.setPlaceholderText("0")
        self.fee_edit.textChanged.connect(self._update_preview)
        self.service_combo.currentIndexChanged.connect(self._update_preview)

        self.date_edit = QLineEdit()
        self.date_edit.setText(to_jalali_str(date.today()))
        self.date_edit.setPlaceholderText(S.LBL_SERVICE_DATE_HINT)

        self.notes_edit = QLineEdit()

        self.preview_label = QLabel(S.LBL_COMMISSION_PREVIEW_EMPTY)
        self.preview_label.setStyleSheet("color: #888; font-weight: bold;")

        form.addRow(S.LBL_EMPLOYEE, self.employee_combo)
        form.addRow(S.LBL_SERVICE_TYPE, self.service_combo)
        form.addRow(S.LBL_FEE_TOMAN, self.fee_edit)
        form.addRow(S.LBL_SERVICE_DATE, self.date_edit)
        form.addRow(S.LBL_COMMISSION_NOTES, self.notes_edit)
        form.addRow("", self.preview_label)

        layout.addLayout(form)

        save_row = QHBoxLayout()
        save_btn = QPushButton(S.BTN_SAVE_COMMISSION)
        save_btn.clicked.connect(self.on_save)
        save_row.addWidget(save_btn)
        save_row.addStretch()
        layout.addLayout(save_row)

        # --- History ---
        history_controls = QHBoxLayout()
        history_controls.addWidget(QLabel(S.LBL_EMPLOYEE))
        self.filter_combo = QComboBox()
        self.filter_combo.currentIndexChanged.connect(self.load_history)
        history_controls.addWidget(self.filter_combo)
        history_controls.addStretch()
        self.delete_btn = QPushButton(S.BTN_DELETE_COMMISSION)
        self.delete_btn.clicked.connect(self.on_delete)
        history_controls.addWidget(self.delete_btn)
        refresh_btn = QPushButton(S.REFRESH)
        refresh_btn.clicked.connect(self.load_history)
        history_controls.addWidget(refresh_btn)
        layout.addLayout(history_controls)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        self._load_employees()
        self.load_history()
        self._update_preview()

    # ----------- Data loading -----------

    def _load_employees(self):
        behyar_employees = get_employees_with_role(self.conn, BEHYAR_ROLE_NAME, active_only=True)
        all_employees = list_employees(self.conn, active_only=True)

        self.employee_combo.clear()
        for emp in behyar_employees:
            self.employee_combo.addItem(emp["full_name"], userData=emp["id"])

        # History filter intentionally stays unfiltered (all active employees) so past
        # commission entries for someone who later lost the Behyar role are still visible.
        self.filter_combo.clear()
        self.filter_combo.addItem(S.FILTER_ALL_EMPLOYEES, userData=None)
        for emp in all_employees:
            self.filter_combo.addItem(emp["full_name"], userData=emp["id"])

    def load_history(self):
        emp_id = self.filter_combo.currentData() if self.filter_combo.count() else None
        rows = list_commissions(self.conn, employee_id=emp_id)

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        self._row_ids = []

        for r, row in enumerate(rows):
            self._row_ids.append(row["id"])
            service_display = S.SERVICE_TYPE_DISPLAY.get(row["service_type"], row["service_type"])
            jalali_date = to_jalali_str(date.fromisoformat(row["service_date"]))

            cells = [
                _text_item(row["employee_name"]),
                _text_item(service_display),
                _numeric_item(row["fee_received"]),
                _numeric_item(row["commission_rate"], display=f"{row['commission_rate']:g}٪"),
                _numeric_item(row["commission_amount"]),
                _text_item(jalali_date),
                _text_item(row["notes"] or ""),
            ]
            for c, item in enumerate(cells):
                self.table.setItem(r, c, item)

        self.table.setSortingEnabled(True)

    # ----------- Live preview -----------

    def _update_preview(self):
        service_type = self.service_combo.currentData()
        fee_toman = self._parse_fee(self.fee_edit.text())
        if not service_type or fee_toman is None or fee_toman <= 0:
            self.preview_label.setText(S.LBL_COMMISSION_PREVIEW_EMPTY)
            return
        try:
            rate = get_commission_rate(self.conn, service_type)
        except ValueError:
            self.preview_label.setText(S.LBL_COMMISSION_PREVIEW_EMPTY)
            return
        fee_rial = fee_toman * 10
        amount = compute_commission_amount(fee_rial, rate)
        self.preview_label.setText(S.LBL_COMMISSION_PREVIEW.format(rate=rate, amount=amount))

    @staticmethod
    def _parse_fee(text: str) -> int | None:
        text = text.strip().replace(",", "")
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None

    # ----------- Actions -----------

    def on_save(self):
        emp_id = self.employee_combo.currentData()
        if emp_id is None:
            QMessageBox.warning(self, S.MSG_NO_EMPLOYEE, S.MSG_SELECT_EMPLOYEE_FIRST)
            return

        fee_toman = self._parse_fee(self.fee_edit.text())
        if fee_toman is None or fee_toman <= 0:
            QMessageBox.warning(self, S.MSG_INVALID_FEE, S.MSG_FEE_REQUIRED)
            return

        try:
            service_date = parse_jalali_str(self.date_edit.text()).isoformat()
        except Exception:
            QMessageBox.warning(self, S.MSG_INVALID_DATE, S.MSG_DATE_FORMAT_HINT)
            return

        service_type = self.service_combo.currentData()
        fee_rial = fee_toman * 10
        notes = self.notes_edit.text().strip() or None

        add_commission(
            self.conn,
            CommissionInput(
                employee_id=emp_id,
                service_type=service_type,
                fee_received=fee_rial,
                service_date=service_date,
                notes=notes,
            ),
        )

        QMessageBox.information(self, S.SAVED, S.MSG_COMMISSION_SAVED)
        self.fee_edit.clear()
        self.notes_edit.clear()
        self.load_history()
        self._update_preview()

    def on_delete(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._row_ids):
            QMessageBox.information(self, S.MSG_NO_SELECTION, S.MSG_NO_COMMISSION_SELECTION)
            return
        confirm = QMessageBox.question(
            self, S.MSG_CONFIRM_DELETE, S.MSG_CONFIRM_DELETE_COMMISSION,
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            delete_commission(self.conn, self._row_ids[row])
            self.load_history()