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
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
HEALTH_SCHEMA_PATH    = ROOT / "sql" / "schema-health.sql"
NUTRITION_SCHEMA_PATH = ROOT / "sql" / "schema-nutrition.sql"

# Load the local .env *before* reading any env var. `app.config` also does
# this, but `app.load_data` imports us without going through config, so we
# need to be self-sufficient. override=False keeps real shell env vars
# winning over .env (matches the convention used in app.config).
load_dotenv(ROOT / ".env", override=False)

DB_PATH = Path(os.environ.get("YDOCTER_DB_PATH", ROOT / "data" / "health.db"))
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


def _is_hrana_stream_error(exc: BaseException) -> bool:
    """True for Turso Hrana 404 `stream not found` errors.

    Why: Turso GCs idle Hrana streams server-side. Our thread-local libsql
    connection doesn't know, so the next ``execute`` surfaces a ValueError
    like ``Hrana: api error: status=404 ... stream not found``. We treat
    this as a signal to reconnect transparently.
    """
    msg = str(exc)
    return "Hrana" in msg and "stream not found" in msg


class _Connection:
    """Thin adapter exposing the sqlite3.Connection methods we use."""

    def __init__(self, native_conn) -> None:
        self._conn = native_conn

    def execute(self, sql: str, params: Sequence[Any] = ()) -> _Cursor:
        # libsql_experimental requires a tuple — it rejects list / other
        # sequences with `TypeError: argument 'parameters': 'list' object
        # cannot be converted to 'PyTuple'`. sqlite3 accepts either, so a
        # blanket coercion here keeps callers free to use either.
        try:
            return _Cursor(self._conn.execute(sql, tuple(params)))
        except ValueError as exc:
            if not _is_hrana_stream_error(exc):
                raise
            self._reconnect()
            return _Cursor(self._conn.execute(sql, tuple(params)))

    def executescript(self, script: str):
        return self._conn.executescript(script)

    def commit(self):
        return self._conn.commit()

    def close(self):
        return self._conn.close()

    def _reconnect(self) -> None:
        """Drop the dead native conn and open a fresh one in place.

        Keeps the wrapper identity stable so the thread-local cache in
        :func:`_get_cached_conn` stays valid.
        """
        import libsql_experimental as libsql

        try:
            self._conn.close()
        except Exception:
            pass
        self._conn = libsql.connect(TURSO_URL, auth_token=TURSO_TOKEN)

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

    return _connect_local()


def _connect_local():
    """Always return a connection to the local SQLite file.

    Used by :func:`get_local_conn` for tables (profiles, test_items,
    measurements) that are committed to git and shouldn't round-trip to
    Turso. Independent of ``TURSO_DATABASE_URL`` so the dashboard works
    even with Turso configured.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # WAL improves concurrent read/write on the file DB.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _apply_schema(conn, path: Path) -> None:
    """Apply schema DDL from a file.

    libsql's ``executescript`` against a remote Turso server has been
    observed to silently abandon trailing statements if it hits anything
    it considers non-DDL — and in particular drops PRAGMA. To stay robust
    on both backends we split into individual statements and run each
    via ``execute`` (autocommit). Empty / pure-comment chunks are ignored.
    """
    raw = path.read_text(encoding="utf-8")
    for stmt in _split_sql(raw):
        conn.execute(stmt)
    conn.commit()


def init_health_schema(conn) -> None:
    """Health-records schema: profiles + test_items + measurements +
    v_measurements view. Applied to the local SQLite DB."""
    _apply_schema(conn, HEALTH_SCHEMA_PATH)


def init_nutrition_schema(conn) -> None:
    """Nutrition schema: nutrients + nutrition_logs + nutrition_values +
    profile_nutrient_rda. Applied to Turso in prod, or to local in
    dev-fallback mode."""
    _apply_schema(conn, NUTRITION_SCHEMA_PATH)


def _split_sql(script: str) -> list[str]:
    """Naively split a SQL script on semicolons, ignoring those inside
    string literals (we don't have any in this codebase) and inside
    ``--`` line comments.
    """
    # Strip line comments first so a stray ``;`` inside a comment doesn't
    # split a statement.
    no_comments = "\n".join(
        line for line in script.splitlines()
        if not line.strip().startswith("--")
    )
    return [p.strip() for p in no_comments.split(";") if p.strip()]


# ---------------------------------------------------------------------------
# Thread-local connection cache
#
# FastAPI runs sync routes on a threadpool — opening a fresh libsql/sqlite
# connection per request costs a TCP/TLS handshake on the Turso path
# (~hundreds of ms to AWS Tokyo). Stashing one connection per worker
# thread keeps the handshake cost paid once. Connections are dropped only
# on suspected backend failures so a transient blip can re-establish
# cleanly; HTTPException and other application-level errors keep the
# cached connection alive.
# ---------------------------------------------------------------------------

_LOCAL = threading.local()

_RECOVERABLE_ERRORS: tuple[type[BaseException], ...] = (
    sqlite3.OperationalError,
    sqlite3.DatabaseError,
    sqlite3.InterfaceError,
    OSError,
)


def _get_cached_conn():
    conn = getattr(_LOCAL, "conn", None)
    if conn is None:
        conn = connect()
        _LOCAL.conn = conn
    return conn


def _drop_cached_conn() -> None:
    conn = getattr(_LOCAL, "conn", None)
    if conn is None:
        return
    _LOCAL.conn = None
    try:
        conn.close()
    except Exception:
        pass


@contextmanager
def get_conn() -> Iterator:
    conn = _get_cached_conn()
    try:
        yield conn
    except _RECOVERABLE_ERRORS:
        _drop_cached_conn()
        raise


# ---------------------------------------------------------------------------
# Local-only connection cache
#
# A separate thread-local slot for the always-local SQLite handle. Health
# checkup data (profiles / test_items / measurements) is committed to git
# and read from this connection regardless of whether Turso is configured.
# ---------------------------------------------------------------------------

_LOCAL_DB = threading.local()


def _get_cached_local_conn():
    conn = getattr(_LOCAL_DB, "conn", None)
    if conn is None:
        conn = _connect_local()
        _LOCAL_DB.conn = conn
    return conn


def _drop_cached_local_conn() -> None:
    conn = getattr(_LOCAL_DB, "conn", None)
    if conn is None:
        return
    _LOCAL_DB.conn = None
    try:
        conn.close()
    except Exception:
        pass


@contextmanager
def get_local_conn() -> Iterator:
    conn = _get_cached_local_conn()
    try:
        yield conn
    except _RECOVERABLE_ERRORS:
        _drop_cached_local_conn()
        raise
