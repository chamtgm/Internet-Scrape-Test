# Task 10 report: Frontend — subscriptions

## What was implemented

All seven steps of the brief, verbatim, with the outer task instructions' correction applied (Step 5's `npm run lint` does not exist in this project — `npm run build` is the only build gate — and the SearchBar-`submit` contradiction was resolved per Ruling P1: `SearchBar.submit` was left completely untouched, and `Store.changeSubscribedOnly` owns re-running the active search).

1. **`web/src/components/SubscriptionStrip.jsx`** (new file) — copied verbatim from the brief's Step 1 code block. Collapsible catalog list with a checkbox per source, `reqIdRef` generation counter guarding `reload()` responses, `pendingRef` (a `Set` held in a `useRef`, not `useState`) guarding per-row in-flight toggles, and `reload()` called after every subscribe/unsubscribe instead of an optimistic local flip.
2. **`web/src/components/SearchBar.jsx`** — signature extended with `subscribedOnly` and `onSubscribedOnlyChange`; a `subscribed only` checkbox added before the `clear` button. `submit` was not touched — confirmed by reading the full post-edit file (see below).
3. **`web/src/components/Store.jsx`** — added `subscribedOnly` state and `lastQueryRef`; `search(q, onlySubscribed = subscribedOnly)` now remembers the query in `lastQueryRef` and passes the flag to `fetchSearch`; `loadFeed` clears `lastQueryRef.current = null`; new `changeSubscribedOnly(next)` handler sets state and re-runs the last query only if a search is active; `SearchBar` and `SubscriptionStrip` (new import) wired into the render with `onError={fail}` on the strip.
4. **`web/src/styles.css`** — the `.subs*` rule block appended verbatim after `.signout`.

## `npm run build` output

Ran twice: once with the Vite proxy pointed at the temporary verification port (8100), and once after reverting `vite.config.js` to its committed state, to prove the build has no dependency on that temporary edit. Both clean:

```
> web@0.0.0 build
> vite build

vite v8.2.2 building client environment for production...
transforming...
✓ 25 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.46 kB │ gzip:  0.29 kB
dist/assets/index-Cb7h-jSN.css    3.73 kB │ gzip:  1.14 kB
dist/assets/index-DWhwBIEE.js   201.90 kB │ gzip: 63.57 kB
✓ built in 58ms
```

There is no lint script in `web/package.json` (confirmed by reading it — only `dev`, `build`, `preview`, `seed:e2e`, `test:e2e`), so no lint step was run, per the outer task instructions.

## Explicit confirmations

- **`SearchBar.submit` is unchanged.** Read the full post-edit file: `submit` is still exactly `(e) => { e.preventDefault(); if (q.trim()) onSearch(q.trim()) else onClear() }`, untouched by the diff. The diff only adds the destructured props and the checkbox `<label>` block.
- **`/api/feed` gained no `subscribed_only`.** `web/src/api.js`'s `fetchFeed` was not touched (not even opened for editing) and never gained a new parameter. Verified live: `browser_network_requests` filtered to `/api/feed` showed five `GET /api/feed?limit=50` calls across the whole session (initial load, poll-triggered refresh, and the final "clear" click after unsubscribing) — never a `subscribed_only` query param, even while the checkbox in `SearchBar` was checked at the time.
- **`query.feed`/`/api/feed` backend confirmed parameter-free** by grep before touching anything: `subscribed_only` only appears in `src/reachstore/query.py`'s `search()` and `src/reachstore/api/routes.py`'s `/api/search` handler — never near `feed`.

## Browser hand-verification — happened, on ports 8100 (API) and 5173 (Vite, default)

Followed Task 9's pattern: started `.venv/bin/python -c "from reachstore.api.app import serve; serve(host='127.0.0.1', port=8100)"` (API) and `npm run dev` (Vite, default port 5173), after temporarily editing `vite.config.js`'s proxy target from `8000` to `8100`. Confirmed via `lsof` before and after that ports 8000 and 8001 stayed owned by the same pre-existing `php` PIDs (29601, 53638) throughout — never touched. Only killed the two processes this session started.

All five of the brief's Step 6 checks confirmed via Playwright, signed in as the real admin (`you@example.com`):

1. **Expand `subscriptions`: seeded sources listed, unchecked.** Expanded the strip — 4 sources listed (`github.blog/feed/`, a deliberately-unresolvable RSS feed, `cli/cli`, `octocat/Hello-World`), summary read `0 of 4`, all checkboxes unchecked.
2. **Check one, collapse, re-expand: stays checked.** Checked `https://github.blog/feed/` (`1 of 4`), collapsed (summary count disappears when closed, matching `open && ...`), re-expanded — still checked, proving it round-tripped through the database via `reload()`, not local state.
3. **Search a matching term, tick `subscribed only`, results stay (filtered correctly).** Searched `GitHub` (matched both the subscribed `github.blog` RSS items and unsubscribed `cli/cli` release items). Ticking `subscribed only` fired exactly one new request — `GET /api/search?q=GitHub&subscribed_only=true` — and the result list changed to only `github.blog/feed/` items; all `cli/cli` items disappeared.
4. **Uncheck the subscription, `subscribed only` search now returns nothing.** Unchecked the source in the strip (`DELETE /api/subscriptions/1` → `204`, followed only by a catalog reload — confirmed no `/api/search` request fired from the strip's own toggle, matching the brief's design that the strip never touches search). Re-toggling the `subscribed only` checkbox off/on to re-trigger `Store.changeSubscribedOnly` re-ran the search, which returned `No items.`
5. **Plain feed still shows everything.** Clicked `clear` — feed reloaded via `loadFeed` and showed the full mixed list of `cli/cli` and `github.blog/feed/` items again, unaffected by the subscription now being `0 of 4`.

Cleanup: killed only the two processes started for this task (API PID 58550, Vite wrapper PID 58556), confirmed via `lsof` that ports 8000/8001 were untouched, reverted `vite.config.js` (`git diff` on that file is empty), removed the `.playwright-mcp/` snapshot directory the browser tool wrote into the repo root (untracked, not part of this task's deliverable), and re-ran `npm run build` clean after the revert. Left the source unsubscribed and the "You" admin account's session state as the verification left it — harmless dev-database state, same precedent as Task 9's report.

## Files changed

Modified:
- `/Users/dev2/Desktop/Testing/web/src/components/SearchBar.jsx`
- `/Users/dev2/Desktop/Testing/web/src/components/Store.jsx`
- `/Users/dev2/Desktop/Testing/web/src/styles.css`

Created:
- `/Users/dev2/Desktop/Testing/web/src/components/SubscriptionStrip.jsx`

Not touched: `web/src/api.js` (already had `fetchCatalog`/`subscribe`/`unsubscribe`/`fetchSearch` from Task 9), `web/vite.config.js` (edited only temporarily for verification, confirmed reverted with an empty `git diff`), anything under `docs/superpowers/specs|plans|reviews`.

## Self-review findings

- **Completeness:** all seven steps done — SubscriptionStrip created verbatim, SearchBar checkbox + two props added, Store wiring (state, ref, `search` signature, `changeSubscribedOnly`, `loadFeed` clearing `lastQueryRef`, JSX wiring + import) all present, styles appended verbatim.
- **Discipline:**
  - `SearchBar.submit` byte-for-byte unchanged — confirmed by reading the whole file post-edit.
  - No optimistic update in `SubscriptionStrip` — `toggle` always calls `reload()` after the mutation, never mutates `entries` directly.
  - `/api/feed` never received a `subscribed_only` parameter, confirmed both by source inspection and live network capture.
  - No new dependencies (`git diff` touches nothing under `package.json`/`package-lock.json`).
  - No CORS middleware, no router — nothing in this task's diff touches `app.py` or adds routing.
  - `docs/superpowers/specs|plans|reviews` untouched (no reason to touch them).
  - `.env` untouched and still untracked.
- **Quality:** diff is a clean, minimal match to the brief's specified code — no extra abstractions, no rewritten helpers, nothing beyond what the seven steps call for.
- One thing worth flagging for the reviewer, not a defect: `changeSubscribedOnly`'s re-run only fires "if `searchingRef.current` and `lastQueryRef.current`" — an empty-string query (`q.trim()` falsy) never reaches `search` in the first place (SearchBar's `submit` calls `onClear()` instead), so `lastQueryRef.current` can never legitimately hold `''`; the falsy check only ever excludes `null`. This is exactly the brief's specified code, not a deviation.

## Concerns

None. All seven steps match the brief exactly, the build is clean, and hand-verification in a live browser confirmed every one of the five checklist behaviors, including the two concurrency guards (`reqIdRef`, `pendingRef`) behaving as intended under normal interactive use.

---

## Fix report: `Store.fail` unstable identity re-fired `/api/catalog`

Coordinator review flagged that `fail` in `Store.jsx` was a plain arrow function, recreated with a new reference on every `Store` render. That instability propagated: `fail` is passed to `SubscriptionStrip` as `onError` → `SubscriptionStrip.reload` is `useCallback(..., [onError])` → `SubscriptionStrip`'s `useEffect(() => { if (open) reload() }, [open, reload])`. A new `fail` reference each render gave `reload` a new identity each render, so any incidental `Store` re-render (selecting a feed item, a poll tick from the `[collecting, loadFeed]` effect) re-fired `fetchCatalog()` while the strip was open, even though nothing about subscriptions had changed. State stayed correct (the `reqIdRef` guard resolves to the freshest response) but it wasted a request per re-render, defeating the intent stated in `SubscriptionStrip`'s own top-of-file comment. This was the coordinator's brief's defect (the original Step 3 code block specified `fail` as a plain arrow function), not something introduced during implementation.

**Change**, in `web/src/components/Store.jsx` — the coordinator's exact one-line fix:

```js
const fail = useCallback(
  (e) => (e.status === 401 ? onSignedOut() : setError(String(e))),
  [onSignedOut],
)
```

with a comment explaining why `useCallback` here is load-bearing rather than decorative. `useCallback` was already imported. Confirmed `onSignedOut` (`App.jsx`'s `signedOut`) is itself `useCallback(() => {...}, [])` with an empty dependency array — stable for the lifetime of `App` — so this genuinely stabilises `fail` rather than just moving the churn elsewhere.

**Dependency-array check requested by the coordinator:** `fail` is referenced inside two other `useCallback`s in `Store.jsx` — `loadFeed` (deps `[]`) and `refreshSources` (deps `[me.is_admin]`) — neither lists `fail` as a dependency. I checked both and concluded **neither needs to**: this was already true before the fix (by strict exhaustive-deps standards it was technically an under-specified dependency array even then) and remains true after it, because `fail`'s behavior never varied across renders in the first place — it only closes over `onSignedOut` (stable, per the memoisation confirmed above) and `setError` (the `useState` setter, always referentially stable). Since `fail`'s *behavior* was already invariant regardless of which render's closure got captured, `loadFeed` and `refreshSources` closing over an older `fail` reference was never a correctness bug, and making `fail` itself stable doesn't change that analysis — if anything it makes the point moot, since now there's only ever one `fail` reference to capture. I did not add `fail` to either array, per the coordinator's instruction not to silently add it without confirming it's actually needed.

**Verification:**
1. `cd web && npm run build` — clean (see below). No lint step exists in this project.
2. Live browser re-verification of the specific claim (an absent `/api/catalog` call on an unrelated re-render), stronger than reasoning alone: started the API on port 8100 (`.venv/bin/python -c "from reachstore.api.app import serve; serve(host='127.0.0.1', port=8100)"`) and Vite on the default 5173 (`npm run dev`), with `vite.config.js`'s proxy temporarily pointed at 8100. Signed in as the admin (session persisted from the earlier hand-verification), opened the `subscriptions` strip (one `GET /api/catalog`), then clicked two different feed items in a row to trigger `select` → `Store` re-renders. `browser_network_requests` filtered to `/api/(catalog|items)` showed:
   ```
   GET /api/catalog        => 200   (from opening the strip)
   GET /api/items/292      => 200   (first item click)
   GET /api/items/232      => 200   (second item click)
   ```
   No second `/api/catalog` call after either click — confirms the fix. The strip itself still rendered and functioned correctly (`0 of 4` subscribed, consistent with the earlier verification session having unsubscribed the one seeded source).
3. Cleanup: killed only the two processes started for this check (API PID 59610, Vite wrapper PID 59616); confirmed via `lsof` that ports 8000/8001 stayed owned by the same pre-existing `php` PIDs (29601, 53638) throughout. Reverted `vite.config.js` (`git diff` on that file is empty). Removed the `.playwright-mcp/` snapshot directory the browser tool wrote into the repo root. Re-ran `npm run build` clean after the revert.

### `npm run build` output (post-fix)

```
> web@0.0.0 build
> vite build

vite v8.2.2 building client environment for production...
transforming...
✓ 25 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.46 kB │ gzip:  0.29 kB
dist/assets/index-Cb7h-jSN.css    3.73 kB │ gzip:  1.14 kB
dist/assets/index-C9nCrN4p.js   201.92 kB │ gzip: 63.57 kB
✓ built in 58ms
```

### Files changed (this fix)

Modified:
- `/Users/dev2/Desktop/Testing/web/src/components/Store.jsx` (the one-line `useCallback` fix plus its explanatory comment)

Not touched: `SubscriptionStrip.jsx` (fix is at the root, in `Store.jsx`, per the coordinator's instruction), `SearchBar.jsx`, `styles.css`, anything under `docs/superpowers/`.

Commit: `609c8f0` — "fix: stabilise Store's fail with useCallback (Task 10 review)"
