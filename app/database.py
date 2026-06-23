from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

from .config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER


SCHEMA = """
CREATE TABLE IF NOT EXISTS rates (
    id          SERIAL PRIMARY KEY,
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


_pool: Optional[ThreadedConnectionPool] = None


def _get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(
            minconn=1,
            maxconn=5,
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
        )
    return _pool


@contextmanager
def get_conn() -> Iterator[psycopg2.extensions.connection]:
    pool = _get_pool()
    conn = pool.getconn()
    try:
        conn.set_session(autocommit=True)
        yield conn
    finally:
        pool.putconn(conn)


def init_db() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _row_to_dict(row: tuple, cur: psycopg2.extras.RealDictCursor) -> dict:
    cols = [desc[0] for desc in cur.description]
    return dict(zip(cols, row))


def insert_if_changed(
    currency: str, value: float, source_date: str, scraped_at: str
) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO rates(currency, value, source_date, scraped_at) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (currency, source_date, value) DO NOTHING",
                (currency, value, source_date, scraped_at),
            )
            return cur.rowcount > 0


def get_latest(currency: str) -> Optional[dict]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, currency, value, source_date, scraped_at FROM rates "
                "WHERE currency = %s ORDER BY scraped_at DESC, id DESC LIMIT 1",
                (currency,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def get_previous(currency: str) -> Optional[dict]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, currency, value, source_date, scraped_at FROM rates "
                "WHERE currency = %s ORDER BY scraped_at DESC, id DESC "
                "LIMIT 1 OFFSET 1",
                (currency,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def get_history(currency: str, limit: int = 200) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, currency, value, source_date, scraped_at FROM rates "
                "WHERE currency = %s ORDER BY scraped_at DESC, id DESC LIMIT %s",
                (currency, max(1, int(limit))),
            )
            return [dict(r) for r in cur.fetchall()]


def get_sparkline(currency: str, limit: int = 30) -> list[float]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT value FROM rates WHERE currency = %s "
                "ORDER BY scraped_at ASC, id ASC LIMIT %s",
                (currency, max(1, int(limit))),
            )
            return [float(r["value"]) for r in cur.fetchall()]


def get_all_changes(limit: int = 500) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, currency, value, source_date, scraped_at "
                "FROM ("
                "  SELECT id, currency, value, source_date, scraped_at,"
                "    LAG(value) OVER (PARTITION BY currency ORDER BY scraped_at, id) AS prev_value,"
                "    LAG(source_date) OVER (PARTITION BY currency ORDER BY scraped_at, id) AS prev_date"
                "  FROM rates"
                ") sub "
                "WHERE prev_value IS NULL OR prev_value != value OR prev_date != source_date "
                "ORDER BY scraped_at DESC, id DESC LIMIT %s",
                (max(1, int(limit)),),
            )
            return [dict(r) for r in cur.fetchall()]


def last_scraped_at() -> Optional[str]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT scraped_at FROM rates ORDER BY scraped_at DESC, id DESC LIMIT 1"
            )
            row = cur.fetchone()
            return row["scraped_at"] if row else None


def is_healthy() -> bool:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True
    except Exception:
        return False
