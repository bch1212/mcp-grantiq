# GrantIQ MCP

**A paid MCP server that gives AI agents instant, structured access to every open US federal grant and contract opportunity.** Backed by Grants.gov + SAM.gov, with 24-hour SQLite caching, per-key daily limits, and a Stripe-friendly upgrade hook.

`https://mcp-grantiq.up.railway.app/mcp`

---

## MCPize listing copy

**Title:** GrantIQ MCP — US Federal Grants & Contracts for AI Agents

**Subtitle:** Search, match, and monitor every open SAM.gov and Grants.gov opportunity from any LLM, in one tool call.

GrantIQ MCP turns the messy world of US government funding into a clean, agent-ready API. Eight typed tools cover everything from broad keyword search and NAICS-coded contract discovery to deadline radar and historical award lookups. Responses are normalized across both data sources, returned as plain JSON, and cached for 24 hours so repeat queries don't burn rate limit on the upstream agencies.

Built for procurement copilots, grant-finder agents, and B2G sales tools, GrantIQ MCP ships with a free tier (50 calls/day) that any developer can drop into Claude or Cursor in 15 seconds. Upgrade to Pro for $19/mo for unlimited calls, or pay $0.02 per call for bursty workloads — billing flips a key from free to pro via a single webhook, with no app rewrites required.

---

## Pricing

| Tier | Price | Limit |
| --- | --- | --- |
| Free | $0 | 50 calls / day / key |
| Pro | **$19 / month** | Unlimited |
| Pay-as-you-go | **$0.02 / call** | Unlimited |

---

## Install

```bash
claude mcp add grantiq-mcp --url https://mcp-grantiq.up.railway.app/mcp
```

Then add the API key Claude should use:

```bash
claude mcp env grantiq-mcp X-API-Key=grantiq-dev-key-001
```

The dev key `grantiq-dev-key-001` is seeded automatically and capped at 50 calls/day. Mint your own with the admin endpoint below.

---

## Tool reference

| Tool | Args | Returns |
| --- | --- | --- |
| `search_grants` | `keyword`, `agency`, `amount_min`, `amount_max`, `status`, `limit` | List of matching grants |
| `get_grant_details` | `opportunity_id` | Full grant object |
| `search_contracts` | `keyword`, `naics_code`, `agency`, `set_aside`, `limit` | List of SAM contracts |
| `get_contract_details` | `notice_id` | Full contract object |
| `match_opportunities` | `org_description`, `org_type`, `focus_areas` | Top 10 matched opps (grants + contracts) |
| `get_agencies` | `type` (`grants` / `contracts` / `both`) | Agencies with open opps, ranked by volume |
| `get_deadlines` | `days_ahead` | Opportunities closing within N days |
| `search_awards` | `recipient_name`, `agency`, `year` | Past SAM award history |

Every tool returns either:

```json
{ "success": true,  "cached": false, "data": { ... } }
```

or, on failure:

```json
{ "success": false, "error": "..." }
```

When the daily limit is hit, the HTTP layer returns **429** with body:

```json
{ "error": "Limit reached. Upgrade at mcpize.com/grantiq-mcp" }
```

---

## curl examples

The MCP endpoint speaks the JSON-RPC streamable-HTTP protocol and is best used through an MCP client. For convenience, every tool also has a REST mirror at `/tools/<tool>`.

```bash
# Search grants
curl -s https://mcp-grantiq.up.railway.app/tools/search_grants \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: grantiq-dev-key-001' \
  -d '{"keyword":"renewable energy","limit":5}'

# Get grant details
curl -s https://mcp-grantiq.up.railway.app/tools/get_grant_details \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: grantiq-dev-key-001' \
  -d '{"opportunity_id":"345678"}'

# Search SAM.gov contracts (cyber, small-business set-aside)
curl -s https://mcp-grantiq.up.railway.app/tools/search_contracts \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: grantiq-dev-key-001' \
  -d '{"keyword":"cybersecurity","set_aside":"SBA","limit":5}'

# Get contract details
curl -s https://mcp-grantiq.up.railway.app/tools/get_contract_details \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: grantiq-dev-key-001' \
  -d '{"notice_id":"abc123"}'

# Match opportunities to an org profile
curl -s https://mcp-grantiq.up.railway.app/tools/match_opportunities \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: grantiq-dev-key-001' \
  -d '{"org_description":"Battery storage R&D startup","org_type":"for-profit","focus_areas":["energy","battery","storage"]}'

# Top agencies right now
curl -s https://mcp-grantiq.up.railway.app/tools/get_agencies \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: grantiq-dev-key-001' \
  -d '{"type":"both"}'

# Deadlines in the next 14 days
curl -s https://mcp-grantiq.up.railway.app/tools/get_deadlines \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: grantiq-dev-key-001' \
  -d '{"days_ahead":14}'

# Past award history
curl -s https://mcp-grantiq.up.railway.app/tools/search_awards \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: grantiq-dev-key-001' \
  -d '{"recipient_name":"Acme Corp","year":2025}'
```

---

## Operator endpoints

Mint a fresh key (free or pro):

```bash
curl -s https://mcp-grantiq.up.railway.app/admin/keys \
  -H 'X-Admin-Token: $GRANTIQ_ADMIN_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"tier":"free","daily_limit":50}'
```

Promote a free key to pro (called from the Stripe checkout success webhook):

```bash
curl -s https://mcp-grantiq.up.railway.app/billing/upgrade \
  -H 'X-Admin-Token: $GRANTIQ_ADMIN_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"key":"grantiq_xxxxx"}'
```

---

## Local dev

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python server.py        # http://localhost:8000
pytest -v               # 22 tests, hermetic with respx mocks
```

---

## Deploy to Railway

The repo includes `nixpacks.toml`. After `railway init`, just `railway up`. The start command is `python server.py` (not `uvicorn ...`) because Railway exec's `[start].cmd` without a shell — server.py reads `$PORT` via `os.getenv` and starts uvicorn programmatically.

Set these on the Railway service:

- `SAM_API_KEY` — your SAM.gov key
- `GRANTIQ_ADMIN_TOKEN` — long random string
- `GRANTIQ_DB_PATH` — `/data/grantiq.db` if you mount a Volume (recommended so cache + keys survive deploys)

A ready-to-run `deploy.sh` is in this directory.

---

## Caveats

- **SAM.gov award history** is exposed via the opportunities API filtered to `ptype=a` (Award Notice). For deeper award analytics (CFDA-level totals, recipient rollups), USAspending.gov is more appropriate and would be a v2 add.
- **Cache TTL is global** (24h). For deadline-sensitive flows the agent should pass distinct query args or call `/admin/keys` to mint a key that bypasses cache (not yet exposed — see TODO).
- **Match scoring** is deterministic Jaccard over title + agency tokens. It's fast and free; an LLM rerank can be added behind the same interface.
- **Stripe wiring** is one-way (`/billing/upgrade`). The MCP server doesn't host the checkout page itself — that lives on the marketing site.
