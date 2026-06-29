from __future__ import annotations
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QMessageBox, QHeaderView, QLabel, QCheckBox,
)

from app.ui import strings_fa as S


class AllowancesTab(QWidget):
    # Column order: label (Persian) first, then toggles, then source, code last
    COLUMNS = [
        S.COL_LABEL, S.COL_ENABLED, S.COL_APPLIES_INSURED,
        S.COL_APPLIES_NON_INSURED, S.COL_AMOUNT_SOURCE, S.COL_CODE,
    ]

    def __init__(self, conn: sqlite3.Connection):
        super().__init__()
        self.conn = conn
        self.setLayoutDirection(Qt.RightToLeft)
        self._checkboxes: dict[tuple[int, str], QCheckBox] = {}

        layout = QVBoxLayout(self)
        info = QLabel(S.ALLOWANCES_INFO)
        info.setWordWrap(True)
        layout.addWidget(info)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)  # label
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)  # amount source
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        save_btn = QPushButton(S.SAVE_CHANGES)
        save_btn.clicked.connect(self.on_save)
        refresh_btn = QPushButton(S.REFRESH)
        refresh_btn.clicked.connect(self.load_data)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.load_data()

    def _amount_source_label(self, row: sqlite3.Row) -> str:
        """Human-readable Persian description of where each allowance's amount comes from."""
        amount_type = row["amount_type"]
        if amount_type == "config_flat":
            cfg_label = S.t_config_label(row["config_key"], row["config_key"])
            return S.SRC_CONFIG.format(key=cfg_label)
        if amount_type == "config_per_child":
            cfg_label = S.t_config_label(row["config_key"], row["config_key"])
            return S.SRC_CONFIG_PER_CHILD.format(key=cfg_label)
        if amount_type == "employee_field_flat":
            field_label = S.t_emp_field(row["employee_field"])
            return S.SRC_EMP_FIELD.format(field=field_label)
        if amount_type == "employee_field_per_hour":
            field_label = S.t_emp_field(row["employee_field"])
            return S.SRC_EMP_FIELD_PER_HOUR.format(field=field_label)
        return amount_type

    def load_data(self):
        self.table.setSortingEnabled(False)
        rows = self.conn.execute(
            "SELECT * FROM allowance_definitions ORDER BY sort_order"
        ).fetchall()
        self.table.setRowCount(len(rows))
        self._checkboxes.clear()
        self._codes_by_row = []

        for r, row in enumerate(rows):
            self._codes_by_row.append(row["code"])

            # 0: Persian label
            label_fa = S.t_allowance_label(row["code"], row["label"])
            label_item = QTableWidgetItem(label_fa)
            label_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.table.setItem(r, 0, label_item)

            # 1-3: enabled / applies_to_insured / applies_to_non_insured checkboxes
            for col, field in [(1, "enabled"), (2, "applies_to_insured"), (3, "applies_to_non_insured")]:
                cb = QCheckBox()
                cb.setChecked(bool(row[field]))
                cb.setLayoutDirection(Qt.LeftToRight)
                marker = QTableWidgetItem()
                marker.setData(Qt.EditRole, int(bool(row[field])))
                marker.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                self.table.setItem(r, col, marker)
                self.table.setCellWidget(r, col, cb)
                self._checkboxes[(r, field)] = cb

            # 4: amount source (Persian)
            source_item = QTableWidgetItem(self._amount_source_label(row))
            source_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.table.setItem(r, 4, source_item)

            # 5: code (stable English identifier, shown last)
            code_item = QTableWidgetItem(row["code"])
            code_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.table.setItem(r, 5, code_item)

        self.table.setSortingEnabled(True)

    def on_save(self):
        for r, code in enumerate(self._codes_by_row):
            enabled = int(self._checkboxes[(r, "enabled")].isChecked())
            applies_insured = int(self._checkboxes[(r, "applies_to_insured")].isChecked())
            applies_non_insured = int(self._checkboxes[(r, "applies_to_non_insured")].isChecked())
            self.conn.execute(
                """UPDATE allowance_definitions
                   SET enabled = ?, applies_to_insured = ?, applies_to_non_insured = ?,
                       updated_at = datetime('now')
                   WHERE code = ?""",
                (enabled, applies_insured, applies_non_insured, code),
            )
        self.conn.commit()
        QMessageBox.information(self, S.SAVED, S.MSG_ALLOWANCES_SAVED)