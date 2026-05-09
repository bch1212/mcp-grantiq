"""SQLite-backed TTL cache for upstream API responses.

Used by all tool wrappers to avoid hammering Grants.gov / SAM.gov.
TTL defaults to 24h per the spec.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

DEFAULT_TTL_SECONDS = 24 * 60 * 60  # 24h


def _db_path() -> str:
    return os.getenv("GRANTIQ_DB_PATH", "grantiq.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_cursor() -> Iterator[sqlite3.Cursor]:
    conn = _connect()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    finally:
        conn.close()


def init_cache() -> None:
    """Create the cache table if it does not exist."""
    with db_cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS api_cache (
                cache_key TEXT PRIMARY KEY,
                payload   TEXT NOT NULL,
                stored_at REAL NOT NULL
            )
            """
        )


def cache_get(key: str, ttl: int = DEFAULT_TTL_SECONDS) -> Optional[Any]:
    """Return cached value if present and within TTL window, else None."""
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT payload, stored_at FROM api_cache WHERE cache_key = ?", (key,)
        ).fetchone()
    if not row:
        return None
    if (time.time() - float(row["stored_at"])) > ttl:
        return None
    try:
        return json.loads(row["payload"])
    except json.JSONDecodeError:
        return None


def cache_set(key: str, value: Any) -> None:
    """Insert/replace a cache entry, stamped with the current time."""
    payload = json.dumps(value, default=str)
    with db_cursor() as cur:
        cur.execute(
            "INSERT OR REPLACE INTO api_cache (cache_key, payload, stored_at) "
            "VALUES (?, ?, ?)",
            (key, payload, time.time()),
        )


def cache_clear() -> None:
    """Drop every cache row. Used by tests."""
    with db_cursor() as cur:
        cur.execute("DELETE FROM api_cache")


def make_key(namespace: str, **params: Any) -> str:
    """Stable, sortable cache key from a namespace + sorted kwargs."""
    parts = [f"{k}={params[k]}" for k in sorted(params) if params[k] is not None]
    return f"{namespace}:" + "&".join(parts)
