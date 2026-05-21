"""Database connection helpers.

Two backends share the same interface:

- **Local** (default): plain SQLite file at ``data/health.db``.
- **Remote / production**: Turso (libSQL) — used when ``TURSO_DATABASE_URL``
  is set in the environment. Every query is a network round-trip; nothing
  is written to local disk.

The remote driver (``libsql_experimental``) returns rows as plain tuples,
so we wrap it in a tiny adapter that exposes the bits of the
``sqlite3.Connection`` / ``sqlite3.Row`` API that the rest of the codebase
actually relies on:

- ``conn.execute(sql, params)`` returns a cursor
- ``cur.fetchall()`` / ``cur.fetchone()`` return dict-like rows
- ``row["col_name"]``, ``row[0]``, ``dict(row)`` all work
- ``cur.lastrowid``, ``conn.commit()``, ``conn.executescript(...)``

If the upstream code starts using more exotic sqlite3 features
(``conn.row_factory``, ``isolation_level``, etc.), extend the adapter
here rather than scattering branching across call sites.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("YDOCTER_DB_PATH", ROOT / "data" / "health.db"))
SCHEMA_PATH = ROOT / "sql" / "schema.sql"

TURSO_URL = os.environ.get("TURSO_DATABASE_URL", "").strip()
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "").strip()


def using_turso() -> bool:
    return bool(TURSO_URL)


# ---------------------------------------------------------------------------
# Adapter for libsql (Turso) → sqlite3-style row access
# ---------------------------------------------------------------------------


class _Row:
    """sqlite3.Row-compatible row used for the Turso path.

    Supports ``row["col"]``, ``row[0]``, ``dict(row)``, ``len(row)``.
    """

    __slots__ = ("_cols", "_values")

    def __init__(self, cols: Sequence[str], values: Sequence[Any]) -> None:
        self._cols = tuple(cols)
        self._values = tuple(values)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        try:
            return self._values[self._cols.index(key)]
        except ValueError as exc:
            raise KeyError(key) from exc

    def __iter__(self):
        # ``dict(row)`` calls ``keys()``; iterating returns column names so
        # ``for col in row`` matches sqlite3.Row behaviour.
        return iter(self._cols)

    def keys(self):
        return list(self._cols)

    def __len__(self) -> int:
        return len(self._cols)

    def __repr__(self) -> str:
        return f"_Row({dict(zip(self._cols, self._values))!r})"


class _Cursor:
    def __init__(self, native_cursor) -> None:
        self._cur = native_cursor

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    @property
    def description(self):
        return self._cur.description

    def _cols(self) -> tuple[str, ...]:
        desc = self._cur.description or ()
        return tuple(d[0] for d in desc)

    def fetchall(self) -> list[_Row]:
        cols = self._cols()
        return [_Row(cols, row) for row in self._cur.fetchall()]

    def fetchone(self) -> _Row | None:
        row = self._cur.fetchone()
        if row is None:
            return None
        return _Row(self._cols(), row)


class _Connection:
    """Thin adapter exposing the sqlite3.Connection methods we use."""

    def __init__(self, native_conn) -> None:
        self._conn = native_conn

    def execute(self, sql: str, params: Sequence[Any] = ()) -> _Cursor:
        return _Cursor(self._conn.execute(sql, params))

    def executescript(self, script: str):
        return self._conn.executescript(script)

    def commit(self):
        return self._conn.commit()

    def close(self):
        return self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def connect():
    """Return a connection to the active backend.

    Returns either a real ``sqlite3.Connection`` (local) or our
    ``_Connection`` adapter wrapping a libsql connection (Turso). Both
    expose the subset of the sqlite3 API the rest of the code relies on.
    """
    if using_turso():
        import libsql_experimental as libsql  # imported lazily for local-only runs

        native = libsql.connect(TURSO_URL, auth_token=TURSO_TOKEN)
        return _Connection(native)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


@contextmanager
def get_conn() -> Iterator:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
