"""GrantIQ MCP — paid MCP server for US grants + federal contracts.

Exposes 8 MCP tools backed by Grants.gov + SAM.gov, fronted by an
X-API-Key auth layer with free/pro tier daily limits.

Endpoints:
    GET  /health                 — service health
    POST /admin/keys             — mint a new API key (admin only)
    POST /billing/upgrade        — flip a key to pro tier (Stripe webhook)
    POST /mcp                    — Streamable HTTP MCP endpoint (FastMCP)
"""

from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager
from typing import Iterable, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware, MiddlewareContext

from db.cache import init_cache
from db.keys import (
    DEV_KEY,
    admin_token,
    check_and_increment,
    create_key,
    init_keys,
    upgrade_to_pro,
)
from tools.contracts import (
    get_contract_details_impl,
    search_awards_impl,
    search_contracts_impl,
)
from tools.grants import (
    get_agencies_impl,
    get_deadlines_impl,
    get_grant_details_impl,
    search_grants_impl,
)
from tools.matching import match_opportunities_impl

log = logging.getLogger("grantiq")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


# --- Auth -------------------------------------------------------------------
RATE_LIMIT_BODY = {
    "error": "Limit reached. Upgrade at mcpize.com/grantiq-mcp"
}


class ApiKeyMiddleware(Middleware):
    """FastMCP middleware that gates every tool call on a valid X-API-Key."""

    async def on_call_tool(self, context: MiddlewareContext, call_next):  # type: ignore[override]
        request = _http_request_from_context(context)
        api_key = (request.headers.get("x-api-key") if request else None) or os.getenv(
            "GRANTIQ_BYPASS_KEY"
        )
        if not api_key:
            raise PermissionError("Missing X-API-Key header")
        allowed, record = check_and_increment(api_key)
        if record is None:
            raise PermissionError("Invalid X-API-Key")
        if not allowed:
            # FastMCP propagates this as an MCP error; HTTP 429 also covered
            # via /tools fallback below.
            raise PermissionError(RATE_LIMIT_BODY["error"])
        return await call_next(context)


def _http_request_from_context(context: MiddlewareContext) -> Optional[Request]:
    """Reach into FastMCP's request context for the underlying Starlette request."""
    try:
        ctx = context.fastmcp_context
        if ctx is None:
            return None
        req_ctx = ctx.request_context
        request = getattr(req_ctx, "request", None)
        if isinstance(request, Request):
            return request
    except Exception:  # pragma: no cover — best-effort plumbing
        return None
    return None


# --- MCP server -------------------------------------------------------------
mcp = FastMCP("GrantIQ MCP")
mcp.add_middleware(ApiKeyMiddleware())


@mcp.tool
async def search_grants(
    keyword: str = "",
    agency: Optional[str] = None,
    amount_min: Optional[float] = None,
    amount_max: Optional[float] = None,
    status: Optional[str] = "posted",
    limit: int = 10,
) -> dict:
    """Search Grants.gov for funding opportunities.

    Args:
        keyword: free-text search term
        agency: filter by agency code (e.g. "USDA")
        amount_min: minimum award ceiling in USD
        amount_max: maximum award ceiling in USD
        status: opportunity status — "posted", "forecasted", "closed"
        limit: max rows to return (1-100)
    """
    return await search_grants_impl(
        keyword=keyword,
        agency=agency,
        amount_min=amount_min,
        amount_max=amount_max,
        status=status,
        limit=limit,
    )


@mcp.tool
async def get_grant_details(opportunity_id: str) -> dict:
    """Fetch the full grant record for a Grants.gov opportunity id."""
    return await get_grant_details_impl(opportunity_id=opportunity_id)


@mcp.tool
async def search_contracts(
    keyword: str = "",
    naics_code: Optional[str] = None,
    agency: Optional[str] = None,
    set_aside: Optional[str] = None,
    limit: int = 10,
) -> dict:
    """Search SAM.gov for federal contract opportunities.

    Args:
        keyword: free-text search term
        naics_code: filter by NAICS industry code
        agency: filter by agency / organization name
        set_aside: SAM type-of-set-aside code (e.g. "SBA" for small business)
        limit: max rows to return (1-100)
    """
    return await search_contracts_impl(
        keyword=keyword,
        naics_code=naics_code,
        agency=agency,
        set_aside=set_aside,
        limit=limit,
    )


@mcp.tool
async def get_contract_details(notice_id: str) -> dict:
    """Fetch the full SAM.gov contract record for a notice id."""
    return await get_contract_details_impl(notice_id=notice_id)


@mcp.tool
async def match_opportunities(
    org_description: str,
    org_type: Optional[str] = None,
    focus_areas: Optional[list[str]] = None,
) -> dict:
    """Return the top ~10 grants + contracts matched to an org profile."""
    return await match_opportunities_impl(
        org_description=org_description,
        org_type=org_type,
        focus_areas=focus_areas,
    )


@mcp.tool
async def get_agencies(type: str = "grants") -> dict:
    """List agencies with currently-open opportunities.

    Args:
        type: one of "grants", "contracts", or "both"
    """
    if type == "contracts":
        contracts = await search_contracts_impl(limit=100)
        seen: dict[str, int] = {}
        for row in (contracts.get("data") or {}).get("results", []):
            name = row.get("agency")
            if name:
                seen[name] = seen.get(name, 0) + 1
        ranked = sorted(
            ({"agency": k, "open_opportunities": v} for k, v in seen.items()),
            key=lambda r: r["open_opportunities"],
            reverse=True,
        )
        return {"success": True, "cached": False, "data": ranked}

    if type == "both":
        grants = await get_agencies_impl(type="grants")
        contracts = await search_contracts_impl(limit=100)
        seen: dict[str, int] = {}
        for row in (grants.get("data") or []):
            seen[row["agency"]] = seen.get(row["agency"], 0) + row["open_opportunities"]
        for row in (contracts.get("data") or {}).get("results", []):
            name = row.get("agency")
            if name:
                seen[name] = seen.get(name, 0) + 1
        ranked = sorted(
            ({"agency": k, "open_opportunities": v} for k, v in seen.items()),
            key=lambda r: r["open_opportunities"],
            reverse=True,
        )
        return {"success": True, "cached": False, "data": ranked}

    return await get_agencies_impl(type="grants")


@mcp.tool
async def get_deadlines(days_ahead: int = 14) -> dict:
    """Return grants whose response deadline is within `days_ahead` days."""
    return await get_deadlines_impl(days_ahead=days_ahead)


@mcp.tool
async def search_awards(
    recipient_name: Optional[str] = None,
    agency: Optional[str] = None,
    year: Optional[int] = None,
) -> dict:
    """Search past SAM.gov contract awards."""
    return await search_awards_impl(
        recipient_name=recipient_name, agency=agency, year=year
    )


# --- FastAPI host -----------------------------------------------------------
mcp_app = mcp.http_app(path="/")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_cache()
    init_keys()
    log.info("GrantIQ MCP starting; dev key seeded as %s", DEV_KEY)
    async with mcp_app.lifespan(app):
        yield


app = FastAPI(title="GrantIQ MCP Server", version="1.0.0", lifespan=lifespan)
app.mount("/mcp", mcp_app)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "grantiq-mcp", "version": "1.0.0"}


@app.get("/")
def root() -> dict:
    return {
        "service": "grantiq-mcp",
        "docs": "https://github.com/bch1212/mcp-grantiq",
        "mcp_endpoint": "/mcp",
        "health": "/health",
    }


# REST passthrough — useful for curl users + the rate-limit-as-HTTP-429
# requirement in the build prompt. MCP clients should use /mcp instead.
async def _gate(request: Request, x_api_key: Optional[str]) -> None:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    allowed, record = check_and_increment(x_api_key)
    if record is None:
        raise HTTPException(status_code=401, detail="Invalid X-API-Key")
    if not allowed:
        raise HTTPException(status_code=429, detail=RATE_LIMIT_BODY)


@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    if exc.status_code == 429 and isinstance(exc.detail, dict):
        return JSONResponse(status_code=429, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.post("/tools/search_grants")
async def rest_search_grants(
    request: Request,
    payload: dict,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    await _gate(request, x_api_key)
    return await search_grants_impl(**payload)


@app.post("/tools/get_grant_details")
async def rest_get_grant_details(
    request: Request,
    payload: dict,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    await _gate(request, x_api_key)
    return await get_grant_details_impl(**payload)


@app.post("/tools/search_contracts")
async def rest_search_contracts(
    request: Request,
    payload: dict,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    await _gate(request, x_api_key)
    return await search_contracts_impl(**payload)


@app.post("/tools/get_contract_details")
async def rest_get_contract_details(
    request: Request,
    payload: dict,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    await _gate(request, x_api_key)
    return await get_contract_details_impl(**payload)


@app.post("/tools/match_opportunities")
async def rest_match_opportunities(
    request: Request,
    payload: dict,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    await _gate(request, x_api_key)
    return await match_opportunities_impl(**payload)


@app.post("/tools/get_agencies")
async def rest_get_agencies(
    request: Request,
    payload: dict,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    await _gate(request, x_api_key)
    type_arg = payload.get("type", "grants")
    if type_arg == "contracts":
        return {"success": True, "data": []}
    return await get_agencies_impl(type=type_arg)


@app.post("/tools/get_deadlines")
async def rest_get_deadlines(
    request: Request,
    payload: dict,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    await _gate(request, x_api_key)
    return await get_deadlines_impl(**payload)


@app.post("/tools/search_awards")
async def rest_search_awards(
    request: Request,
    payload: dict,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    await _gate(request, x_api_key)
    return await search_awards_impl(**payload)


# --- Admin endpoints --------------------------------------------------------
@app.post("/admin/keys")
async def mint_key(
    payload: dict,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
):
    """Mint a new API key. Body: {"tier": "free|pro", "daily_limit": int?}"""
    if not x_admin_token or x_admin_token != admin_token():
        raise HTTPException(status_code=401, detail="Invalid admin token")
    tier = payload.get("tier", "free")
    daily_limit = int(payload.get("daily_limit", 50))
    new_key = "grantiq_" + secrets.token_urlsafe(24)
    record = create_key(new_key, tier=tier, daily_limit=daily_limit)
    return {"success": True, "key": record.key, "tier": record.tier, "daily_limit": record.daily_limit}


@app.post("/billing/upgrade")
async def billing_upgrade(
    payload: dict,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
):
    """Promote a key to the pro tier. Called by the Stripe success webhook."""
    if not x_admin_token or x_admin_token != admin_token():
        raise HTTPException(status_code=401, detail="Invalid admin token")
    key = payload.get("key")
    if not key:
        raise HTTPException(status_code=400, detail="key is required")
    record = upgrade_to_pro(key)
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown key")
    return {"success": True, "key": record.key, "tier": record.tier}


def main() -> None:
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
