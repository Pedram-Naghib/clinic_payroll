from __future__ import annotations
import sqlite3
from datetime import datetime, time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QMessageBox, QHeaderView, QLabel, QComboBox, QFileDialog,
    QFormLayout,
)

from app.core.punch_importer import (
    import_punches_file, relink_unmatched_punches, punch_summary,
)
from app.core.attendance_engine import compute_and_persist_attendance, EmployeeAttendance
from app.core.jalali import jalali_to_gregorian, gregorian_to_jalali
from app.ui import strings_fa as S


def _numeric_item(value: float | int | None, display: str | None = None) -> QTableWidgetItem:
    item = QTableWidgetItem()
    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
    if value is None or value == "":
        item.setData(Qt.DisplayRole, "")
        item.setData(Qt.EditRole, 0)
    else:
        item.setData(Qt.EditRole, float(value))
        item.setData(Qt.DisplayRole, display if display is not None else str(value))
    return item


def _text_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
    return item


class AttendanceTab(QWidget):
    COLUMNS = [
        S.COL_NAME, S.COL_TYPE, S.COL_HOURS, S.COL_DAYS,
        S.COL_SESSIONS, S.COL_STATUS, S.COL_ANOMALIES_COUNT,
    ]

    def __init__(self, conn: sqlite3.Connection):
        super().__init__()
        self.conn = conn
        self.setLayoutDirection(Qt.RightToLeft)
        self._last_results: list[EmployeeAttendance] = []

        layout = QVBoxLayout(self)

        info = QLabel(S.ATTENDANCE_INFO)
        info.setWordWrap(True)
        layout.addWidget(info)

        # --- Top controls row ---
        controls = QHBoxLayout()

        import_btn = QPushButton(S.BTN_IMPORT_PUNCHES)
        import_btn.clicked.connect(self.on_import)
        controls.addWidget(import_btn)

        relink_btn = QPushButton(S.BTN_RELINK_PUNCHES)
        relink_btn.clicked.connect(self.on_relink)
        controls.addWidget(relink_btn)

        controls.addStretch()

        # Jalali year / month selectors (default to most recent observed month if data exists)
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

        compute_btn = QPushButton(S.BTN_COMPUTE_HOURS)
        compute_btn.clicked.connect(self.on_compute)
        controls.addWidget(compute_btn)

        layout.addLayout(controls)

        # --- Summary status label (shows db-wide punch info) ---
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("color: #888;")
        layout.addWidget(self.summary_label)

        # --- Results table ---
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        self._set_default_period()
        self._refresh_summary()

    def _set_default_period(self):
        """If we have punches, default the selector to the latest punch's Jalali month."""
        latest = self.conn.execute(
            "SELECT MAX(punch_datetime) AS d FROM raw_punches"
        ).fetchone()
        if not latest or not latest["d"]:
            return
        try:
            g_dt = datetime.strptime(latest["d"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return
        jy, jm, _ = gregorian_to_jalali(g_dt.year, g_dt.month, g_dt.day)
        # Find/set indices
        y_idx = self.year_combo.findData(jy)
        if y_idx >= 0:
            self.year_combo.setCurrentIndex(y_idx)
        m_idx = self.month_combo.findData(jm)
        if m_idx >= 0:
            self.month_combo.setCurrentIndex(m_idx)

    def _refresh_summary(self):
        s = punch_summary(self.conn)
        if s["total"] == 0:
            self.summary_label.setText(S.MSG_NO_DATA)
            return
        parts = [f"{s['total']:,} رکورد در دیتابیس"]
        if s["unmatched"]:
            parts.append(f"{s['unmatched']:,} بدون مالک")
        if s["earliest"] and s["latest"]:
            parts.append(f"{s['earliest']} → {s['latest']}")
        self.summary_label.setText("  ·  ".join(parts))

    # ----------- Actions -----------

    def on_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, S.MSG_SELECT_FILE, "", S.MSG_FILE_TYPES,
        )
        if not path:
            return
        try:
            result = import_punches_file(self.conn, path)
        except Exception as e:
            QMessageBox.critical(self, S.ERROR, str(e))
            return

        # Build a Persian summary message
        unmatched_section = ""
        if result["unmatched_count"]:
            enno_preview = ", ".join(result["unmatched_enroll_nos"][:30])
            if len(result["unmatched_enroll_nos"]) > 30:
                enno_preview += " ..."
            unmatched_section = S.MSG_UNMATCHED_DETAILS.format(enno_list=enno_preview)

        QMessageBox.information(
            self, S.MSG_IMPORT_TITLE,
            S.MSG_IMPORT_RESULT.format(
                parsed=result["parsed"],
                inserted=result["inserted"],
                duplicates=result["duplicates"],
                unmatched_count=result["unmatched_count"],
                unmatched_section=unmatched_section,
            ),
        )
        self._set_default_period()
        self._refresh_summary()

    def on_relink(self):
        n = relink_unmatched_punches(self.conn)
        QMessageBox.information(self, S.SAVED, S.MSG_RELINK_RESULT.format(n=n))
        self._refresh_summary()

    def on_compute(self):
        jy = self.year_combo.currentData()
        jm = self.month_combo.currentData()
        if jy is None or jm is None:
            return
        # Convert Jalali month boundaries to Gregorian datetimes
        period_start_d = jalali_to_gregorian(jy, jm, 1)
        if jm < 12:
            period_end_d = jalali_to_gregorian(jy, jm + 1, 1)
        else:
            period_end_d = jalali_to_gregorian(jy + 1, 1, 1)
        period_start = datetime.combine(period_start_d, time(0, 0, 0))
        period_end = datetime.combine(period_end_d, time(0, 0, 0))

        results = compute_and_persist_attendance(self.conn, period_start, period_end)
        self._last_results = results
        self._render_results(results)

    def _render_results(self, results: list[EmployeeAttendance]):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(results))
        gray = QBrush(QColor(160, 160, 160))

        from app.ui.strings_fa import EMP_TYPE_DISPLAY

        for r, att in enumerate(results):
            # Vertical header: employee.id
            self.table.setVerticalHeaderItem(r, QTableWidgetItem(str(att.employee_id)))

            type_display = EMP_TYPE_DISPLAY.get(att.employment_type, att.employment_type)
            if att.is_fixed_pay:
                status = S.STATUS_FIXED_PAY
            elif not att.sessions and att.total_hours == 0:
                status = S.STATUS_NO_PUNCHES
            elif att.anomalies:
                status = S.STATUS_HAS_ANOMALIES.format(n=len(att.anomalies))
            else:
                status = S.STATUS_OK

            cells = [
                _text_item(att.full_name),
                _text_item(type_display),
                _numeric_item(att.total_hours, display=f"{att.total_hours:.1f}"),
                _numeric_item(att.days_worked, display=str(att.days_worked)),
                _numeric_item(len(att.sessions), display=str(len(att.sessions))),
                _text_item(status),
                _numeric_item(len(att.anomalies), display=str(len(att.anomalies))),
            ]
            # Tooltip on the status cell = full list of anomalies
            if att.anomalies:
                cells[5].setToolTip("\n".join(att.anomalies))

            for c, item in enumerate(cells):
                if att.is_fixed_pay:
                    item.setForeground(gray)
                self.table.setItem(r, c, item)

        self.table.setSortingEnabled(True)