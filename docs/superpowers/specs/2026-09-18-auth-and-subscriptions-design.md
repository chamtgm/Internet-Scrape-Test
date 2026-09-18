# Auth and Subscriptions — Design

**Status:** design, approved in conversation 2026-09-18. Not yet implemented.
**Supersedes:** the "Auth, registration, sessions" and "Subscriptions write path" lines in §13 of `2026-08-31-web-ui-and-api-design.md`.
**Follows:** Plan 1 (core store, shipped) and Plan 2's web slice (shipped, merged at `af21a1b`).

---

## 1. Overview

reachstore serves one hard-coded user. `api/deps.py` defines `DEFAULT_USER_ID = 1` and passes it to the three `query` functions that take a `user_id`. That constant exists so the tenant-isolation path stays live and exercised; replacing it with a real identity is this slice's purpose.

Two things ship together:

- **Identity** — real accounts, invite-only, server-side sessions, and an admin role that gates the operator controls.
- **Subscriptions** — the per-user interest table that already exists in the schema with no write path, which is why `query.search(subscribed_only=True)` is currently unreachable code.

They ship together because subscriptions are meaningless without knowing who is asking, and because subscriptions are a small addition once identity exists.

`ask()` LLM synthesis is deliberately **not** here. It is a different shape of problem — prompt construction, an Ollama dependency, streaming, and a quality question with no test-suite answer — and bundling it would mean a disagreement about prompts blocks login. It gets its own spec.

## 2. Goals and non-goals

**Goals**

- Up to 50 people have separate accounts, separate subscriptions, and separate private items should a later slice create any.
- Access is invite-only: an operator runs a CLI command, hands over a one-time link, and the invitee sets their own password.
- Operator controls — source health and triggering collection — are restricted to admins.
- `query.search(subscribed_only=True)` becomes reachable.
- `DEFAULT_USER_ID` is deleted.

**Non-goals**

- Defending against the public internet. See §9.
- Password reset by email. There is no mail transport in this project and adding one is not free. An admin resets a password from the CLI.
- Per-user collection, private items, or per-user LLM keys. `users.llm_provider` and `users.llm_key_encrypted` stay unused; they belong to the `ask()` spec.
- OAuth, SSO, 2FA, or a "remember me" distinction.

## 3. Key decisions

Each of these was decided in conversation; they are recorded so the reasoning survives.

**Localhost only.** The loopback guard added in the previous slice stays. Logins exist to separate people sharing one machine, not to withstand the internet. This decision is what makes it legitimate to omit HTTPS, CSRF tokens, and login rate limiting — see §9, which states the consequences explicitly rather than leaving them as gaps someone discovers later.

**Server-side sessions, not a signed stateless cookie.** A `sessions` row can be deleted, which logs that person out instantly and everywhere. For a tool where access is granted and revoked by hand, revocation is the feature that matters. The cost is one indexed `SELECT` per request, on a connection the request already opens.

**Invite by CLI, password set by the invitee.** The operator never learns anyone's password, nothing is emailed, and a leaked invite expires and works once.

**Subscriptions filter reading only.** Collection stays tier-driven; `collect.py` is untouched. Gating collection on subscriptions would break the store-raw principle — unsubscribe for a month and that month is permanently missing from history.

**Admin-only operator controls, via one boolean.** `users.is_admin`. Two dependency checks and one column, rather than a role table.

**Password hashing with stdlib `hashlib.scrypt`.** No new dependency. Parameters `n=2**15, r=8, p=1, maxmem=64 MiB, dklen=64`, measured at 41 ms on this machine — slow enough to make offline brute force expensive, fast enough that a login feels instant. Argon2 is the more modern recommendation but costs a dependency for no gain against this threat model.

## 4. Architecture

One new module owns the entire boundary between "a request" and "an identity":

```
src/reachstore/api/auth.py     ← passwords, sessions, invites, the two dependencies
```

Nothing else may turn a cookie into a user. This is the same discipline as `query.visible_to` being the sole tenant predicate: one function to audit, one place to get it right.

`auth.py` exposes:

```python
# password handling
hash_password(password: str) -> str                    # "scrypt$n$r$p$<b64 salt>$<b64 dk>"
verify_password(password: str, encoded: str) -> bool   # constant-time compare

# session lifecycle
create_session(session, *, user_id: int, now: datetime) -> str   # returns the raw token
lookup_session(session, *, token: str, now: datetime) -> User | None
delete_session(session, *, token: str) -> None

# FastAPI dependencies
get_current_user(...) -> User    # 401 if absent, unknown, or expired
require_admin(...) -> User       # 403 unless user.is_admin
```

`create_session` returns the raw token; only its SHA-256 digest is stored. A database dump therefore contains no usable sessions — the same reasoning that applies to passwords.

`lookup_session` deletes an expired row as it passes over it, so expiry needs no scheduler.

**Concrete values**, stated here so they are not invented twice in different places:

| Thing | Value |
|---|---|
| Cookie name | `reachstore_session` |
| Cookie attributes | `HttpOnly`, `SameSite=Lax`, `Path=/`, no `Secure` (see §9) |
| Session lifetime | 30 days from issue, not sliding |
| Invite lifetime | 7 days from issue |
| Token entropy | `secrets.token_urlsafe(32)` — 256 bits, 43 characters |
| Stored form | `hashlib.sha256(token).hexdigest()`, 64 characters |

A non-sliding session means someone is asked to log in again a month after they first did, regardless of activity. For a localhost tool that is a fair trade against the extra write on every request that a sliding window costs.

**The clock.** `auth.py` takes `now` as a parameter on every function that needs it, consistent with the project-wide invariant. The route handlers, which are entrypoints, supply `datetime.now(UTC)`.

## 5. Data model

### 5.1 Changes

**`users` gains one column:**

```python
is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa.false())
```

`password_hash` already exists as `Text` with `default=""`. It is reused, and an empty value now means "not a usable account" — see §5.3.

**New `sessions` table**, mapped by a model named **`UserSession`**, not `Session` — `models.py` and every module that touches it also import `sqlalchemy.orm.Session`, and two different `Session` names in one file is a trap:

| Column | Type | Notes |
|---|---|---|
| `id` | `BigInteger` PK | |
| `user_id` | FK `users.id` `ON DELETE CASCADE` | deleting a user logs them out as a side effect |
| `token_hash` | `String(64)` unique | SHA-256 hex of the cookie token; never the token itself |
| `created_at` | `TIMESTAMPTZ` | |
| `expires_at` | `TIMESTAMPTZ` | checked after the lookup; the unique index on `token_hash` is what makes the lookup cheap |

**New `invites` table:**

| Column | Type | Notes |
|---|---|---|
| `id` | `BigInteger` PK | |
| `email` | `String(320)` | not unique — re-inviting is a new row |
| `display_name` | `String(120)` | |
| `is_admin` | `Boolean` | what the created account will be |
| `token_hash` | `String(64)` unique | SHA-256 hex |
| `created_at` | `TIMESTAMPTZ` | |
| `expires_at` | `TIMESTAMPTZ` | 7 days |
| `consumed_at` | `TIMESTAMPTZ` nullable | non-null means spent |

### 5.2 Why invites are a separate table

The alternative is creating the `users` row up front with an empty password and an invite token on it — and the existing `password_hash` default of `""` suggests the original schema imagined exactly that.

It is rejected because a separate table makes **a `users` row always denote a usable account**. Otherwise every query touching users carries an implicit "…unless it is a pending one", which holds until someone forgets it. Making the invalid state unrepresentable beats guarding it everywhere.

### 5.3 The one exception, and how it is contained

There is already a `users` row — `hand-verify@example.com`, id 1 — left over from hand-verification during Plan 1. It has `password_hash == ""`.

Rather than special-case it in a migration, `verify_password` returns `False` for any empty or malformed encoded hash, and `login` rejects it. Such a row can therefore never authenticate. The operator may delete it; nothing requires them to. This is the only place where "a users row that cannot log in" exists, and it is closed by one guard in one function rather than a condition spread across queries.

### 5.4 Migration

`migrations/versions/0002_auth_and_sessions.py`, following `0001_initial.py`'s conventions exactly: `revision = "0002"`, `down_revision = "0001"`, plain string identifiers, `sqlalchemy as sa` and `from alembic import op`.

It adds the `is_admin` column with a server default so existing rows are valid, and creates the two tables. `downgrade()` drops them and the column.

**No data migration.** All 218 existing items have `owner_user_id IS NULL`, meaning shared, and stay visible to every logged-in user. There are zero existing subscriptions.

## 6. The invite and setup flow

Three CLI commands, following `cli.py`'s existing Typer conventions and its `_session()` helper:

```
reachstore invite <email> --name "<display name>" [--admin]
reachstore set-password <email>
reachstore revoke-sessions <email>
```

`invite` creates an `invites` row and prints the setup URL:

```
<WEB_BASE_URL>/?setup=<token>
```

`WEB_BASE_URL` is a new optional setting in `config.py`, defaulting to `http://127.0.0.1:5173`. It has to be configurable because the frontend is served from two different places: Vite on port 5173 in development, and FastAPI itself from `web/dist` on port 8000 in production. A hardcoded port would print a dead link in one of those two modes.

The token is shown exactly once, because only its hash is stored. Re-running `invite` for the same email issues a fresh invite; the earlier one remains valid until it expires unless explicitly revoked, which is acceptable for a hand-operated tool.

`set-password` prompts twice, without echo, and writes the hash. It serves two purposes: bootstrapping the very first admin, and resetting a forgotten password — which is why §2 can list email reset as a non-goal without leaving people locked out.

`revoke-sessions` deletes every session row for that user. It is the "someone left" operation, and it is why §3 chose server-side sessions.

**Bootstrapping, concretely.** On a fresh install the operator runs `invite <their email> --name "..." --admin` and opens the printed link. No migration needs to nominate an admin, and no test row gets blessed with privileges it should not have.

## 7. API surface

All paths keep the `/api` prefix. Three access levels.

### Public

**`POST /api/auth/login`** — body `{email, password}`. On success sets the session cookie and returns the user. On failure returns **401 with one identical message for both an unknown email and a wrong password**, and verifies against a dummy hash in the unknown-email case so the response time matches. Without that, timing becomes a user-enumeration oracle.

**`POST /api/auth/setup`** — body `{token, password}`. Validates an unconsumed, unexpired invite; creates the `users` row with the invite's `email`, `display_name`, and `is_admin`; stamps `consumed_at`; logs the new user in. Rejects with 400 if the token is unknown, spent, or expired. If a user with that email already exists, rejects with 409 rather than silently taking over the account.

**`GET /api/auth/me`** — callable without a session, which is why it sits here; returns `{id, email, display_name, is_admin}` when one exists and 401 when it does not. The frontend calls this on mount to decide what to render.

### Any logged-in user

**`GET /api/feed`**, **`GET /api/search`**, **`GET /api/items/{item_id}`** — unchanged in shape; `DEFAULT_USER_ID` becomes `user.id`. `GET /api/search` gains a `subscribed_only: bool = False` query parameter, passed through to the existing `query.search` parameter of the same name.

**`POST /api/auth/logout`** — deletes the session row and clears the cookie. Idempotent: logging out twice is 200, not an error.

**`GET /api/catalog`** — every source, projected to `{source_id, kind, identifier}` only. This is what the subscription UI lists.

**`GET /api/subscriptions`** — the current user's subscriptions: `{source_id, label, active}`.

**`PUT /api/subscriptions/{source_id}`** — subscribe. Idempotent, via `ON CONFLICT DO NOTHING` against the existing `uq_subscriptions_user_source` constraint, consistent with how the project achieves idempotency everywhere else: in the database, never by an application-level existence check.

**`DELETE /api/subscriptions/{source_id}`** — unsubscribe. Idempotent.

### Admin only

**`GET /api/sources`** — unchanged shape, now behind `require_admin`. Returns full health: `last_status`, `error_text`, `consecutive_failures`, `item_count`, plus the `collecting` flag.

**`POST /api/collect`** — unchanged, now behind `require_admin`.

### 7.1 Why `/api/catalog` exists rather than opening `/api/sources`

Fix F4 of Plan 1 left a note that `source_health` must be reconsidered once subscriptions gained a write path, because a source identifier can carry a credential — a tokenised feed URL, a private repository name.

That note comes due here, and resolving it surfaced a fact worth recording: **`ItemSummary.source_identifier` is already returned to every reader and rendered in every feed row** (`web/src/components/ItemList.jsx`). Identifiers are therefore already visible to any logged-in user, and pretending otherwise would require removing them from the feed and breaking every row label.

So the operator-only content is not the identifier. It is the failure diagnostics and the control: `error_text`, run status, failure streaks, other users' item counts, and the ability to start a run. `/api/sources` keeps all of that behind `require_admin`. `/api/catalog` exposes strictly the fields the feed already exposes, which is what a reader needs to choose what to subscribe to, and nothing more.

## 8. Subscriptions behaviour

A subscription is a **reading preference**, not a collection instruction. Collection continues to walk every source in a tier.

Two places it takes effect:

- `GET /api/search?subscribed_only=true` — passes through to the existing `query.search` parameter, which joins `subscriptions` on `user_id` and `active`. No new SQL: the query layer already implements this and has had no caller.
- The subscription strip in the UI, which is how a user sets them.

The feed is **not** filtered by subscription and continues to show everything visible. A new account therefore sees a populated feed rather than an empty one, and subscription becomes a narrowing tool rather than a setup chore.

`subscriptions.label` stays nullable and unused by this slice; it exists for a later per-user renaming feature.

## 9. Security posture

This section states what is *not* defended and why, so a later reader can tell a deliberate omission from an oversight.

**The network boundary is the access control.** `assert_loopback` refuses to bind a non-loopback interface without `REACHSTORE_ALLOW_NONLOCAL=1`. Everything below is contingent on that.

| Measure | Status | Reasoning |
|---|---|---|
| Password hashing | **Built** — scrypt, 41 ms | Cheap, and a leaked dump must not yield passwords. |
| Session tokens hashed at rest | **Built** — SHA-256 | A dump must not yield live sessions. |
| `HttpOnly` cookie | **Built** | Stops page script reading the session. Directly relevant: last slice shipped a `javascript:`-capable `href` from untrusted feed data. |
| `SameSite=Lax` | **Built** | Free baseline CSRF mitigation. |
| No user enumeration on login | **Built** | Identical 401 and matched timing. |
| Revocable sessions | **Built** | `revoke-sessions`, plus FK cascade. |
| `Secure` cookie flag | **Not set** | There is no HTTPS on localhost; setting it would break the cookie entirely. |
| HTTPS | **Not built** | Localhost only. |
| CSRF tokens | **Not built** | `SameSite=Lax` covers the realistic case at this threat model. |
| Login rate limiting | **Not built** | No remote attacker can reach the port. |
| Password strength rules | **Minimal** — 8 character floor | Arbitrary complexity rules push people toward reuse. |
| Email-based reset | **Not built** | No free mail transport; `set-password` covers it. |

**If this is ever exposed beyond localhost, the five "not built" rows become required work.** That sentence exists so the decision to expose it cannot quietly skip them.

## 10. Frontend

No router. The app deliberately has none, and two screens do not justify one.

`App.jsx` gains a three-way decision on mount:

1. `?setup=<token>` present in `window.location.search` → render `<Setup>`.
2. `GET /api/auth/me` returns 401 → render `<Login>`.
3. Otherwise → render the app shell as today, with `me` in state.

Three new components:

- **`Login.jsx`** — email, password, submit. Shows the server's message on 401.
- **`Setup.jsx`** — reads the token from the URL, takes a password twice, calls `POST /api/auth/setup`, then drops into the app. Clears the token from the URL on success via `history.replaceState` so the spent token is not left in the address bar or in history.
- **`SubscriptionStrip.jsx`** — collapsible, same shape as `HealthStrip`. Lists `/api/catalog` with a checkbox per source reflecting `/api/subscriptions`.

Changes to existing components:

- **`HealthStrip` and the Collect button render only when `me.is_admin`.** A non-admin never calls `/api/sources`, so the 403 never occurs in normal use. Because `collecting` is sourced from that endpoint, non-admins also never poll — which is correct, since they cannot start a run.
- **`SearchBar`** gains a "subscribed only" checkbox, passed through to the search call.
- **A header shows the display name and a Logout button.**

`api.js` gains `fetchMe`, `login`, `logout`, `setup`, `fetchCatalog`, `fetchSubscriptions`, `subscribe`, `unsubscribe` — all `credentials: 'same-origin'`, which is the default for same-origin requests and is stated here only to make the cookie's path explicit. No `fetch` moves outside `api.js`.

## 11. Testing

**The largest single work item in this slice is retrofitting the existing suite.** `tests/test_api_read.py` (7 tests), `tests/test_api_sources.py` (4) and `tests/test_api_collect.py` (7) all build an unauthenticated `TestClient` and will fail the moment the endpoints require a session. `tests/test_api_app.py` (3) tests `assert_loopback` directly and is unaffected.

The fix is a fixture, not eighteen edits: `conftest.py` gains `admin_client` and `user_client` fixtures that create a user, a session row, and a `TestClient` carrying the cookie. Each existing test then changes only which client it asks for. Test data seeded per test, rolled back per test, as today.

New coverage:

- **`auth.py` unit tests** — hash round-trip; wrong password rejected; empty and malformed encoded hashes rejected (the §5.3 guard); a tampered hash rejected; session create/lookup/delete; expired session rejected *and* deleted; token not recoverable from the stored row.
- **A permission matrix test.** One parameterised test asserting, for every endpoint, the status an anonymous caller, a logged-in non-admin, and an admin each receive. This is the test that catches a future endpoint added without a dependency — the failure mode a per-endpoint test cannot see.
- **Invite flow** — setup consumes the invite; a second use is rejected; an expired invite is rejected; an invite for an existing email is 409; the created account's `is_admin` matches the invite.
- **Login** — unknown email and wrong password return an identical response.
- **Subscriptions** — subscribe is idempotent; unsubscribe is idempotent; one user's subscriptions are invisible to another; `search(subscribed_only=True)` narrows to subscribed sources and returns nothing when the user has none.
- **Tenant isolation, end to end** — two users, one private item each, asserted through the HTTP layer rather than only at `query`. The existing isolation tests cover `query`; this covers the path that now determines `user_id`.

**Playwright.** The four existing browser tests need a logged-in session; the seed script gains an admin account with a known password, and the spec file logs in first. Two tests added: a login round-trip, and the setup flow consuming an invite. The suite stays hermetic against the test database.

**The suite stays offline.** Nothing here makes a network call.

## 12. Changes to existing code

| File | Change |
|---|---|
| `models.py` | `users.is_admin`; `UserSession` and `Invite` models |
| `migrations/versions/0002_*.py` | new |
| `api/auth.py` | new |
| `api/deps.py` | **delete `DEFAULT_USER_ID`** |
| `api/routes.py` | dependencies on every endpoint; `subscribed_only` parameter; the catalog and subscription endpoints |
| `api/schemas.py` | auth, catalog, and subscription models |
| `cli.py` | `invite`, `set-password`, `revoke-sessions` |
| `tests/conftest.py` | `admin_client` / `user_client` fixtures |
| `tests/test_api_*.py` | adopt the fixtures |
| `web/src/*` | three new components; `App.jsx`, `SearchBar`, `api.js` updated |
| `web/tests/*` | log in first; two new tests |
| `docs/architecture.md` | §3 invariants, §4 data model, §7 web layer, §9 decisions |

`query.py`, `store.py`, `collect.py`, and every adapter are **untouched**. That is a deliberate check on this design: if identity required changing the collection or storage layers, the boundaries would be wrong.

## 13. Build order

1. Migration and models — `is_admin`, `sessions`, `invites`.
2. `api/auth.py` with its unit tests. No endpoints yet; pure functions and dependencies, tested directly.
3. `conftest.py` fixtures plus the retrofit of the 18 existing API tests. Done before the endpoints change, so the suite is green at every step.
4. Auth endpoints: `login`, `logout`, `me`.
5. Dependencies applied to existing endpoints, plus the permission matrix test.
6. CLI: `invite`, `set-password`, `revoke-sessions`.
7. `POST /api/auth/setup` and the invite flow tests.
8. Catalog and subscription endpoints, plus `subscribed_only` on search.
9. Frontend: `Login`, `Setup`, the `me` gate, logout.
10. Frontend: `SubscriptionStrip`, the subscribed-only toggle, admin-gated `HealthStrip`.
11. Playwright: log in first; login and setup tests.
12. `docs/architecture.md`.

Steps 1–8 are usable from `curl` before any frontend change.

## 14. Risks

| Risk | Mitigation |
|---|---|
| The 18 existing API tests are retrofitted sloppily, weakening coverage | Step 3 happens before endpoints change, so the suite must stay green; a diff that alters an assertion rather than just the client is a review finding |
| A future endpoint ships with no dependency | The permission matrix test enumerates endpoints, so a new one fails until it is classified |
| Operator locks themselves out | `set-password` exists precisely for this and needs only database access |
| Session fixation | A fresh token is issued on login and on setup; no token is ever accepted from a request parameter |
| Someone sets `Secure` on the cookie "for safety" and breaks localhost | §9 records it as deliberate, with the reason |
| `hand-verify@example.com` treated as a real account | §5.3: `verify_password` rejects an empty hash, so it cannot authenticate |

## 15. Out of scope, recorded for later

- `ask()` LLM synthesis, per-user LLM keys, and encrypting `llm_key_encrypted` — its own spec, next.
- Per-user collection and private items. `owner_user_id` stays `NULL` for everything this slice creates.
- Add/remove sources from the browser.
- `subscriptions.label` as a user-facing rename.
- Multi-worker deployment; still requires replacing the in-process collect guard.
- Anything in §9's "not built" column, which becomes required if this is ever exposed beyond localhost.
