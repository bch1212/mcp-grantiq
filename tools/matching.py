"""Lightweight, deterministic opportunity matcher.

Spec calls for `match_opportunities(org_description, org_type, focus_areas)`
returning the top 10 matched opportunities. We pull recent grants AND
contracts in parallel, then score each candidate by simple keyword
overlap. Deterministic, free, and easy to unit-test — an LLM rerank can
be layered on later behind the same interface.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Iterable, Optional

from tools.contracts import search_contracts_impl
from tools.grants import search_grants_impl

WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: Optional[str]) -> set[str]:
    if not text:
        return set()
    return {tok for tok in WORD_RE.findall(text.lower()) if len(tok) > 2}


def _score(target_tokens: set[str], candidate: dict) -> float:
    """Simple Jaccard over tokens from title + agency."""
    text = " ".join(
        str(candidate.get(field, "") or "")
        for field in ("title", "agency", "agency_code")
    )
    cand_tokens = _tokenize(text)
    if not cand_tokens or not target_tokens:
        return 0.0
    overlap = len(target_tokens & cand_tokens)
    union = len(target_tokens | cand_tokens) or 1
    return overlap / union


def _normalize_grant(row: dict) -> dict:
    return {
        "source": "grants.gov",
        "id": row.get("opportunity_id"),
        "title": row.get("title"),
        "agency": row.get("agency"),
        "url": row.get("url"),
        "deadline": row.get("close_date"),
    }


def _normalize_contract(row: dict) -> dict:
    return {
        "source": "sam.gov",
        "id": row.get("notice_id"),
        "title": row.get("title"),
        "agency": row.get("agency"),
        "url": row.get("url"),
        "deadline": row.get("response_deadline"),
    }


async def match_opportunities_impl(
    org_description: str,
    org_type: Optional[str] = None,
    focus_areas: Optional[Iterable[str]] = None,
    limit: int = 10,
) -> dict:
    if not org_description or not org_description.strip():
        return {"success": False, "error": "org_description is required"}

    focus_list = list(focus_areas or [])
    target_text = " ".join([org_description, org_type or "", *focus_list])
    target_tokens = _tokenize(target_text)

    primary_keyword = focus_list[0] if focus_list else org_description.split()[0]

    grants_resp, contracts_resp = await asyncio.gather(
        search_grants_impl(keyword=primary_keyword, limit=50),
        search_contracts_impl(keyword=primary_keyword, limit=50),
        return_exceptions=True,
    )

    candidates: list[dict] = []
    if isinstance(grants_resp, dict) and grants_resp.get("success"):
        for row in grants_resp["data"].get("results", []):
            normalized = _normalize_grant(row)
            normalized["match_score"] = round(_score(target_tokens, row), 4)
            candidates.append(normalized)
    if isinstance(contracts_resp, dict) and contracts_resp.get("success"):
        for row in contracts_resp["data"].get("results", []):
            normalized = _normalize_contract(row)
            normalized["match_score"] = round(_score(target_tokens, row), 4)
            candidates.append(normalized)

    candidates.sort(key=lambda r: r["match_score"], reverse=True)
    top = candidates[: max(limit, 1)]

    return {
        "success": True,
        "cached": False,
        "data": {
            "matched": len(top),
            "results": top,
            "input": {
                "org_description": org_description,
                "org_type": org_type,
                "focus_areas": focus_list,
            },
        },
    }
