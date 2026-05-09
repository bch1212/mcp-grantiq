# GrantIQ MCP — launch post drafts

Builder voice. Problem-first. Honest caveats. Brett ships when ready.

---

## Show HN

**Title:**
> Show HN: GrantIQ MCP – give your AI agent live US grants and federal contracts

**Body:**
GrantIQ MCP is a paid Model Context Protocol server that lets any LLM search every open Grants.gov opportunity and SAM.gov contract through one normalized JSON interface. Eight tools cover keyword search, agency rollups, deadline radar, NAICS-coded contract discovery, and a deterministic matcher that scores opportunities against an org profile. Responses are cached in SQLite for 24h so repeat queries don't burn the upstream rate limits.

Free tier is 50 calls/day, no signup — just `claude mcp add grantiq-mcp --url https://mcp.grantiq.us/mcp` and use the seeded dev key. Pro is $19/mo for unlimited. The `/billing/upgrade` endpoint flips a key to pro tier with one webhook so Stripe integration is mechanical.

What's interesting to me: most "agent + government data" demos I've seen treat scraping as the hard part. The hard part is normalization across the two main sources (Grants.gov is a JSON-RPC-ish POST API, SAM.gov is REST + key-gated, deadlines and amounts come back in different shapes), plus billing in a way that doesn't need a dashboard. This collapses both into 8 typed tools.

Caveats: SAM award data is from the opportunities API filtered to award-notice type, not USAspending — fine for "did they win contracts last year?" not for CFDA-level analytics. Match scoring is Jaccard, not LLM rerank.

Repo: https://github.com/bch1212/mcp-grantiq

---

## r/ClaudeAI

**Title:** Built an MCP server that gives Claude live US federal grants + contracts

I kept hitting the same wall building grant-finder agents — every prompt ended with "but I don't actually have access to Grants.gov." So I shipped GrantIQ MCP, a paid MCP server that exposes the two main US funding databases (Grants.gov + SAM.gov) as 8 typed tools.

```
claude mcp add grantiq-mcp --url https://mcp.grantiq.us/mcp
```

Free tier dev key is `grantiq-dev-key-001` — 50 calls/day. Tools:
- search_grants / get_grant_details
- search_contracts / get_contract_details
- match_opportunities (org profile → top 10 ranked)
- get_agencies, get_deadlines, search_awards

Cache TTL is 24h so repeat questions don't slow Claude down. Built on FastMCP + FastAPI + SQLite, deployed on Railway.

Open to feedback. Repo: https://github.com/bch1212/mcp-grantiq

---

## r/AI_Agents

**Title:** GrantIQ MCP — government grants + contracts as 8 typed tools for agents

Most B2G data sources are agent-hostile: split across two APIs (Grants.gov and SAM.gov), inconsistent date/amount formats, no native rate-limit headers. GrantIQ MCP is a paid MCP server that normalizes them into 8 tools an agent can call without knowing the upstream schemas.

Use cases I've seen so far:
- procurement copilots filtering by NAICS + small-business set-aside
- grant-finder agents matching an org description to top opps
- deadline-radar agents that surface anything closing in N days

Free tier: 50 calls/day. `https://mcp.grantiq.us/mcp` + `X-API-Key` header. Pro flips on via webhook.

Repo: https://github.com/bch1212/mcp-grantiq — feedback welcome.

---

## Twitter (single post)

> Shipped GrantIQ MCP — a paid MCP server that gives any LLM live access to US federal grants + contracts.
>
> 8 tools across @GrantsGov + SAM.gov, 24h cache, 50 free calls/day.
>
> claude mcp add grantiq-mcp --url https://mcp.grantiq.us/mcp
>
> github.com/bch1212/mcp-grantiq

---

## Twitter (thread)

1/ Shipped GrantIQ MCP today. It turns Grants.gov + SAM.gov into 8 typed tools any LLM can call through MCP.

2/ Why bother? Every B2G agent demo I've seen dies at the data layer. Grants.gov is a quirky JSON-RPC POST API, SAM.gov is REST + key-gated, dates and amounts come back in different shapes. This normalizes both into a single agent surface.

3/ Tools: search_grants, get_grant_details, search_contracts, get_contract_details, match_opportunities, get_agencies, get_deadlines, search_awards.

4/ Free tier: 50 calls/day, no signup. `claude mcp add grantiq-mcp --url https://mcp.grantiq.us/mcp` and you're in. Pro is $19/mo, flipped on by Stripe webhook.

5/ Built on FastMCP + FastAPI + SQLite, deployed on Railway with a Let's Encrypt cert at mcp.grantiq.us. Cache TTL 24h so repeat queries don't burn upstream limits.

6/ github.com/bch1212/mcp-grantiq — feedback welcome.

---

## Product Hunt

**Tagline:** US federal grants + contracts for any AI agent

**Description:**
GrantIQ MCP is a paid Model Context Protocol server that lets any LLM search live US federal grants (Grants.gov) and contract opportunities (SAM.gov) through 8 normalized tools. Free tier is 50 calls/day with a seeded dev key — `claude mcp add grantiq-mcp --url https://mcp.grantiq.us/mcp` and your agent has government funding data on tap. $19/mo for unlimited or $0.02/call.

**Maker comment:**
Hi PH. I built GrantIQ MCP because every B2G agent demo I've seen breaks at the data layer. Grants.gov and SAM.gov each have their own quirks; this collapses both into one agent-friendly surface with caching, rate limits, and a Stripe-friendly upgrade path. The match_opportunities tool is the most fun to play with — feed it an org description and focus areas and it ranks the top 10 grants + contracts deterministically. Open to all feedback.

---

## LinkedIn

A reflective angle, not a sales pitch: I keep noticing that the bottleneck for "AI agent for X" products isn't the model — it's getting the data into a shape an agent can actually act on.

I just shipped GrantIQ MCP, a paid server that exposes US federal grants and contracts to any LLM through 8 normalized tools. Procurement copilots, grant-finder agents, B2G sales tools — all of them keep hitting the same wall, because Grants.gov and SAM.gov are designed for human portals, not for software. This collapses both into one MCP surface with caching and per-key billing.

Free tier is 50 calls/day. https://github.com/bch1212/mcp-grantiq

---

## Discord (terse)

> Shipped GrantIQ MCP — paid MCP server for US federal grants + contracts. Free tier 50/day.
>
> `claude mcp add grantiq-mcp --url https://mcp.grantiq.us/mcp`
>
> https://github.com/bch1212/mcp-grantiq
