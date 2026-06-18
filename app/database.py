from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from .config import DB_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS rates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    currency    TEXT    NOT NULL,
    value       REAL    NOT NULL,
    source_date TEXT    NOT NULL,
    scraped_at  TEXT    NOT NULL,
    UNIQUE(currency, source_date, value)
);
CREATE INDEX IF NOT EXISTS idx_rates_currency_time
    ON rates(currency, scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_rates_source_date
    ON rates(source_date DESC);
"""


def _connect(path: Optional[Path] = None) -> sqlite3.Connection:
    p = str(path or DB_PATH)
    conn = sqlite3.connect(p, timeout=10, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """No-op kept for backwards-compat: schema is now bootstrapped on every
    connection, so the table is always present (even if the file was deleted
    under us between requests)."""
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def insert_if_changed(
    currency: str, value: float, source_date: str, scraped_at: str
) -> bool:
    """Insert a new rate row only if the latest stored value+date differs.

    Returns True if a new row was inserted, False if skipped.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value, source_date FROM rates WHERE currency = ? "
            "ORDER BY scraped_at DESC, id DESC LIMIT 1",
            (currency,),
        ).fetchone()
        if row and row["value"] == value and row["source_date"] == source_date:
            return False
        conn.execute(
            "INSERT INTO rates(currency, value, source_date, scraped_at) "
            "VALUES (?, ?, ?, ?)",
            (currency, value, source_date, scraped_at),
        )
        return True


def get_latest(currency: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, currency, value, source_date, scraped_at FROM rates "
            "WHERE currency = ? ORDER BY scraped_at DESC, id DESC LIMIT 1",
            (currency,),
        ).fetchone()
        return dict(row) if row else None


def get_previous(currency: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, currency, value, source_date, scraped_at FROM rates "
            "WHERE currency = ? ORDER BY scraped_at DESC, id DESC "
            "LIMIT 1 OFFSET 1",
            (currency,),
        ).fetchone()
        return dict(row) if row else None


def get_history(currency: str, limit: int = 200) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, currency, value, source_date, scraped_at FROM rates "
            "WHERE currency = ? ORDER BY scraped_at DESC, id DESC LIMIT ?",
            (currency, max(1, int(limit))),
        ).fetchall()
        return [dict(r) for r in rows]


def get_sparkline(currency: str, limit: int = 30) -> list[float]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT value FROM rates WHERE currency = ? "
            "ORDER BY scraped_at ASC, id ASC LIMIT ?",
            (currency, max(1, int(limit))),
        ).fetchall()
        return [float(r["value"]) for r in rows]


def get_all_changes(limit: int = 500) -> list[dict]:
    """All rows where the value differs from the previous row of the same currency."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT r.id, r.currency, r.value, r.source_date, r.scraped_at "
            "FROM rates r "
            "WHERE r.id IN ("
            "  SELECT r2.id FROM rates r2 "
            "  LEFT JOIN rates p ON p.currency = r2.currency "
            "    AND (p.scraped_at < r2.scraped_at "
            "         OR (p.scraped_at = r2.scraped_at AND p.id < r2.id)) "
            "  WHERE p.id IS NULL OR p.value != r2.value OR p.source_date != r2.source_date"
            ") "
            "ORDER BY r.scraped_at DESC, r.id DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
        return [dict(r) for r in rows]


def last_scraped_at() -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT scraped_at FROM rates ORDER BY scraped_at DESC, id DESC LIMIT 1"
        ).fetchone()
        return row["scraped_at"] if row else None


def is_healthy() -> bool:
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except Exception:  # noqa: BLE001
        return False

