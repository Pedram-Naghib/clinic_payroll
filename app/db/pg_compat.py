"""
Thin sqlite3.Connection-shaped wrapper around psycopg, so every function in
app/core/*.py -- written against sqlite3's '?' placeholders, sqlite3.Row
access, and cursor.lastrowid -- runs completely unchanged against Postgres.
Only used when DATABASE_URL is set; the desktop app's sqlite3 path in
app/db/database.py is untouched.

Two mechanical translations applied to every SQL string before it reaches
Postgres:
  - '?' positional placeholders -> '%s' (psycopg's native style). Safe here
    because none of app/core's SQL strings contain a literal '?' character.
  - a bare `INSERT INTO ...` with no RETURNING/ON CONFLICT clause gets
    ' RETURNING id' appended, so cursor.lastrowid keeps working -- every
    table in this schema uses `id` as its primary key column name.

Row shape matters too: sqlite3.Row supports BOTH row["col"] (mapping) AND
row[0] / tuple-unpacking like `for (x,) in cursor: ...` (sequence, values in
column order). psycopg's dict_row only gives mapping access -- iterating a
plain dict yields its KEYS, not values, so `for (emp_id,) in conn.execute(
"SELECT id FROM employees...")` would silently bind emp_id to the string
"id" instead of the row's value. Row below replicates sqlite3.Row's dual
interface so app/core's existing access patterns keep working unchanged.
"""
from __future__ import annotations
import re
import psycopg

_QMARK = re.compile(r"\?")
_HAS_RETURNING_OR_CONFLICT = re.compile(r"\b(RETURNING|ON\s+CONFLICT)\b", re.IGNORECASE)
_IS_BARE_INSERT = re.compile(r"^\s*INSERT\s+INTO\s", re.IGNORECASE)


def translate_sql(sql: str) -> tuple[str, bool]:
    """Returns (translated_sql, wants_lastrowid)."""
    wants_lastrowid = bool(_IS_BARE_INSERT.match(sql) and not _HAS_RETURNING_OR_CONFLICT.search(sql))
    translated = _QMARK.sub("%s", sql)
    if wants_lastrowid:
        translated = translated.rstrip().rstrip(";") + " RETURNING id"
    return translated, wants_lastrowid


class Row:
    """sqlite3.Row-alike: row["col"] AND row[0] AND value-iteration (so
    tuple-unpacking a query result works), backed by a psycopg row_factory."""
    __slots__ = ("_columns", "_values")

    def __init__(self, columns, values):
        self._columns = columns
        self._values = values

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._values[self._columns.index(key)]
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def keys(self):
        return list(self._columns)


def _row_factory(cursor):
    columns = [c.name for c in (cursor.description or [])]

    def make_row(values):
        return Row(columns, values)

    return make_row


class Cursor:
    def __init__(self, pg_cursor, lastrowid=None):
        self._cur = pg_cursor
        self.lastrowid = lastrowid

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur)

    @property
    def rowcount(self):
        return self._cur.rowcount


class Connection:
    def __init__(self, pg_conn):
        self._conn = pg_conn
        self.row_factory = None  # sqlite3 API compat no-op -- rows are always dict-like here

    def execute(self, sql: str, params=()) -> Cursor:
        translated, wants_lastrowid = translate_sql(sql)
        cur = self._conn.cursor(row_factory=_row_factory)
        cur.execute(translated, tuple(params) if params else None)
        lastrowid = None
        if wants_lastrowid:
            row = cur.fetchone()
            lastrowid = row["id"] if row else None
        return Cursor(cur, lastrowid)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def get_connection(database_url: str) -> Connection:
    # The same DATABASE_URL is also read by SQLAlchemy/Alembic, which needs
    # the dialect spelled out (postgresql+psycopg://) to pick this driver.
    # Raw psycopg3's connect() wants the plain DSN, so strip the "+psycopg"
    # (or any "+driver") suffix here rather than needing two env vars.
    dsn = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    return Connection(psycopg.connect(dsn, autocommit=False))
