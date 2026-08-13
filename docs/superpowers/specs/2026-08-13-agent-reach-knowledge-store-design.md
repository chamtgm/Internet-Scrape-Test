# Agent-Reach Knowledge Store — Design

**Date:** 2026-08-13
**Status:** Approved design, ready for implementation planning

## 1. Overview

A multi-user knowledge store built on top of [Agent-Reach](https://github.com/Panniantong/Agent-Reach).

Agent-Reach is a *reader*: a CLI + MCP layer that fetches content from Twitter/X, Reddit, YouTube, GitHub, Bilibili, XiaoHongShu, Instagram, RSS, and arbitrary web pages without paid API keys. It hands content back and forgets it.

This project supplies the missing half: **persistence and retrieval**. Users declare what they care about, the system collects on a schedule, stores everything raw, and lets users search and ask questions across their accumulated collection through a web UI.

**Pipeline:** `declared sources → fetch via Agent-Reach → normalize → store raw → query`

## 2. Goals and non-goals

### Goals
- Persist content collected via Agent-Reach in a durable, queryable store.
- Support 5–50 invite-only users, each with their own watchlist and private collection.
- Cover all Agent-Reach source tiers, including auth-required and browser-automated platforms.
- Run indefinitely on free infrastructure.
- Serve a web UI that both reads collected content and controls the system.

### Non-goals (v1)
- Public signup, billing, or abuse handling.
- Semantic/vector search — Postgres full-text search only.
- The outreach, trend-monitoring, and competitor-tracking lenses. The spine supports them; they are not built in v1.
- Sharing collections between users beyond the automatic deduplication of public Tier-1 sources.
- Mobile apps or email digests.

## 3. Key decisions and rationale

| Decision | Rationale |
|---|---|
| Store raw, judge relevance at query time (ELT) | Ingest-time filtering is an irreversible decision made with the least information available; interests shift and re-scraping social platforms is unreliable. Query-time judging also costs tokens proportional to what is asked, not to what is fetched. |
| Split collection by source tier | Datacenter IPs are blocked by X/XHS/Instagram, and Tier-2/3 sources require user session cookies. Running those fetches on the user's own machine solves both with no infrastructure cost. |
| Postgres, not SQLite | SQLite permits one writer at a time; concurrent pushes from many collectors would serialize and time out. |
| Content shared, interest per-user | Tier-1 sources fetched centrally are stored once and linked to many users, so N subscribers cost one fetch. |
| React + Vite, served by FastAPI | User preference for a rich UI; serving the built assets from the API keeps a single origin, avoiding CORS and cookie complexity. |
| BYOK for LLM access | Query-time synthesis is the only per-user variable cost; user-supplied keys keep it off the operator's bill and outside free-tier daily caps. |

## 4. Architecture

Three deployable artifacts.

```
        ┌──────── user's machine ────────┐
        │  collector ── agent-reach      │   Tier 2/3: X, Reddit, YouTube,
        │      │        (their cookies)  │   Bilibili, XHS, Instagram
        └──────┼─────────────────────────┘
               │ HTTPS push (bearer token)
               ▼
   ┌─────────── Oracle Cloud free VM ─────────────┐
   │  Caddy → FastAPI → Postgres                  │   Tier 1: GitHub, RSS,
   │            │        raw payloads on disk     │   web pages (fetched once,
   │            └── query layer → React UI        │   shared across users)
   └──────────────────────────────────────────────┘
```

**`server`** — Python + FastAPI. Owns Postgres, authentication, Tier-1 fetchers, the query layer, the JSON API, and serving the built UI. A systemd timer drives Tier-1 collection.

**`collector`** — Python CLI installed on each user's machine. Pulls its assignment list from the server, invokes `agent-reach` for Tier-2/3 sources, pushes normalized items back. Platform cookies and `~/.agent-reach/config.yaml` never leave the device.

**`web`** — React + Vite SPA, built to static assets and served by FastAPI.

### Source tiers

| Tier | Sources | Fetched by | Reliability |
|---|---|---|---|
| 1 | GitHub, RSS, web pages (Jina Reader), Exa search queries | Server | Stable; no credentials |
| 2 | Twitter/X, Reddit, YouTube, Bilibili | Collector | Occasional breakage; cookies/tooling |
| 3 | XiaoHongShu, Instagram | Collector | Frequent breakage; browser automation |

Tier-3 failures are expected and logged, never treated as run-fatal.

## 5. Data model

Postgres. Seven tables.

```sql
users          id, email, display_name, password_hash, llm_key_encrypted,
               llm_provider, created_at

collectors     id, user_id, name, token_hash, last_seen_at, created_at
                 -- one row per user machine; revocable from the UI

sources        id, kind, identifier, tier, config_json, created_at
                 UNIQUE (kind, identifier)
                 -- kind ∈ github_repo | rss | web_page | subreddit | x_account
                 --        | yt_channel | bilibili_up | xhs_user | search_query

subscriptions  id, user_id, source_id, label, active, created_at
                 UNIQUE (user_id, source_id)

items          id, source_id, external_id, owner_user_id NULL,
               url, title, author_handle, published_at, fetched_at,
               content_text, content_tsv, raw_path, content_hash
                 UNIQUE (source_id, external_id)

fetch_runs     id, source_id, collector_id NULL, started_at, finished_at,
               status, items_found, items_new, error_text

item_tags      item_id, user_id, tag, created_at
                 PRIMARY KEY (item_id, user_id, tag)
```

**Sharing.** `items.owner_user_id IS NULL` means the item is shared (Tier-1, fetched centrally). A non-null value means the item is private to that user (Tier-2/3, derived from their authenticated session). Every query filters `owner_user_id IS NULL OR owner_user_id = :me`.

**Search.** `content_tsv` is a generated `tsvector` column over title and content, with a GIN index. Postgres full-text search; no external service.

**Content storage.** `content_text` is stored in Postgres (TOAST-compressed and searchable). The raw upstream payload is written to disk at `raw_path`, enabling reprocessing after a parser change without re-scraping.

**Idempotency.** `UNIQUE (source_id, external_id)` combined with `INSERT ... ON CONFLICT DO NOTHING` makes every collection operation safe to repeat — required because collectors crash mid-push, cron double-fires, and users trigger manual runs.

**Health.** Source health is derived by querying the most recent `fetch_runs` row per source, not stored as mutable state.

## 6. Collection pipeline

### Adapter interface

```python
class Adapter(Protocol):
    kind: str          # "github_repo", "subreddit", ...
    tier: int          # 1 = server-side, 2/3 = collector-side

    def fetch(self, source: Source, since: datetime | None) -> list[NormalizedItem]:
        ...
```

```python
@dataclass
class NormalizedItem:
    external_id: str
    url: str
    title: str | None
    author_handle: str | None
    published_at: datetime | None
    content_text: str
    raw: dict
```

Adapters shell out to `agent-reach`, parse its output, and emit `NormalizedItem`. Platform-specific handling never escapes the adapter file. Adding a platform is one new module plus one registry entry.

### Execution paths

- **Server:** systemd timer → `collect --tier 1` → every active Tier-1 source.
- **Collector:** user cron → `collector run` → `GET /assignments` → fetch Tier-2/3 → `POST /items` in batches.
- **Ad-hoc:** `POST /runs` from the UI enqueues the same job for a single source.

All three paths use the identical adapter → normalize → upsert code.

### Failure handling

| Mechanism | Behavior |
|---|---|
| Per-source isolation | Each source fetches inside its own try/except; one failure never aborts the run. |
| Timeout | 120s hard cap per source, then abandon and record. |
| Backoff | On failure, retry after 2× the previous delay, capped at 24h. |
| Circuit breaker | 5 consecutive failures marks the source `needs_attention` and surfaces it in the UI. |
| Jitter | Randomized delay between fetches to avoid bot-like request patterns. |

Every attempt writes a `fetch_runs` row regardless of outcome.

## 7. Query layer, API, UI

### Query layer

The single place containing SQL. Both the API and any direct consumer (e.g. Claude Code) call these functions.

```python
search(user, q, *, kinds=None, since=None, subscribed_only=False) -> list[Item]
feed(user, limit, cursor) -> Page[Item]
get_item(user, item_id) -> Item | None
source_health(user) -> list[SourceStatus]
ask(user, question) -> Answer          # FTS top-30 → LLM → cited answer
```

The tenant-isolation filter is implemented here and nowhere else. `ask()` retrieves roughly 30 candidates via full-text search, passes them to the user's LLM with their own key, and returns a synthesized answer with links back to source items.

### API

```
POST   /auth/register         invite code + email + password → account
POST   /auth/login            email + password → session cookie
POST   /auth/logout
GET    /assignments           collector: Tier-2/3 sources to fetch
POST   /items                 collector: push normalized batch (idempotent)
GET    /feed
GET    /search
GET    /items/{id}
GET    /sources
POST   /subscriptions
DELETE /subscriptions/{id}
POST   /runs                  trigger collection for one source
GET    /health/sources
POST   /ask
GET    /settings  POST /settings        LLM key, collector tokens
```

Collectors authenticate with a bearer token; browsers with a session cookie.

### UI screens

1. **Feed** — reverse-chronological items across subscriptions.
2. **Search** — full-text search with filters for source kind and date.
3. **Item detail** — full content, source link, tags.
4. **Sources** — watchlist management, per-source health, "run now", collector token management.
5. **Ask** — natural-language question over the collection, answered with citations.

## 8. Security

| Concern | Handling |
|---|---|
| Accounts | Invite-only. Admin generates invite codes and distributes them manually; no email delivery in v1. Passwords hashed with Argon2. |
| Sessions | Cookie with `httpOnly`, `secure`, `SameSite=Lax`. |
| Collector auth | Random 32-byte bearer tokens, stored hashed, revocable per machine. |
| Platform cookies | Never transmitted to the server — guaranteed by architecture, not policy. |
| LLM keys | Encrypted at rest using a key supplied via environment variable; never returned by any endpoint. |
| Tenant isolation | Enforced in the query layer only, verified by dedicated tests. |
| Transport | Caddy reverse proxy with automatic Let's Encrypt HTTPS. |

Collections are private per user; nothing scraped is redistributed to third parties.

## 9. Testing

1. **Adapter fixtures.** One recorded real `agent-reach` response per source kind, committed to the repo. Adapter tests parse fixtures; no network access in the test suite.
2. **Isolation tests.** Two users with private items; assert no query-layer function ever returns the other user's items. Applied to every query-layer function.
3. **Idempotency tests.** Pushing the same batch twice leaves row counts unchanged.
4. **API smoke tests.** Each endpoint returns 200 when authenticated and 401 when not.
5. **Failure-handling tests.** A raising adapter does not abort a multi-source run; five consecutive failures trip the circuit breaker.

Network-dependent tests are excluded deliberately: flaky suites get ignored, and an ignored suite produces false confidence.

## 10. Deployment

Oracle Cloud Always Free VM (4 ARM cores, 24 GB RAM, no sleep, no expiry).

`docker compose` with three services:
- `postgres` — data volume on the VM
- `api` — FastAPI + built UI assets
- `caddy` — TLS termination and reverse proxy

A systemd timer on the host runs Tier-1 collection. Raw payloads are written to a mounted volume.

Users install the collector with `pip install` from the project's Git repository, run `collector login <token>` with a token issued from the UI, and add one cron entry.

## 11. Build order

Each layer is testable before the layer above it exists.

1. Schema and migrations
2. Query layer, with isolation tests
3. Adapters, against fixtures
4. Collect entrypoint and scheduler
5. JSON API
6. Collector CLI
7. React UI
8. Deployment

## 12. Risks

| Risk | Mitigation |
|---|---|
| Tier-3 sources break frequently | Circuit breaker plus visible health dashboard; breakage is expected, not exceptional. |
| Users do not install the collector | Tier-1 sources work without it; the UI states clearly which sources require a collector. |
| Free LLM tiers hit daily caps | BYOK per user, so caps are per-user rather than global. |
| Agent-Reach changes its output format | Adapters are isolated and fixture-tested; a format change breaks one file with a clear failing test. |
| Oracle reclaims idle free-tier VMs | Continuous scheduled collection keeps the instance active; database and raw payloads are backed up off-VM. |

## 13. Future extensions

Enabled by the spine without re-scraping, since raw content is retained:

- Outreach lens — entity resolution across platforms.
- Trend lens — recency and velocity ranking.
- Competitor lens — snapshot diffing over time.
- Semantic search via embeddings alongside full-text search.
- Knowledge-graph view built from stored raw content.
