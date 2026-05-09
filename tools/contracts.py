"""SAM.gov wrapper for federal contract opportunities + award history.

API key passed via the SAM_API_KEY env var (falls back to the dev key
in the build prompt).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

from db.cache import cache_get, cache_set, make_key

SAM_OPPS_URL = "https://api.sam.gov/opportunities/v2/search"
SAM_AWARDS_URL = "https://api.sam.gov/prod/federalcontractopportunities/v1/api/search"
DEFAULT_TIMEOUT = 25.0
DEFAULT_API_KEY = "SAM-4b2f823c-bfd2-4555-bafb-b527e9e48058"


def _api_key() -> str:
    return os.getenv("SAM_API_KEY", DEFAULT_API_KEY)


def _ok(data: Any, cached: bool = False) -> dict:
    return {"success": True, "cached": cached, "data": data}


def _err(message: str) -> dict:
    return {"success": False, "error": message}


def _date_window(days_back: int = 90) -> tuple[str, str]:
    """SAM requires `postedFrom` + `postedTo` in MM/DD/YYYY."""
    today = datetime.utcnow()
    return (
        (today - timedelta(days=days_back)).strftime("%m/%d/%Y"),
        today.strftime("%m/%d/%Y"),
    )


async def search_contracts_impl(
    keyword: Optional[str] = None,
    naics_code: Optional[str] = None,
    agency: Optional[str] = None,
    set_aside: Optional[str] = None,
    limit: int = 10,
) -> dict:
    """Search SAM.gov for active contract opportunities."""
    cache_key = make_key(
        "sam_contracts",
        keyword=keyword,
        naics_code=naics_code,
        agency=agency,
        set_aside=set_aside,
        limit=limit,
    )
    cached = cache_get(cache_key)
    if cached is not None:
        return _ok(cached, cached=True)

    posted_from, posted_to = _date_window(90)
    params = {
        "api_key": _api_key(),
        "limit": min(max(limit, 1), 100),
        "postedFrom": posted_from,
        "postedTo": posted_to,
    }
    if keyword:
        params["q"] = keyword
    if naics_code:
        params["ncode"] = naics_code
    if agency:
        params["organizationName"] = agency
    if set_aside:
        params["typeOfSetAside"] = set_aside

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(SAM_OPPS_URL, params=params)
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPError as exc:
        return _err(f"SAM.gov request failed: {exc!s}")
    except ValueError as exc:
        return _err(f"SAM.gov returned non-JSON response: {exc!s}")

    raw_hits = body.get("opportunitiesData") or []
    hits = []
    for hit in raw_hits[: params["limit"]]:
        hits.append(
            {
                "notice_id": hit.get("noticeId"),
                "title": hit.get("title"),
                "agency": hit.get("fullParentPathName"),
                "type": hit.get("type"),
                "set_aside": hit.get("typeOfSetAsideDescription"),
                "naics_code": hit.get("naicsCode"),
                "posted_date": hit.get("postedDate"),
                "response_deadline": hit.get("responseDeadLine"),
                "url": hit.get("uiLink"),
            }
        )

    result = {"count": len(hits), "results": hits, "total": body.get("totalRecords", len(hits))}
    cache_set(cache_key, result)
    return _ok(result)


async def get_contract_details_impl(notice_id: str) -> dict:
    """Get full SAM.gov record for a single notice id."""
    if not notice_id:
        return _err("notice_id is required")

    cache_key = make_key("sam_details", id=notice_id)
    cached = cache_get(cache_key)
    if cached is not None:
        return _ok(cached, cached=True)

    posted_from, posted_to = _date_window(365)
    params = {
        "api_key": _api_key(),
        "limit": 1,
        "noticeid": notice_id,
        "postedFrom": posted_from,
        "postedTo": posted_to,
    }
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(SAM_OPPS_URL, params=params)
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPError as exc:
        return _err(f"SAM.gov request failed: {exc!s}")
    except ValueError as exc:
        return _err(f"SAM.gov returned non-JSON response: {exc!s}")

    hits = body.get("opportunitiesData") or []
    if not hits:
        return _err(f"No SAM.gov record found for notice_id={notice_id}")

    cache_set(cache_key, hits[0])
    return _ok(hits[0])


async def search_awards_impl(
    recipient_name: Optional[str] = None,
    agency: Optional[str] = None,
    year: Optional[int] = None,
) -> dict:
    """Search past SAM contract awards.

    Uses the SAM opportunities endpoint filtered to `Award Notice` type so
    we get a single, free, predictable surface (USAspending.gov is more
    detailed but requires a different schema and is out of scope here).
    """
    cache_key = make_key(
        "sam_awards", recipient=recipient_name, agency=agency, year=year
    )
    cached = cache_get(cache_key)
    if cached is not None:
        return _ok(cached, cached=True)

    if year:
        posted_from = f"01/01/{year}"
        posted_to = f"12/31/{year}"
    else:
        posted_from, posted_to = _date_window(365)

    params: dict[str, Any] = {
        "api_key": _api_key(),
        "limit": 25,
        "postedFrom": posted_from,
        "postedTo": posted_to,
        "ptype": "a",  # SAM type code "a" = Award Notice
    }
    if recipient_name:
        params["q"] = recipient_name
    if agency:
        params["organizationName"] = agency

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(SAM_OPPS_URL, params=params)
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPError as exc:
        return _err(f"SAM.gov request failed: {exc!s}")

    awards = []
    for hit in body.get("opportunitiesData") or []:
        award = hit.get("award") or {}
        awards.append(
            {
                "notice_id": hit.get("noticeId"),
                "title": hit.get("title"),
                "agency": hit.get("fullParentPathName"),
                "recipient": (award.get("awardee") or {}).get("name"),
                "amount": award.get("amount"),
                "award_date": award.get("date"),
                "url": hit.get("uiLink"),
            }
        )

    result = {"count": len(awards), "results": awards}
    cache_set(cache_key, result)
    return _ok(result)
