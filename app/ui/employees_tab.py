from __future__ import annotations
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QMessageBox, QHeaderView, QLabel, QDialog, QFormLayout,
    QLineEdit, QComboBox, QCheckBox, QSpinBox, QDialogButtonBox, QTextEdit,
)
from PySide6.QtGui import QColor, QBrush

from app.core.employees import EmployeeInput, add_employee, update_employee, delete_employee
from app.ui import strings_fa as S


def _numeric_item(value: int | float | None, display: str | None = None) -> QTableWidgetItem:
    """Item that sorts numerically (uses EditRole) but displays formatted text."""
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


class EmployeeDialog(QDialog):
    """Add/Edit form covering every employee field."""

    def __init__(self, parent=None, employee: sqlite3.Row | None = None):
        super().__init__(parent)
        self.employee = employee
        self.setWindowTitle(S.DLG_EDIT_EMPLOYEE if employee else S.DLG_ADD_EMPLOYEE)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(460)

        layout = QFormLayout(self)
        layout.setLabelAlignment(Qt.AlignRight)

        self.name_edit = QLineEdit()
        self.type_combo = QComboBox()
        # User-facing display values are Persian; we map to/from DB values 'insured'/'non_insured'.
        self.type_combo.addItem(S.EMP_TYPE_INSURED, userData="insured")
        self.type_combo.addItem(S.EMP_TYPE_NON_INSURED, userData="non_insured")
        self.enroll_edit = QLineEdit()
        self.enroll_edit.setPlaceholderText(S.LBL_DEVICE_ID_HINT)
        self.exempt_check = QCheckBox(S.LBL_EXEMPT)

        self.fixed_salary_edit = QLineEdit()
        self.fixed_salary_edit.setPlaceholderText(S.LBL_FIXED_SALARY_HINT)
        self.hourly_rate_edit = QLineEdit()
        self.hourly_rate_edit.setPlaceholderText(S.LBL_HOURLY_RATE_HINT)

        self.housing_hourly_edit = QLineEdit()
        self.food_hourly_edit = QLineEdit()
        self.housing_fixed_edit = QLineEdit()
        self.food_fixed_edit = QLineEdit()

        self.married_check = QCheckBox(S.LBL_MARRIED)
        self.children_spin = QSpinBox()
        self.children_spin.setRange(0, 20)

        self.seniority_edit = QLineEdit()
        self.vacation_balance_edit = QLineEdit()
        self.notes_edit = QTextEdit()
        self.notes_edit.setFixedHeight(60)

        layout.addRow(S.LBL_FULL_NAME, self.name_edit)
        layout.addRow(S.LBL_EMP_TYPE, self.type_combo)
        layout.addRow(S.LBL_DEVICE_ID, self.enroll_edit)
        layout.addRow("", self.exempt_check)
        layout.addRow(S.LBL_FIXED_SALARY, self.fixed_salary_edit)
        layout.addRow(S.LBL_HOURLY_RATE, self.hourly_rate_edit)
        layout.addRow(S.LBL_HOUSING_HOURLY, self.housing_hourly_edit)
        layout.addRow(S.LBL_FOOD_HOURLY, self.food_hourly_edit)
        layout.addRow(S.LBL_HOUSING_FIXED, self.housing_fixed_edit)
        layout.addRow(S.LBL_FOOD_FIXED, self.food_fixed_edit)
        layout.addRow("", self.married_check)
        layout.addRow(S.LBL_CHILDREN, self.children_spin)
        layout.addRow(S.LBL_SENIORITY, self.seniority_edit)
        layout.addRow(S.LBL_VACATION_BALANCE, self.vacation_balance_edit)
        layout.addRow(S.LBL_NOTES, self.notes_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(S.OK)
        buttons.button(QDialogButtonBox.Cancel).setText(S.CANCEL)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if employee:
            self._populate_from_row(employee)

    def _populate_from_row(self, row: sqlite3.Row):
        self.name_edit.setText(row["full_name"] or "")
        # Find combo index by stored DB value
        for i in range(self.type_combo.count()):
            if self.type_combo.itemData(i) == row["employment_type"]:
                self.type_combo.setCurrentIndex(i)
                break
        self.enroll_edit.setText(row["device_enroll_no"] or "")
        self.exempt_check.setChecked(bool(row["is_exempt_from_shifts"]))
        self.fixed_salary_edit.setText(str(row["fixed_monthly_salary"]) if row["fixed_monthly_salary"] is not None else "")
        self.hourly_rate_edit.setText(str(row["base_hourly_rate"]) if row["base_hourly_rate"] is not None else "")
        self.housing_hourly_edit.setText(str(row["housing_allowance_per_hour"] or 0))
        self.food_hourly_edit.setText(str(row["food_allowance_per_hour"] or 0))
        self.housing_fixed_edit.setText(str(row["fixed_housing_allowance"] or 0))
        self.food_fixed_edit.setText(str(row["fixed_food_allowance"] or 0))
        self.married_check.setChecked(bool(row["is_married"]))
        self.children_spin.setValue(row["number_of_children"] or 0)
        self.seniority_edit.setText(str(row["seniority_allowance"] or 0))
        self.vacation_balance_edit.setText(str(row["vacation_balance_days"] or 0))
        self.notes_edit.setPlainText(row["notes"] or "")

    def get_employee_input(self) -> EmployeeInput:
        def _int_or_none(text: str) -> int | None:
            text = text.strip().replace(",", "")
            return int(text) if text else None

        def _int_or_zero(text: str) -> int:
            return _int_or_none(text) or 0

        return EmployeeInput(
            full_name=self.name_edit.text().strip(),
            employment_type=self.type_combo.currentData() or "insured",
            device_enroll_no=self.enroll_edit.text().strip() or None,
            is_exempt_from_shifts=self.exempt_check.isChecked(),
            fixed_monthly_salary=_int_or_none(self.fixed_salary_edit.text()),
            base_hourly_rate=_int_or_none(self.hourly_rate_edit.text()),
            housing_allowance_per_hour=_int_or_zero(self.housing_hourly_edit.text()),
            food_allowance_per_hour=_int_or_zero(self.food_hourly_edit.text()),
            fixed_housing_allowance=_int_or_zero(self.housing_fixed_edit.text()),
            fixed_food_allowance=_int_or_zero(self.food_fixed_edit.text()),
            is_married=self.married_check.isChecked(),
            number_of_children=self.children_spin.value(),
            seniority_allowance=_int_or_zero(self.seniority_edit.text()),
            vacation_balance_days=float(self.vacation_balance_edit.text() or 0),
            notes=self.notes_edit.toPlainText().strip() or None,
        )


class EmployeesTab(QWidget):
    # Columns shown in the table (vertical header shows employee ID instead of row number).
    COLUMNS = [
        S.COL_NAME, S.COL_TYPE, S.COL_DEVICE, S.COL_EXEMPT,
        S.COL_MONTHLY_SALARY, S.COL_HOURLY_RATE,
        S.COL_MARRIED, S.COL_CHILDREN, S.COL_ACTIVE,
    ]

    def __init__(self, conn: sqlite3.Connection):
        super().__init__()
        self.conn = conn
        self.setLayoutDirection(Qt.RightToLeft)

        layout = QVBoxLayout(self)

        info = QLabel(S.EMPLOYEES_INFO)
        info.setWordWrap(True)
        layout.addWidget(info)

        self.show_inactive_check = QCheckBox(S.SHOW_INACTIVE)
        self.show_inactive_check.stateChanged.connect(self.load_data)
        layout.addWidget(self.show_inactive_check)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setSortingEnabled(True)  # click headers to sort
        # vertical header shows the actual employee.id, not Qt's row counter
        self.table.verticalHeader().setVisible(True)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton(S.ADD_EMPLOYEE)
        self.add_btn.clicked.connect(self.on_add)
        self.edit_btn = QPushButton(S.EDIT_SELECTED)
        self.edit_btn.clicked.connect(self.on_edit)
        self.delete_btn = QPushButton(S.DELETE_SELECTED)
        self.delete_btn.clicked.connect(self.on_delete)
        self.refresh_btn = QPushButton(S.REFRESH)
        self.refresh_btn.clicked.connect(self.load_data)
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.edit_btn)
        btn_row.addWidget(self.delete_btn)
        btn_row.addWidget(self.refresh_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.load_data()

    def load_data(self):
        # Disable sorting during repopulation so rows don't get shuffled mid-insert.
        self.table.setSortingEnabled(False)

        show_inactive = self.show_inactive_check.isChecked()
        if show_inactive:
            rows = self.conn.execute(
                "SELECT * FROM employees ORDER BY active DESC, id"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM employees WHERE active = 1 ORDER BY id"
            ).fetchall()

        self.table.setRowCount(len(rows))
        self._row_ids = []
        gray = QBrush(QColor(160, 160, 160))

        for r, row in enumerate(rows):
            self._row_ids.append(row["id"])
            # vertical header = employee.id (the user's request: ID as row index)
            id_header = QTableWidgetItem(str(row["id"]))
            self.table.setVerticalHeaderItem(r, id_header)

            type_display = S.EMP_TYPE_DISPLAY.get(row["employment_type"], row["employment_type"])
            is_inactive = not row["active"]

            cells = [
                _text_item(row["full_name"] or ""),
                _text_item(type_display),
                _text_item(row["device_enroll_no"] or ""),
                _text_item(S.YES if row["is_exempt_from_shifts"] else S.NO),
                _numeric_item(row["fixed_monthly_salary"]),
                _numeric_item(row["base_hourly_rate"]),
                _text_item(S.YES if row["is_married"] else S.NO),
                _numeric_item(row["number_of_children"], display=str(row["number_of_children"] or 0)),
                _text_item(S.STATUS_ACTIVE if row["active"] else S.STATUS_INACTIVE),
            ]
            for c, item in enumerate(cells):
                if is_inactive:
                    item.setForeground(gray)
                self.table.setItem(r, c, item)

        self.table.setSortingEnabled(True)
        # Update delete button label depending on whether selection is active/inactive
        self.table.itemSelectionChanged.connect(self._refresh_delete_button)
        self._refresh_delete_button()

    def _selected_employee_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._row_ids):
            return None
        # Important: after sorting, row indexes don't match insertion order anymore.
        # The vertical header item still holds the employee ID — read from there.
        header_item = self.table.verticalHeaderItem(row)
        if header_item is None:
            return None
        try:
            return int(header_item.text())
        except ValueError:
            return None

    def _selected_employee_row(self) -> sqlite3.Row | None:
        emp_id = self._selected_employee_id()
        if emp_id is None:
            return None
        return self.conn.execute("SELECT * FROM employees WHERE id = ?", (emp_id,)).fetchone()

    def _refresh_delete_button(self):
        emp = self._selected_employee_row()
        if emp and not emp["active"]:
            self.delete_btn.setText(S.RESTORE_SELECTED)
        else:
            self.delete_btn.setText(S.DELETE_SELECTED)

    def on_add(self):
        dlg = EmployeeDialog(self)
        if dlg.exec() == QDialog.Accepted:
            emp = dlg.get_employee_input()
            if not emp.full_name:
                QMessageBox.warning(self, S.MSG_MISSING_NAME, S.MSG_NAME_REQUIRED)
                return
            add_employee(self.conn, emp)
            self.load_data()

    def on_edit(self):
        emp = self._selected_employee_row()
        if emp is None:
            QMessageBox.information(self, S.MSG_NO_SELECTION, S.MSG_SELECT_EMPLOYEE)
            return
        dlg = EmployeeDialog(self, employee=emp)
        if dlg.exec() == QDialog.Accepted:
            update_employee(self.conn, emp["id"], dlg.get_employee_input())
            self.load_data()

    def on_delete(self):
        emp = self._selected_employee_row()
        if emp is None:
            QMessageBox.information(self, S.MSG_NO_SELECTION, S.MSG_SELECT_EMPLOYEE)
            return
        # If already inactive -> restore instead
        if not emp["active"]:
            self.conn.execute("UPDATE employees SET active = 1 WHERE id = ?", (emp["id"],))
            self.conn.commit()
            self.load_data()
            return
        confirm = QMessageBox.question(
            self, S.MSG_CONFIRM_DELETE, S.MSG_DELETE_PROMPT,
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            delete_employee(self.conn, emp["id"], hard_delete=False)
            self.load_data()