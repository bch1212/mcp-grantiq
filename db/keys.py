"""API key issuance, validation, and per-day rate limiting.

Tiers:
- free: capped at `daily_limit` calls/day (50 by default).
- pro:  unlimited.

If GRANTIQ_DEV_KEY is set, that key is seeded on startup for local use.
There is no hardcoded shared key and no default admin token.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from db.cache import _connect, db_cursor

FREE_DAILY_LIMIT = 50

# Digest of the shared dev key that used to be published in this repo.
# Startup deletes a matching row so an existing database does not keep it.
_RETIRED_DEV_KEY_SHA256 = "20a43b4f6889e8227c562ad1dc95484d13fa4a88f008d00fc238a8a5895d7a1d"


class AdminConfigError(RuntimeError):
    """GRANTIQ_ADMIN_TOKEN is missing or blank."""


def dev_key() -> Optional[str]:
    """Optional local key from GRANTIQ_DEV_KEY. Empty means do not seed one."""
    key = (os.getenv("GRANTIQ_DEV_KEY") or "").strip()
    return key or None


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
    """Create the keys table and seed GRANTIQ_DEV_KEY when it is set."""
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
    _retire_published_dev_key()
    # Seed an optional local key (idempotent). Never a hardcoded default.
    key = dev_key()
    if key and _is_retired_dev_key(key):
        key = None
    if key and get_key(key) is None:
        create_key(key, tier="free", daily_limit=FREE_DAILY_LIMIT)


def _is_retired_dev_key(key: str) -> bool:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return digest == _RETIRED_DEV_KEY_SHA256


def _retire_published_dev_key() -> None:
    """Drop the previously published shared dev key if a database still has it."""
    with db_cursor() as cur:
        rows = cur.execute("SELECT key FROM api_keys").fetchall()
        for row in rows:
            key = row["key"]
            if _is_retired_dev_key(key):
                cur.execute("DELETE FROM api_keys WHERE key = ?", (key,))


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
    """Token required to mint new keys via the admin endpoint.

    Missing or blank configuration is an error. There is no default, so
    startup and admin routes fail closed instead of accepting a known value.
    """
    token = (os.getenv("GRANTIQ_ADMIN_TOKEN") or "").strip()
    # The example file publishes these placeholders. They must not authenticate.
    if not token or token in {"your-admin-token", "replace-with-strong-random"}:
        raise AdminConfigError(
            "GRANTIQ_ADMIN_TOKEN must be set to a private value. Refusing admin operations."
        )
    return token
