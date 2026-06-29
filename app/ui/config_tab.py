from __future__ import annotations
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QMessageBox, QHeaderView, QLineEdit, QComboBox, QLabel,
    QFormLayout, QDialog, QDialogButtonBox,
)

from app.core.config import get_all_config, set_config, add_config
from app.ui import strings_fa as S


class AddConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(S.DLG_ADD_CONFIG)
        self.setLayoutDirection(Qt.RightToLeft)
        layout = QFormLayout(self)
        layout.setLabelAlignment(Qt.AlignRight)

        self.key_edit = QLineEdit()
        self.label_edit = QLineEdit()
        self.value_edit = QLineEdit()
        self.type_combo = QComboBox()
        self.type_combo.addItems(["int", "float", "text"])
        self.category_edit = QLineEdit("general")
        self.desc_edit = QLineEdit()

        layout.addRow(S.LBL_KEY_HINT, self.key_edit)
        layout.addRow(S.LBL_LABEL, self.label_edit)
        layout.addRow(S.LBL_VALUE, self.value_edit)
        layout.addRow(S.LBL_TYPE, self.type_combo)
        layout.addRow(S.LBL_CATEGORY, self.category_edit)
        layout.addRow(S.LBL_DESCRIPTION, self.desc_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(S.OK)
        buttons.button(QDialogButtonBox.Cancel).setText(S.CANCEL)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self):
        return (
            self.key_edit.text().strip(),
            self.value_edit.text().strip(),
            self.type_combo.currentText(),
            self.label_edit.text().strip(),
            self.desc_edit.text().strip(),
            self.category_edit.text().strip() or "general",
        )


class ConfigTab(QWidget):
    # Column order: human-facing first (label, value, category, description),
    # then the stable internal key + type at the end (narrower).
    COLUMNS = [S.COL_LABEL, S.COL_VALUE, S.COL_CATEGORY, S.COL_DESCRIPTION, S.COL_KEY, S.COL_VALUE_TYPE]

    def __init__(self, conn: sqlite3.Connection):
        super().__init__()
        self.conn = conn
        self.setLayoutDirection(Qt.RightToLeft)

        layout = QVBoxLayout(self)
        info = QLabel(S.CONFIG_INFO)
        info.setWordWrap(True)
        layout.addWidget(info)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        # Make label + description stretch; others fit-to-content.
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)   # label
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)   # description
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        add_btn = QPushButton(S.ADD_NEW_VARIABLE)
        add_btn.clicked.connect(self.on_add)
        save_btn = QPushButton(S.SAVE_CHANGES)
        save_btn.clicked.connect(self.on_save)
        refresh_btn = QPushButton(S.REFRESH)
        refresh_btn.clicked.connect(self.load_data)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.load_data()

    def load_data(self):
        self.table.setSortingEnabled(False)
        rows = get_all_config(self.conn)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            key = row["key"]
            # Persian display via lookup; falls back to stored value for user-added vars
            label_fa = S.t_config_label(key, row["label"])
            desc_fa = S.t_config_desc(key, row["description"] or "")
            category_fa = S.t_category(row["category"] or "")

            # 0: label (read-only, Persian)
            label_item = QTableWidgetItem(label_fa)
            label_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.table.setItem(r, 0, label_item)

            # 1: value (editable)
            self.table.setItem(r, 1, QTableWidgetItem(str(row["value"])))

            # 2: category (Persian)
            cat_item = QTableWidgetItem(category_fa)
            cat_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.table.setItem(r, 2, cat_item)

            # 3: description (Persian)
            desc_item = QTableWidgetItem(desc_fa)
            desc_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.table.setItem(r, 3, desc_item)

            # 4: key (read-only English identifier, internal)
            key_item = QTableWidgetItem(key)
            key_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.table.setItem(r, 4, key_item)

            # 5: type (read-only)
            type_item = QTableWidgetItem(row["value_type"])
            type_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.table.setItem(r, 5, type_item)

        self.table.setSortingEnabled(True)

    def on_save(self):
        try:
            for r in range(self.table.rowCount()):
                # Key is now in column 4, value in column 1, type in column 5
                key = self.table.item(r, 4).text()
                value = self.table.item(r, 1).text()
                value_type = self.table.item(r, 5).text()
                if value_type == "int":
                    int(value)
                elif value_type == "float":
                    float(value)
                set_config(self.conn, key, value)
            QMessageBox.information(self, S.SAVED, S.MSG_CONFIG_SAVED)
        except ValueError as e:
            QMessageBox.critical(self, S.MSG_INVALID_VALUE, str(e))

    def on_add(self):
        dlg = AddConfigDialog(self)
        if dlg.exec() == QDialog.Accepted:
            key, value, value_type, label, desc, category = dlg.get_values()
            if not key or not label:
                QMessageBox.warning(self, S.WARNING, S.MSG_KEY_LABEL_REQUIRED)
                return
            try:
                if value_type == "int":
                    int(value)
                elif value_type == "float":
                    float(value)
            except ValueError:
                QMessageBox.critical(
                    self, S.MSG_INVALID_VALUE,
                    S.MSG_VALUE_TYPE_MISMATCH.format(type=value_type),
                )
                return
            add_config(self.conn, key, value, value_type, label, desc, category)
            self.load_data()