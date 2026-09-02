# Task 8 Report: Live progress during collection

## What I implemented

`web/src/App.jsx`, two changes:

1. **Polling effect** — inserted verbatim from the brief, right after the mount effect. While `collecting` is true, it polls `GET /api/sources` every 2000ms, writes `sources` on every tick (so the health strip fills in progressively), and when the server reports `collecting: false` it flips local `collecting` to false and calls `loadFeed()`. Cleanup sets a `cancelled` flag and clears the interval on every path (dependency change or unmount), so a fetch that resolves after teardown can't call `setState` on a dead effect instance. On a fetch error it sets the error banner and stops polling (`setCollecting(false)`) rather than retrying forever.

2. **`select` ordering guard** — `select` now uses its own `selectIdRef` (a fresh `useRef(0)`), bumped synchronously at call start, captured as `reqId`, and checked before both the `.then` (`setSelected`) and `.catch` (`fail`) writes. This is the identical generation-counter pattern already used by `loadFeed`/`search`/`loadMore` via `requestIdRef`, but on its own counter.

## Why `select` needed its own ref, not `requestIdRef`

`requestIdRef` is shared by `loadFeed`, `search`, and `loadMore`, all of which write `items`/`cursor`. `select` writes a different piece of state (`selected`) and fires far more often — every row click. If `select` bumped `requestIdRef`, a detail click made while a `loadFeed`/`search`/`loadMore` request was still in flight would supersede that request's captured generation, and its in-flight `setItems`/`setCursor` write would be silently dropped even though nothing about the feed/search actually changed. A separate `selectIdRef` keeps the detail-pane guard fully independent of the list-pane guard.

## Verification evidence

Both servers were started per the brief (`.venv/bin/python -c "from reachstore.api.app import serve; serve()"` on :8000, `npm run dev` on :5173 in `web/`). Neither port was occupied beforehand (checked with `lsof`); both processes were started by me and killed by me at the end (PIDs 98724 and 98744 — confirmed via `lsof -ti` before `kill`, ports free afterward). I did not touch any other developer's process.

Live data: tier 1 has one real source (`https://github.blog/feed/`, an actual internet RSS feed); tier 3 has two real sources (`octocat/Hello-World`, `cli/cli` via GitHub's API/CLI adapter). All runs below hit real endpoints, not fixtures.

**Button state / health strip / auto re-enable (item 2, first half) — observed directly.** After reloading during an in-flight tier-3 run (see next point), a fresh page snapshot showed:
```
button "Collecting…" [disabled] [ref=f18e8]
```
i.e. the disabled "Collecting…" label rendered from live server state, driven by `SearchBar`'s existing `disabled={collecting}` / `{collecting ? 'Collecting…' : 'Collect'}` (unmodified, pre-existing code). I then waited 10s and re-snapshotted: the button had reverted to enabled `"Collect"` with a new element ref, i.e. React re-rendered off state my effect set. The network log for that page instance showed the full sequence: two mount-time `GET /sources` calls (React StrictMode double-invoke), then three `GET /sources` polling ticks roughly 2s apart, then a final `GET /feed` — exactly "poll until done, then reload the feed." Expanding the health strip afterward showed `cli/cli` at 202 items (item counts visibly updated from the run).

I also drove this through an actual first-click-then-observe flow (not just reload) on tier 1: `POST /api/collect` returned `202 {"started":true}`, and the following network log showed `GET /sources` then `GET /feed` firing on their own afterward — the same reload-on-completion behavior. I could not catch a live "Collecting…" DOM snapshot on that specific run because tier 1's single-source collection completes in under ~2s, faster than my tool round-trip; I rely on the tier-3 case above (where the run took long enough to survive a full page reload) as the direct visual proof, plus the network-timeline proof from tier 1 as corroboration that the same lifecycle happens regardless of which tier is used.

**Double-click surfaces "already in progress" (item 2, second half) — verified in two parts, both directly observed:**
- *Client-side same-tab guard*: via `page.evaluate`, I queried the real Collect DOM button and called `.click()` twice synchronously in one JS tick. `browser_network_requests` afterward showed exactly **one** `POST /api/collect` — the pre-existing `collectPendingRef` guard (unmodified by this task, from Task 7) absorbs a same-tab double click before a second request is ever sent. I did not modify this guard; I verified it still holds after my edits.
- *Server-side concurrent-request path*: via `page.evaluate`, I fired two raw concurrent `fetch('/api/collect', ...)` calls with `Promise.all` (guaranteeing true overlap, unlike sequential UI clicks whose round-trip latency in my tooling exceeded the collection duration). Result:
  ```
  a: { status: 202, body: { started: true,  tier: 1, reason: null } }
  b: { status: 409, body: { started: false, tier: null, reason: "a collection run is already in progress" } }
  ```
  This is the exact reason string the brief names. `collect()`'s existing branch `if (!res.ok) { setError(res.reason ?? 'could not start collection') }` (unmodified, pre-existing) renders `res.reason` straight into the visible `{error && <p className="error">{error}</p>}` banner, so I infer — from reading this unchanged code plus confirming `res.ok` is `false` for a 409 fetch Response — that a real concurrent request (e.g., two browser tabs) would show this exact message in the banner. I did not manage to force a genuine two-tab UI race (both real tier-1 and tier-3 runs completed faster than my Playwright tool round-trip between switching tabs and clicking), so the UI-rendering half of this claim is inferred from code + the isolated fetch-level proof above, not watched end-to-end pixel-for-pixel.

**Page reload during a run (item 3) — observed directly, most solid evidence in this report.** I fired a real tier-3 `POST /api/collect` from inside the page (via `fetch`) and called `location.reload()` immediately in the same `evaluate` call, i.e. right after the POST response, while the background collection was still running server-side (confirmed separately via a `curl` timing loop: a tier-3 run held `collecting: true` for several seconds). The freshly-reloaded page's very first snapshot — no click, no prior client state — showed:
```
button "Collecting…" [disabled] [ref=f18e8]
```
This is driven purely by `refreshSources()` on mount reading the server's `collecting` boolean, exactly per the brief's design rationale. I then watched that same fresh instance's polling effect detect completion (button reverted to `"Collect"`, network log showed poll ticks then an automatic `GET /feed`), confirming the whole lifecycle also works starting from a cold reload, not just from the click path.

**Python suite:** `.venv/bin/python -m pytest -q` → 116 passed. I did not modify any Python file.

**Build:** `npm run build` succeeded (21 modules transformed, no errors).

## Files changed

- `/Users/dev2/Desktop/Testing/web/src/App.jsx` — polling effect + `select` ordering guard.

## Self-review findings

- Diff matches the brief's provided code for the polling effect verbatim (no deviation).
- Effect dependency array `[collecting, loadFeed]`: `loadFeed` is `useCallback` with an empty dep array, so it's referentially stable — the effect only re-subscribes when `collecting` itself flips, not on every render. No stale-closure risk: each time `collecting` becomes true a fresh effect instance captures the then-current `loadFeed`/`setSources`/`setError`/`setCollecting`, and cleanup tears down the previous interval before a new one is created.
- Cleanup runs on every path: dependency change (`collecting` flips either way) and unmount both trigger the `return () => { cancelled = true; clearInterval(id) }` cleanup, and the in-flight-request guard (`cancelled`) is separate from the interval-clearing, per the brief's explicit decision #1.
- No progress bar, percentage, or item counter added — only `setSources(r.sources)`, feeding the existing `HealthStrip`, per decision #4.
- Interval is the literal `2000` from the brief, not a variable or config value, per decision #5.
- `select`'s guard mirrors `loadFeed`/`search`/`loadMore` exactly (bump-before-await, check-before-write in both `.then` and `.catch`) but on its own ref, satisfying the brief's explicit warning not to share `requestIdRef`.
- No new dependencies; no `package.json`/lockfile changes.
- Cleaned up incidental Playwright test artifacts (`.playwright-mcp/`) before committing so they didn't leak into the repo; confirmed `git status` was clean before commit.
- Both servers I started for verification were shut down by PID after testing; ports 8000 and 5173 confirmed free afterward. No other developer's process was touched.

## Concerns

- I could not observe a genuine two-browser-tab race reach the UI's error banner end-to-end (both real collection runs I tested completed in well under the multi-second round-trip of switching Playwright tabs and clicking). The "already in progress" claim is backed by: (a) a timing-exact proof that the server returns the exact reason string under true concurrency, and (b) unmodified, already-existing client code that visibly wires `res.reason` into the error banner for any non-ok response. I'm confident in the mechanism but did not watch the literal two-tab scenario paint pixels on screen — flagging this as inferred-not-witnessed per the task's honesty requirement, not because I think it's likely to be wrong.
