"""API key issuance, validation, and per-day rate limiting.

Tiers:
- free: capped at `daily_limit` calls/day (50 by default).
- pro:  unlimited.

The dev key `grantiq-dev-key-001` is seeded on startup so that
agents can probe the server without registering.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from db.cache import _connect, db_cursor

DEV_KEY = "grantiq-dev-key-001"
FREE_DAILY_LIMIT = 50


@dataclass
class KeyRecord:
    key: str
    tier: str
    call_count: int
    daily_limit: int
    created_at: float
    last_reset_day: str

    @property
    def is_pro(self) -> bool:
        return self.tier == "pro"


def init_keys() -> None:
    """Create the keys table and seed the default dev key."""
    with db_cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                key             TEXT PRIMARY KEY,
                tier            TEXT NOT NULL,
                call_count      INTEGER NOT NULL DEFAULT 0,
                daily_limit     INTEGER NOT NULL DEFAULT 50,
                created_at      REAL NOT NULL,
                last_reset_day  TEXT NOT NULL
            )
            """
        )
    # Seed dev key (idempotent).
    if get_key(DEV_KEY) is None:
        create_key(DEV_KEY, tier="free", daily_limit=FREE_DAILY_LIMIT)


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def create_key(key: str, *, tier: str = "free", daily_limit: int = FREE_DAILY_LIMIT) -> KeyRecord:
    """Insert a new key. Idempotent on PRIMARY KEY collision."""
    now = time.time()
    today = _today_utc()
    with db_cursor() as cur:
        cur.execute(
            "INSERT OR IGNORE INTO api_keys "
            "(key, tier, call_count, daily_limit, created_at, last_reset_day) "
            "VALUES (?, ?, 0, ?, ?, ?)",
            (key, tier, daily_limit, now, today),
        )
    record = get_key(key)
    assert record is not None  # we just inserted it
    return record


def get_key(key: str) -> Optional[KeyRecord]:
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT key, tier, call_count, daily_limit, created_at, last_reset_day "
            "FROM api_keys WHERE key = ?",
            (key,),
        ).fetchone()
    if not row:
        return None
    return KeyRecord(
        key=row["key"],
        tier=row["tier"],
        call_count=int(row["call_count"]),
        daily_limit=int(row["daily_limit"]),
        created_at=float(row["created_at"]),
        last_reset_day=row["last_reset_day"],
    )


def _reset_if_new_day(record: KeyRecord) -> KeyRecord:
    today = _today_utc()
    if record.last_reset_day == today:
        return record
    with db_cursor() as cur:
        cur.execute(
            "UPDATE api_keys SET call_count = 0, last_reset_day = ? WHERE key = ?",
            (today, record.key),
        )
    record.call_count = 0
    record.last_reset_day = today
    return record


def check_and_increment(key: str) -> tuple[bool, Optional[KeyRecord]]:
    """Validate a key and bump its counter.

    Returns `(allowed, record)`. `allowed` is False if the key is unknown OR
    the free-tier daily limit has been hit. Pro keys are always allowed.
    """
    record = get_key(key)
    if record is None:
        return False, None
    record = _reset_if_new_day(record)
    if not record.is_pro and record.call_count >= record.daily_limit:
        return False, record
    with db_cursor() as cur:
        cur.execute(
            "UPDATE api_keys SET call_count = call_count + 1 WHERE key = ?",
            (record.key,),
        )
    record.call_count += 1
    return True, record


def upgrade_to_pro(key: str) -> Optional[KeyRecord]:
    """Promote an existing key to the pro tier (called from billing webhook)."""
    if get_key(key) is None:
        return None
    with db_cursor() as cur:
        cur.execute(
            "UPDATE api_keys SET tier = 'pro', daily_limit = 1000000 WHERE key = ?",
            (key,),
        )
    return get_key(key)


def reset_call_count(key: str) -> None:
    """Test helper — wipe the daily counter."""
    with db_cursor() as cur:
        cur.execute(
            "UPDATE api_keys SET call_count = 0, last_reset_day = ? WHERE key = ?",
            (_today_utc(), key),
        )


def admin_token() -> str:
    """Token required to mint new keys via the admin endpoint."""
    return os.getenv("GRANTIQ_ADMIN_TOKEN", "change-me-in-prod")
