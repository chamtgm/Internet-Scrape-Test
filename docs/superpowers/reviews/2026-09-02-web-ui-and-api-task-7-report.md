# Task 7 Report: Search, item detail, and the health strip

## What I implemented

- `web/src/components/ItemDetail.jsx` (new) — brief's code verbatim.
- `web/src/components/SearchBar.jsx` (new) — brief's code verbatim.
- `web/src/components/HealthStrip.jsx` (new) — brief's code verbatim.
- `web/src/App.jsx` (rewritten) — brief's version, plus the in-flight guards described below.
- `web/src/components/ItemList.jsx` (modified) — added a `loadingMore` prop that disables the `.load-more` button and swaps its label to "Loading…" while a page fetch is in flight.
- `web/src/styles.css` (appended) — brief's CSS verbatim, plus one extra rule, `.load-more:disabled { opacity:.55; cursor:default; }`, to visually match the `.searchbar button:disabled` treatment for the newly-disableable load-more button.

## In-flight guard — how I implemented it, and a bug I found while verifying it

I initially implemented the guard exactly as instructed — "a boolean state is enough" — using `useState`. On first-pass manual double-click testing through Playwright that felt fine. But I then wrote a stricter test that dispatches two `button.click()` calls synchronously in the same JS tick (no `await` between them, so React gets no chance to re-render between clicks). **That test failed**: two identical `/api/feed` requests went out, and the item list grew from 50 to 150 (a duplicated page) — the exact bug this task exists to fix.

Root cause: `setLoadingMore(true)` doesn't mutate the `loadingMore` variable already captured in the `loadMore` closure that's currently attached to the DOM; the guard `if (loadingMore) return` in the *second* click's handler is still evaluating the closure from *before* the first click's state update flushed and React re-rendered. Because React (createRoot, this is React 19) batches state updates and only swaps in the new closure after a render commit, two clicks that both dispatch before that commit happens both read `loadingMore === false`.

Fix: gate on a `useRef` instead of (or in addition to) the state. Refs are a single mutable object shared by every closure regardless of which render created that closure, and mutating `.current` is synchronous — so `loadingMoreRef.current = true` set inside the *first* click's handler is visible to the *second* click's handler even though no re-render happened in between. I kept the `useState` value (`loadingMore`) purely to drive the visual `disabled`/"Loading…" UI; the actual gate that prevents the duplicate request is `loadingMoreRef`. Applied the identical pattern to the Collect button via `collectPendingRef`, per the task instructions ("apply the same reasoning to the Collect button").

```js
const loadingMoreRef = useRef(false)
...
const loadMore = () => {
  if (loadingMoreRef.current) return
  loadingMoreRef.current = true
  setLoadingMore(true)
  fetchFeed(cursor)
    .then((r) => { setItems((prev) => [...prev, ...r.items]); setCursor(r.next_cursor) })
    .catch(fail)
    .finally(() => { loadingMoreRef.current = false; setLoadingMore(false) })
}
```

Same shape for `collect`/`collectPendingRef`.

### Verification of the guard

Environment: API on :8000 (`.venv/bin/python -c "from reachstore.api.app import serve; serve()"`), Vite on :5173, driven with Playwright MCP.

**Before the ref fix** (state-only guard), forcing two `btn.click()` calls in the same tick:
```
{"before":50,"after":150,"feedRequestCount":2,
 "feedRequests":["…/api/feed?limit=50&before_id=69&before_published_at=2025-04-24T17%3A00%3A42Z",
                  "…/api/feed?limit=50&before_id=69&before_published_at=2025-04-24T17%3A00%3A42Z"],
 "clickTimeDisabledStates":[false,false]}
```
Two identical requests, duplicated page (50→150), 50 React "duplicate key" console errors as a direct symptom.

**After the ref fix**, same test (three same-tick clicks this time):
```
{"before":50,"after":100,"feedRequestCount":1,
 "feedRequests":["…/api/feed?limit=50&before_id=69&before_published_at=2025-04-24T17%3A00%3A42Z"],
 "clickTimeDisabledStates":[false,false,false]}
```
Exactly one request regardless of how many synchronous clicks landed; feed grows cleanly 50→100. (`disabled` is still `false` at click time in this stricter test — expected, since the DOM attribute only updates after React's next render; the actual blocking happens in the ref, not the attribute.)

**Collect button**, same same-tick double-click technique:
```
{"collectRequestCount":1,"requests":[{"url":"…/api/collect","method":"POST"}],
 "clickTimeDisabledStates":[false,false]}
```
Only one `POST /api/collect` fired. UI then showed `"Collecting…"` with the button disabled (driven by `collecting` flipping true after the single successful response).

I also ran a looser "two separate Playwright `.click()` calls via `Promise.all`" version first (closer to a literal user double-click, where Playwright's own actionability waits interleave real task-queue turns) — that passed even with the original state-only guard (1 request), which is *why* the stricter same-tick test mattered: it's what exposed the real race.

## Verification evidence for the five required behaviors

All done live against the real Postgres-backed API (existing data: 212 items, 4 sources, one of which — `https://this-domain-should-not-resolve-zzzzz1234.invalid/feed` — has genuine failed fetch runs with `error_text` populated from real DNS failures, no fixture needed).

1. **Search narrows the list.** Typed `codespace` into the search box, pressed Enter. Item count went from 50 (initial feed page) to 49 matching rows; "Load more" was absent (`loadMorePresent: false`). Repeated with `security`: 50 → 26. Verified via `document.querySelectorAll('.item-list .item-row').length` after each search.

2. **`clear` restores the full feed.** Confirmed via `browser_find` that the button's accessible name is exactly `clear` (matches the Task 9 contract). Clicked it after a search: item count returned to 50, first item was the newest (`GitHub CLI 2.98.0`), "Load more" reappeared and was enabled, and the search input was emptied (`searchInputValue: ""`).

3. **Clicking a row fills the right pane with full stored text and a working external link.** Clicked the "GitHub CLI 2.98.0" row. Read `.detail-title`, `.detail-meta`, `.detail-body`, and the `<a>` inside `.detail-title` via `document.querySelector`. Result: title "GitHub CLI 2.98.0", meta "cli/cli · 2026-08-20 · github-actions[bot]", body 8028 characters (starts "## Security\r\nA security vulnerability has been identified…"), link `href="https://github.com/cli/cli/releases/tag/v2.98.0"` with `target="_blank"`.

4. **The health strip expands and shows a failing source's `error_text`.** Clicked `.health-summary` (initial text: "▸ 4 sources · 3 healthy · 1 failing", matching the live `/api/sources` response). After clicking, read all four `.health-list li` rows: the failing source (`https://this-domain-should-not-resolve-zzzzz1234.invalid/feed`) showed `dot failed`, "0 items · 3 failures", and `.health-error` text `"AdapterError: HTTP request failed for https://this-domain-should-not-resolve-zzzzz1234.invalid/feed: [Errno 8] nodename nor servname provided, or not known"` — the real error text from a real failed fetch run, not a mock.

5. **The in-flight guard prevents a double-click from duplicating a page.** See the dedicated section above — verified both for Load More and Collect, with request counts captured over the network, not inferred from UI state alone.

I did **not** verify the "reload during an active run resumes the progress view" scenario end-to-end (decision #2 in the brief) — the tier-1 collection run (github.blog RSS only) completed in under 2 seconds, faster than I could reload mid-run. I did verify the *mechanism*: `refreshSources()` sets `collecting` from `r.collecting` in the `/api/sources` response on mount (unchanged from the brief), and confirmed post-run that a fresh page load correctly showed the Collect button enabled/idle because the server-side `collecting` was `false`. This is inference from a correct, unmodified read path plus a passing post-condition check, not a direct observation of the mid-run reload case — flagging that distinction explicitly rather than claiming full verification.

## Files changed

- `/Users/dev2/Desktop/Testing/web/src/App.jsx` (rewritten)
- `/Users/dev2/Desktop/Testing/web/src/components/ItemDetail.jsx` (new)
- `/Users/dev2/Desktop/Testing/web/src/components/SearchBar.jsx` (new)
- `/Users/dev2/Desktop/Testing/web/src/components/HealthStrip.jsx` (new)
- `/Users/dev2/Desktop/Testing/web/src/components/ItemList.jsx` (modified — `loadingMore` prop)
- `/Users/dev2/Desktop/Testing/web/src/styles.css` (appended)

Commit: `194b640` — "feat: search, item detail, and the health strip"

## Self-review findings

- Diff reviewed with `git diff` before commit. All four class-name/label contract items required by Task 9 (`.item-row`, `.item-title`, `.item-meta`, `.item-list`, `.empty`, `.load-more`, `.detail-title`, `.detail-meta`, `.detail-body`, `.health-summary`, `.health-list`, `.health-id`, `.health-meta`, `.health-error`, `.dot`/`.success`/`.failed`/`.never`, `aria-label="search"`, `aria-label="tier"`, button named exactly `clear`) are present unchanged from the brief — confirmed by reading the component source, not just by having pasted it.
- `.empty` coexisting in both `ItemList` (`No items.`) and `ItemDetail` (`Select an item.`) is preserved — I did not touch either message.
- Confirmed `npm run build` succeeds (Vite production build, 21 modules, no errors) as a syntax/type sanity check beyond the manual browser testing.
- No new dependencies were added (checked `web/package.json` — untouched). No router, no state manager, no CSS framework.
- Ran the full manual-verification pass a second time after the ref fix, on a fresh page load, to make sure the fix didn't regress the four non-guard behaviors — all four still pass (see evidence above).
- Checked the browser console after the fix: only the standard "Download React DevTools" info line, no errors. (Before the fix, the artificially-forced duplicate-page state produced 50 "duplicate key" React errors — expected symptom of the bug, gone after the fix.)
- Deviation from the brief's literal `ItemList.jsx` (which the brief doesn't list as a file to modify): I added the `loadingMore` prop and disabled/label handling. This was required by the calling agent's explicit instruction to fix the Task 6 review finding "as part of this task," which necessarily touches `ItemList.jsx` since that's where the `.load-more` button lives. I judged this the smallest correct change rather than duplicating a load-more button inside `App.jsx`.
- One extra CSS rule (`.load-more:disabled`) beyond the brief's verbatim CSS block — needed because the load-more button, now made disableable, had no disabled style otherwise (the brief's `.searchbar button:disabled` rule doesn't reach it, since `.load-more` sits outside `.searchbar`). One line, follows the existing pattern exactly.
- Cleaned up `.playwright-mcp/` test-run artifacts from the repo root before committing (Playwright MCP writes snapshot/console logs there by default) — not part of the task, would have been noise in `git status`.
- Servers: started API (PID 96664) and Vite (PID 96680/96694) myself on their default ports 8000/5173, both were free beforehand (checked with `lsof` first), and I stopped only those PIDs at the end — verified via `ps -p` that all three are gone and both ports are free again. Did not touch the unrelated an unrelated local project project's Vite processes also visible in `ps aux`.

## Concerns

- None blocking. The one thing worth flagging to whoever picks up Task 8/9: the guard fix (ref-based, not the plain `useState` the brief's task instructions suggested as sufficient) is a deviation from "a boolean state is enough" — I made this call because I found concrete evidence the simpler approach doesn't hold under a same-tick double click, which is precisely the scenario the original Task 6 review was warning about. Happy to explain further or revert to state-only if the ref version is considered overkill, but the test evidence above shows state-only measurably fails.

---

## Post-review fix report

Reviewer approved the `useRef` double-click guard as-is and surfaced two Important findings, both in `App.jsx`. Commit `39bfd6e` — "fix: clear stale error banner and drop out-of-order feed/search responses".

### Finding 1 — stale error banner outlives the failure that caused it

**Fix:** added `setError(null)` at the start of `loadFeed`, `search`, and `loadMore` (matching the pattern `collect` already used), and added it to `select`, which previously had no error handling of its own beyond `.catch(fail)`.

**Verified** (not just reasoned through) with Playwright against the live API, using `page.route()` to force a real 500 response, then confirming a later successful action clears the banner:

1. Forced `/api/search` to return 500 once. Submitted a search. Observed `.error` text: `"Error: 500 Internal Server Error"`. Then clicked an item row (a `select` call, unroute'd so it succeeds). Observed `.error` is `null` afterward.
2. Forced `/api/feed?...before_id=...` (a "Load more" request) to return 500. Clicked "Load more". Observed the banner. Then unrouted and clicked `clear` (a `loadFeed` call). Observed the banner cleared (`null`).

Both observed directly via `document.querySelector('.error')?.textContent` before and after, not inferred from code reading alone.

### Finding 2 — out-of-order responses corrupting the list

**Fix:** added `requestIdRef` (a `useRef(0)` generation counter, same pattern as the existing double-click guard refs). `loadFeed`, `search`, and `loadMore` each bump it and capture the value at call time; each `.then`/`.catch` applies its `setItems`/`setCursor`/`fail` only if `requestIdRef.current` still equals the captured id. `select` and `collect` were left untouched — they don't write `items`/`cursor`, and the reviewer scoped the counter to the three that do.

**Verified with a real slow/fast interleaving**, not by reasoning alone, using `page.route()` to delay one endpoint and `page.on('response')` to record actual arrival order with timestamps:

**Race A — slow "Load more" vs. fast search** (the reviewer's primary example):
- Delayed `/api/feed?...before_id=...` (the load-more request) by 3s via `page.route`.
- Clicked "Load more" (fires the slow request), then ~150ms later submitted a search for "security" (fires a fast, un-delayed request).
- Recorded actual response arrival via `page.on('response')`: `/api/search?q=security` → `200` at **237ms**; `/api/feed?...before_id=64...` → `200` at **3070ms** (i.e. it really did land nearly 3s after the search, and really did resolve 200 — not cancelled, not aborted).
- Final DOM state, captured after both responses had landed: **26 items**, exactly matching the search result set and titles, "Load more" hidden (correct — still searching). The late `/api/feed` response was accepted by the network layer but silently dropped by the app instead of being appended, so the list was never corrupted into a mixed 76-item set.
- Before the fix this exact scenario is the one described in the finding: the stale append would have landed on top of the search results.

**Race B — slow search vs. fast clear** (the reviewer's named secondary case):
- Delayed `/api/search*` by 3s.
- Submitted a search for "security" (slow), then ~150ms later clicked `clear` (fires a fast, un-delayed `loadFeed`).
- Recorded response order: `/api/feed?limit=50` → `200` (fast), `/api/search?q=security` → `200` (arrived ~3s later, confirmed landed, not cancelled).
- Final DOM state: 50 items (the fresh feed), first item matches the newest feed row, "Load more" visible again, search input empty. The late, stale search response did not clobber the feed that `clear` had already loaded.

I did not attempt to reproduce a third race (e.g. two overlapping searches) since neither the reviewer's finding nor my own reading of the code suggested one exists that this counter doesn't already cover — the same generation-ref mechanism protects every pairing among `loadFeed`/`search`/`loadMore` since they all share one counter.

### Build and process hygiene

- `npm run build` passed after the fix (21 modules, no errors) — re-ran this myself rather than relying solely on the reviewer's confirmation from before the fix, since the fix touched the file that was built.
- Started a new API instance (PID 97848) and Vite instance (PID 97853) on the same default ports (8000/5173, confirmed free beforehand with `lsof`) since the ones from the initial verification pass had already been stopped when that round of work was reported done. Stopped both at the end of this round, confirmed via `ps -p` and a re-check of `lsof` that both ports are free. No other process was touched.
- Removed the `.playwright-mcp/` directory Playwright MCP writes snapshot/console logs into by default — not part of the diff, cleaned up before committing so it doesn't show as untracked noise.

### Files changed (this round)

- `/Users/dev2/Desktop/Testing/web/src/App.jsx` only.

Commit: `39bfd6e` — "fix: clear stale error banner and drop out-of-order feed/search responses"
