"""Shared pytest fixtures.

Each test gets a clean SQLite DB at $TMPDIR/grantiq-test.db so cache +
key counters don't bleed between tests.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "grantiq-test.db"
    monkeypatch.setenv("GRANTIQ_DB_PATH", str(db_path))
    monkeypatch.setenv("GRANTIQ_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("SAM_API_KEY", "TEST-SAM-KEY")
    # init schemas for every test
    from db.cache import init_cache
    from db.keys import init_keys

    init_cache()
    init_keys()
    yield db_path


@pytest.fixture
def client():
    """FastAPI TestClient with the GrantIQ app booted."""
    from fastapi.testclient import TestClient

    import server  # noqa: WPS433 — late import so isolated_db env is set first

    with TestClient(server.app) as c:
        yield c
