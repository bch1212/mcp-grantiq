"""GrantIQ MCP test suite.

External APIs are mocked with respx so the suite is hermetic and fast.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import respx

from db import keys as keys_db
from tools.contracts import (
    SAM_OPPS_URL,
    get_contract_details_impl,
    search_awards_impl,
    search_contracts_impl,
)
from tools.grants import (
    GRANTS_DETAILS_URL,
    GRANTS_SEARCH_URL,
    get_agencies_impl,
    get_deadlines_impl,
    get_grant_details_impl,
    search_grants_impl,
)
from tools.matching import match_opportunities_impl

DEV_KEY = keys_db.DEV_KEY


# --- helpers ----------------------------------------------------------------
def _grants_search_payload(rows=None):
    return {
        "oppHits": rows
        or [
            {
                "id": "12345",
                "number": "USDA-001",
                "title": "Rural broadband expansion",
                "agency": "USDA",
                "agencyCode": "USDA",
                "oppStatus": "posted",
                "openDate": "01/05/2026",
                "closeDate": "06/30/2026",
                "awardCeiling": "500000",
                "awardFloor": "10000",
            },
            {
                "id": "67890",
                "number": "DOE-002",
                "title": "Clean energy storage R&D",
                "agency": "Department of Energy",
                "agencyCode": "DOE",
                "oppStatus": "posted",
                "openDate": "02/10/2026",
                "closeDate": "05/15/2026",
                "awardCeiling": "2000000",
                "awardFloor": "100000",
            },
        ],
    }


def _sam_search_payload(rows=None):
    return {
        "totalRecords": 2,
        "opportunitiesData": rows
        or [
            {
                "noticeId": "abc123",
                "title": "Cybersecurity assessment services",
                "fullParentPathName": "DEPT OF DEFENSE",
                "type": "Solicitation",
                "typeOfSetAsideDescription": "Total Small Business",
                "naicsCode": "541512",
                "postedDate": "2026-04-01",
                "responseDeadLine": "2026-06-01T17:00:00-04:00",
                "uiLink": "https://sam.gov/opp/abc123/view",
            },
            {
                "noticeId": "def456",
                "title": "Cloud migration consulting",
                "fullParentPathName": "DEPT OF VETERANS AFFAIRS",
                "type": "Solicitation",
                "typeOfSetAsideDescription": "8(a) Set-Aside",
                "naicsCode": "541512",
                "postedDate": "2026-04-10",
                "responseDeadLine": "2026-05-20T17:00:00-04:00",
                "uiLink": "https://sam.gov/opp/def456/view",
            },
        ],
    }


# --- 1. cache + key infra --------------------------------------------------
def test_cache_roundtrip_and_ttl(tmp_path, monkeypatch):
    from db import cache

    monkeypatch.setenv("GRANTIQ_DB_PATH", str(tmp_path / "c.db"))
    cache.init_cache()

    cache.cache_set("k1", {"a": 1})
    assert cache.cache_get("k1") == {"a": 1}

    # TTL of 0 should treat the entry as expired
    assert cache.cache_get("k1", ttl=0) is None

    # Unknown key returns None
    assert cache.cache_get("missing") is None


def test_dev_key_seeded_and_increments():
    record = keys_db.get_key(DEV_KEY)
    assert record is not None
    assert record.tier == "free"
    assert record.daily_limit == 50
    assert record.call_count == 0

    allowed, _ = keys_db.check_and_increment(DEV_KEY)
    assert allowed is True
    assert keys_db.get_key(DEV_KEY).call_count == 1


def test_free_tier_blocks_at_daily_limit():
    rec = keys_db.create_key("limit-key", tier="free", daily_limit=2)
    assert rec.daily_limit == 2

    a1, _ = keys_db.check_and_increment("limit-key")
    a2, _ = keys_db.check_and_increment("limit-key")
    a3, after = keys_db.check_and_increment("limit-key")
    assert a1 and a2
    assert not a3
    assert after.call_count == 2  # third attempt was rejected, counter not bumped


def test_pro_tier_is_unlimited():
    keys_db.create_key("pro-key", tier="free", daily_limit=1)
    promoted = keys_db.upgrade_to_pro("pro-key")
    assert promoted.is_pro
    for _ in range(10):
        allowed, _ = keys_db.check_and_increment("pro-key")
        assert allowed is True


# --- 2. Grants.gov tools ----------------------------------------------------
@pytest.mark.asyncio
@respx.mock
async def test_search_grants_basic_and_caches():
    route = respx.post(GRANTS_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_grants_search_payload())
    )
    first = await search_grants_impl(keyword="energy", limit=5)
    assert first["success"] is True
    assert first["cached"] is False
    assert first["data"]["count"] == 2
    assert first["data"]["results"][0]["title"].startswith("Rural broadband")

    # Second call hits cache, no extra HTTP request
    second = await search_grants_impl(keyword="energy", limit=5)
    assert second["cached"] is True
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_search_grants_amount_filter():
    respx.post(GRANTS_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_grants_search_payload())
    )
    resp = await search_grants_impl(keyword="x", amount_min=1_000_000)
    assert resp["success"] is True
    titles = [r["title"] for r in resp["data"]["results"]]
    assert "Clean energy storage R&D" in titles
    assert "Rural broadband expansion" not in titles  # below 1M floor


@pytest.mark.asyncio
@respx.mock
async def test_search_grants_handles_upstream_5xx():
    respx.post(GRANTS_SEARCH_URL).mock(return_value=httpx.Response(503, text="boom"))
    resp = await search_grants_impl(keyword="x")
    assert resp["success"] is False
    assert "Grants.gov" in resp["error"]


@pytest.mark.asyncio
@respx.mock
async def test_get_grant_details_required_arg():
    resp = await get_grant_details_impl(opportunity_id="")
    assert resp["success"] is False


@pytest.mark.asyncio
@respx.mock
async def test_get_grant_details_happy_path():
    respx.post(GRANTS_DETAILS_URL).mock(
        return_value=httpx.Response(
            200,
            json={"opportunityId": "12345", "title": "Rural broadband", "synopsis": "..."},
        )
    )
    resp = await get_grant_details_impl(opportunity_id="12345")
    assert resp["success"] is True
    assert resp["data"]["title"] == "Rural broadband"


@pytest.mark.asyncio
@respx.mock
async def test_get_agencies_aggregates_and_sorts():
    respx.post(GRANTS_SEARCH_URL).mock(
        return_value=httpx.Response(
            200,
            json=_grants_search_payload(
                rows=[
                    {"id": "1", "title": "a", "agency": "USDA"},
                    {"id": "2", "title": "b", "agency": "USDA"},
                    {"id": "3", "title": "c", "agency": "DOE"},
                ]
            ),
        )
    )
    resp = await get_agencies_impl(type="grants")
    assert resp["success"] is True
    top = resp["data"][0]
    assert top["agency"] == "USDA"
    assert top["open_opportunities"] == 2


@pytest.mark.asyncio
@respx.mock
async def test_get_deadlines_filters_window():
    from datetime import datetime, timedelta, timezone

    soon = (datetime.now(timezone.utc) + timedelta(days=5)).strftime("%m/%d/%Y")
    far = (datetime.now(timezone.utc) + timedelta(days=120)).strftime("%m/%d/%Y")
    respx.post(GRANTS_SEARCH_URL).mock(
        return_value=httpx.Response(
            200,
            json=_grants_search_payload(
                rows=[
                    {"id": "1", "title": "soon", "agency": "X", "closeDate": soon},
                    {"id": "2", "title": "later", "agency": "Y", "closeDate": far},
                ]
            ),
        )
    )
    resp = await get_deadlines_impl(days_ahead=14)
    assert resp["success"] is True
    titles = [r["title"] for r in resp["data"]]
    assert titles == ["soon"]


# --- 3. SAM.gov tools -------------------------------------------------------
@pytest.mark.asyncio
@respx.mock
async def test_search_contracts_basic():
    respx.get(SAM_OPPS_URL).mock(
        return_value=httpx.Response(200, json=_sam_search_payload())
    )
    resp = await search_contracts_impl(keyword="cyber", limit=5)
    assert resp["success"] is True
    assert resp["data"]["count"] == 2
    assert resp["data"]["results"][0]["notice_id"] == "abc123"


@pytest.mark.asyncio
@respx.mock
async def test_get_contract_details_not_found():
    respx.get(SAM_OPPS_URL).mock(
        return_value=httpx.Response(200, json={"opportunitiesData": []})
    )
    resp = await get_contract_details_impl(notice_id="missing-id")
    assert resp["success"] is False
    assert "missing-id" in resp["error"]


@pytest.mark.asyncio
@respx.mock
async def test_search_awards_runs():
    respx.get(SAM_OPPS_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "opportunitiesData": [
                    {
                        "noticeId": "AW-1",
                        "title": "IT services contract",
                        "fullParentPathName": "GSA",
                        "uiLink": "https://sam.gov/opp/AW-1/view",
                        "award": {
                            "awardee": {"name": "Acme Corp"},
                            "amount": "1500000",
                            "date": "2025-09-30",
                        },
                    }
                ]
            },
        )
    )
    resp = await search_awards_impl(recipient_name="Acme", year=2025)
    assert resp["success"] is True
    assert resp["data"]["results"][0]["recipient"] == "Acme Corp"


# --- 4. matcher -------------------------------------------------------------
@pytest.mark.asyncio
@respx.mock
async def test_match_opportunities_orders_by_score():
    respx.post(GRANTS_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_grants_search_payload())
    )
    respx.get(SAM_OPPS_URL).mock(
        return_value=httpx.Response(200, json=_sam_search_payload())
    )
    resp = await match_opportunities_impl(
        org_description="renewable energy storage startup",
        org_type="for-profit",
        focus_areas=["energy", "battery", "storage"],
    )
    assert resp["success"] is True
    results = resp["data"]["results"]
    assert results, "matcher returned no results"
    # results are sorted high → low
    scores = [r["match_score"] for r in results]
    assert scores == sorted(scores, reverse=True)


# --- 5. HTTP layer ----------------------------------------------------------
def test_health_endpoint(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_rest_requires_api_key(client):
    r = client.post("/tools/search_grants", json={"keyword": "x"})
    assert r.status_code == 401


@respx.mock
def test_rest_with_dev_key_succeeds(client):
    respx.post(GRANTS_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_grants_search_payload())
    )
    r = client.post(
        "/tools/search_grants",
        json={"keyword": "x", "limit": 2},
        headers={"X-API-Key": DEV_KEY},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["count"] == 2


def test_rest_returns_429_when_over_limit(client):
    keys_db.create_key("burn-key", tier="free", daily_limit=1)
    # one allowed call (mocked target — we use health which doesn't gate, so
    # use search_awards w/ mocked SAM since that passes through _gate)
    with respx.mock:
        respx.get(SAM_OPPS_URL).mock(
            return_value=httpx.Response(200, json={"opportunitiesData": []})
        )
        ok = client.post(
            "/tools/search_awards",
            json={"recipient_name": "x"},
            headers={"X-API-Key": "burn-key"},
        )
        assert ok.status_code == 200
        blocked = client.post(
            "/tools/search_awards",
            json={"recipient_name": "x"},
            headers={"X-API-Key": "burn-key"},
        )
    assert blocked.status_code == 429
    assert "Upgrade" in blocked.json()["error"]


def test_admin_can_mint_key(client):
    r = client.post(
        "/admin/keys",
        json={"tier": "free", "daily_limit": 25},
        headers={"X-Admin-Token": "test-admin-token"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["key"].startswith("grantiq_")
    assert body["tier"] == "free"
    assert body["daily_limit"] == 25


def test_admin_rejects_bad_token(client):
    r = client.post(
        "/admin/keys",
        json={"tier": "pro"},
        headers={"X-Admin-Token": "wrong"},
    )
    assert r.status_code == 401


def test_billing_upgrade_promotes_key(client):
    # mint, then promote
    minted = client.post(
        "/admin/keys",
        json={"tier": "free"},
        headers={"X-Admin-Token": "test-admin-token"},
    ).json()
    r = client.post(
        "/billing/upgrade",
        json={"key": minted["key"]},
        headers={"X-Admin-Token": "test-admin-token"},
    )
    assert r.status_code == 200
    assert r.json()["tier"] == "pro"
    assert keys_db.get_key(minted["key"]).is_pro
