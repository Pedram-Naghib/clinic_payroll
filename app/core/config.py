"""
Read/write access to the Owner-editable global config table.
Values are stored as TEXT but cast according to value_type on read,
so the Owner can edit them through a UI without touching code.
"""

from __future__ import annotations
import sqlite3


def _cast(value: str, value_type: str):
    if value_type == "int":
        return int(value)
    if value_type == "float":
        return float(value)
    return value  # 'text'


def get_config(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute(
        "SELECT value, value_type FROM system_config WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        return default
    return _cast(row["value"], row["value_type"])


def get_all_config(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM system_config ORDER BY category, label"
    ).fetchall()


def set_config(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute(
        "UPDATE system_config SET value = ?, updated_at = datetime('now') WHERE key = ?",
        (str(value), key),
    )
    conn.commit()


def add_config(conn: sqlite3.Connection, key: str, value, value_type: str,
                label: str, description: str = "", category: str = "general") -> None:
    """For the Owner dashboard's 'add new config variable' use case."""
    conn.execute(
        """INSERT INTO system_config (key, value, value_type, label, description, category)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value, value_type=excluded.value_type,
               label=excluded.label, description=excluded.description, category=excluded.category,
               updated_at=datetime('now')""",
        (key, str(value), value_type, label, description, category),
    )
    conn.commit()
