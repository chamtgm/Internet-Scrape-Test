# Task 9 report: Frontend — the login gate

## What was implemented

All ten steps of the brief, verbatim except where the task instructions explicitly corrected the brief (Step 8's `npm run lint`, which does not exist — `npm run build` is the only build gate, per the task instructions).

1. **`web/src/api.js`** rewritten: added `ApiError` (carries `.status`), a `send()` helper for POST/PUT/DELETE, `fetchMe()` returning `null` on 401, `login`, `setupAccount`, `logout`, `fetchCatalog`, `subscribe`, `unsubscribe`, and `fetchSearch` gained a `subscribedOnly` parameter. `get()` now throws `ApiError` instead of a bare `Error`.
2. **`web/src/components/Login.jsx`** created — email/password form, `busy`-disabled submit, single "Email or password is incorrect." message for any 401.
3. **`web/src/components/Setup.jsx`** created — password/confirm form, client-side length and match checks, clears the `#setup=` fragment via `history.replaceState` on success.
4. **`web/src/components/Store.jsx`** created — the entire former body of `App.jsx` moved verbatim, with exactly the five changes the brief specifies (detailed below).
5. **`web/src/App.jsx`** rewritten as the gate — three-state `me` (`undefined`/`null`/object), reads `#setup=<token>` from the URL fragment, renders `Setup`, `Login`, or `Store`.
6. **`web/src/components/SearchBar.jsx`** — added `canCollect` prop; tier `<select>` and Collect button now render only when `canCollect` is true.
7. **`web/src/styles.css`** — appended the `.booting`, `.auth*`, `.header-row`, `.whoami`, `.badge`, `.signout` rules exactly as specified.
8. Build verified (see output below). No lint step exists in this project (confirmed: `package.json` only has `dev`, `build`, `preview`, `seed:e2e`, `test:e2e`), so none was run, per the task instructions' correction of the brief.
9. Hand-verified in a real browser — see below.
10. Committed — see commit list at the end.

## `npm run build` output

```
> web@0.0.0 build
> vite build

vite v8.2.2 building client environment for production...
transforming...
✓ 24 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.46 kB │ gzip:  0.29 kB
dist/assets/index-kSVfLk30.css    3.26 kB │ gzip:  1.07 kB
dist/assets/index-DKiBOrMX.js   200.08 kB │ gzip: 63.10 kB

✓ built in 61ms
```

Ran twice — once mid-verification (with the proxy temporarily pointed at port 8100) and once after reverting `vite.config.js` to its committed state, to confirm the build has no dependency on that temporary change. Both clean.

## Exactly what differs between the old `App.jsx` body and `Store.jsx`

Diffed `git show HEAD:web/src/App.jsx` against the new `web/src/components/Store.jsx`. Five hunks, matching the brief's five listed changes one-to-one, nothing else:

1. **Signature and imports.** `export default function App()` → `export default function Store({ me, onSignedOut })`. Import paths adjusted for the new file location (`./api` → `../api`, `./components/X` → `./X`), and `logout` added to the `../api` import.
2. **`fail`** gained the 401 branch: `const fail = (e) => setError(String(e))` → `const fail = (e) => (e.status === 401 ? onSignedOut() : setError(String(e)))`, with the brief's comment above it.
3. **`refreshSources`** gained the admin guard `if (!me.is_admin) return Promise.resolve()` as its first line, and its `useCallback` dependency array changed from `[]` to `[me.is_admin]`. Nothing else in the function body changed.
4. **`signOut`** added as a new function (`try { await logout() } finally { onSignedOut() }`), placed after `collect` and before the returned JSX.
5. **The header JSX** changed from a bare `<SearchBar .../><HealthStrip .../>` pair to `SearchBar` gaining a `canCollect={me.is_admin}` prop, `HealthStrip` wrapped in `{me.is_admin && ...}`, and a new `.header-row` / `.whoami` block showing `me.display_name`, an admin badge, and the sign-out button.

Everything else — every `useState`, every `useRef` with its original comment (`loadingMoreRef`/`collectPendingRef` same-tick guard, `requestIdRef` generation counter, `sourcesIdRef` ordering guard, `searchingRef` stale-closure mirror, `selectIdRef` own counter), `loadFeed`, both `useEffect`s (including the polling effect's `[collecting, loadFeed]` dependency array, left untouched as instructed), `select`, `search`, `loadMore`, `collect`, and the rest of the returned JSX (`error` banner, `main.panes`, `ItemList`, `ItemDetail`) — is byte-for-byte identical to the old `App.jsx` body.

## Hand-verification

Performed in a real browser via the Playwright MCP tool, against a live API and Vite dev server I started myself.

**Ports used:** API on `127.0.0.1:8100` (started with `.venv/bin/python -c "from reachstore.api.app import serve; serve(host='127.0.0.1', port=8100)"`, PID 56543), Vite dev server on the default `5173` (PID 56564, via `npm run dev`). Port 8000 and 8001 were left untouched — confirmed still owned by the pre-existing `php` processes (PIDs 29601 and 53638) both before and after. `vite.config.js`'s proxy target was temporarily edited from `8000` to `8100` for the verification, then reverted to `8000` before committing (confirmed via `git diff` showing no change to that file, and a clean rebuild afterward).

All five checklist items from the brief's Step 9 confirmed:
- **Anonymous visit shows the login form, not an error banner.** Confirmed via snapshot — only the `reachstore` heading, email/password fields, and "Sign in" button rendered. (The browser's own devtools network log did record two 401 responses to `/api/auth/me` — that is normal browser-level logging of any non-2xx fetch, not an app-level error banner; `fetchMe()` caught it and returned `null` as designed. Two, not one, because React 19 dev mode double-invokes effects under StrictMode-equivalent behavior; this does not happen in the production build.)
- **Wrong password shows "Email or password is incorrect."** Confirmed by submitting `you@example.com` / a wrong password — exact string rendered.
- **After signing in (admin), the feed loads and the health strip and Collect button are present.** Confirmed with the real admin account (`you@example.com` / `Reachstore-Setup-2026!`): feed populated with GitHub blog/CLI items, health strip showed "4 sources · 3 healthy · 1 failing", tier select and Collect button both present, "You" + admin badge + sign-out button all rendered.
- **Sign out returns to the login form.** Confirmed — clicking "sign out" (`POST /api/auth/logout` returned 200 in the API log) returned to the bare login form.
- **Reloading while signed in shows the feed with no login flash.** Confirmed — full page navigation to `/` while the session cookie was still valid rendered the feed directly.

**Additional verification beyond the checklist** (useful given `Setup.jsx` and the admin-gating logic are new code, not covered by any Python test):
- Issued a real invite via `reachstore invite task9-verify@example.com --name "Task9 Verify"`, confirmed the printed link uses the `#setup=<token>` fragment form (matches the brief's claim about Task 6's `invite` command).
- Navigated to that link, confirmed the `Setup` form rendered with "Choose a password".
- Submitted matching passwords, confirmed the URL fragment was cleared (`history.replaceState` worked) and the app landed directly in `Store` as the new non-admin user.
- Confirmed **non-admin gating end-to-end**: no admin badge, no `HealthStrip`, and no tier-select/Collect button rendered for the non-admin account, while the feed still loaded and sign-out still worked. This is the client-side half of the admin gate the brief calls for (Step 6 + Step 4 change 5); the server-side 403 is out of this task's scope (already pinned by a Task 5 test per the brief).

One incidental, unrelated finding: navigating Playwright to `http://127.0.0.1:5173` failed with `ERR_CONNECTION_REFUSED` while `http://localhost:5173` worked — the Vite dev server's Node process was listening on the IPv6 loopback only. This is pre-existing Vite/Node behavior unrelated to this task's changes (same `vite.config.js` `server.port` setting as before), not a regression, and does not affect anything committed.

Cleanup after verification: killed only the two processes I started (API PID 56543, Vite PID 56564 — the `npm run dev` wrapper's own PID 56550 exited when its child did), confirmed with `lsof` that ports 8000/8001 (the pre-existing `php` processes) were never touched, reverted `vite.config.js`, removed the `.playwright-mcp/` snapshot/log directory the browser tool wrote into the repo root (untracked, not part of this task's deliverable), and re-ran `npm run build` clean. Left the `task9-verify@example.com` account and its session in the dev database — a legitimate account created the same way Tasks 6/7 create theirs, harmless to leave for any later manual testing.

## Files changed

Modified:
- `/Users/dev2/Desktop/Testing/web/src/api.js`
- `/Users/dev2/Desktop/Testing/web/src/App.jsx`
- `/Users/dev2/Desktop/Testing/web/src/components/SearchBar.jsx`
- `/Users/dev2/Desktop/Testing/web/src/styles.css`

Created:
- `/Users/dev2/Desktop/Testing/web/src/components/Login.jsx`
- `/Users/dev2/Desktop/Testing/web/src/components/Setup.jsx`
- `/Users/dev2/Desktop/Testing/web/src/components/Store.jsx`

Not modified (verified clean after temporary edit for hand-verification):
- `/Users/dev2/Desktop/Testing/web/vite.config.js`

## Self-review findings

- Diffed `Store.jsx` against the old `App.jsx` body (see above) — exactly the five changes the brief lists, nothing more. All six `useRef` comments preserved character-for-character.
- Diffed `api.js`, `App.jsx`, `SearchBar.jsx`, `styles.css` against the brief's literal code blocks — all match exactly.
- Confirmed no new dependencies: `package.json` untouched.
- Confirmed no router added: `App.jsx` has no `react-router` import; gating is a plain three-way `if`/return on `me`.
- Confirmed no CORS middleware touched (didn't need to — this task doesn't touch `app.py`).
- Confirmed `docs/superpowers/specs|plans|reviews` untouched (this task never had reason to touch them).
- Confirmed `web/dist` (the build artifact) is gitignored and did not end up in `git status`.
- `refreshSources`'s dependency array is `[me.is_admin]`, not `[me]` — correct per the brief's literal code, and also the tighter choice: the callback only reads the boolean, so keying on the whole `me` object would cause spurious re-creation if `me` were ever replaced by a new object with the same `is_admin` value.

## Concerns

None blocking. Two minor observations, neither a defect:

1. The brief's Step 8 instruction (`npm run lint`) is stale, as the task instructions already flagged; I ran only `npm run build`, per the correction.
2. `api.js`'s `fetchCatalog`/`subscribe`/`unsubscribe` exports are unused by anything in this task's UI — they're specified verbatim in the brief's Step 1 code block, presumably for Task 10 (subscriptions UI) to consume. Left them in as the brief requires; flagging only so a reviewer isn't surprised by unused-looking exports (they're not unused at build time in any way that breaks `vite build`, since they're just exports, not imports).

---

## Fix report: real outage was rendering as "signed out"

Coordinator review flagged that `web/src/App.jsx`'s boot effect swallowed any error from `fetchMe()` (a 500, a dropped connection, a malformed response — anything `fetchMe()` rethrows because it isn't a 401) into `setMe(null)`, which renders identically to an ordinary signed-out visit. This is the coordinator's own Step 5 code as originally briefed; I implemented it faithfully in the original pass, and the defect was in the brief, not introduced by me.

**Change**, in `web/src/App.jsx`:
- Added `bootError` state, set only in the boot effect's `.catch`, alongside `setMe(null)`.
- The `me === null` branch now renders `{bootError && <p className="error">Could not reach the server: {bootError}</p>}` above whichever of `Setup`/`Login` applies — banner on top, form still usable, since the failure may be transient.
- `signedOut()` now also clears `bootError`.

**Decision on clearing `bootError` in `signedOut()`: yes, cleared it.** Reasoning: a deliberate, successful sign-out means a `POST /api/auth/logout` request just round-tripped to the server, which proves the server is reachable right now. Leaving a stale `bootError` from an earlier failed boot check would then misreport a currently-healthy server as still down, right after the user's own action proved otherwise. Clearing it removes a banner whose cause (an earlier unreachable server) is no longer true.

**Verification:**
1. `cd web && npm run build` — clean (see output below). No lint step exists in this project, confirmed previously.
2. Browser re-verification, stronger than reasoning alone per the coordinator's suggestion: temporarily pointed `vite.config.js`'s proxy at a dead port (`127.0.0.1:9999`, nothing listening) so `/api/auth/me` would fail with something other than a 401, started `npm run dev` on the free default port 5173, and navigated Playwright to `http://localhost:5173/`. Confirmed the banner rendered:
   > Could not reach the server: Error: 502 Bad Gateway
   with the ordinary Login form still present and usable underneath it — exactly the intended behavior (Vite's proxy itself returns 502 when its upstream is unreachable; `fetchMe()` correctly treated this as a non-401 failure and rethrew, and `App` surfaced it distinctly from a plain signed-out state).
3. Cleanup: killed only the two processes I started for this check (npm wrapper PID 57617, its child Vite/Node PID 57631); confirmed via `lsof` that ports 8000 and 8001 (the pre-existing, unrelated `php` processes) were never touched. Reverted `vite.config.js` to its committed proxy target (`git diff` on that file is empty). Removed the `.playwright-mcp/` snapshot directory the browser tool wrote into the repo root. Re-ran `npm run build` clean after the revert.

### `npm run build` output (post-fix)

```
> web@0.0.0 build
> vite build

vite v8.2.2 building client environment for production...
transforming...
✓ 24 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.46 kB │ gzip:  0.29 kB
dist/assets/index-kSVfLk30.css    3.26 kB │ gzip:  1.07 kB
dist/assets/index-DGDhWrPp.js   200.25 kB │ gzip: 63.13 kB

✓ built in 57ms
```

### Files changed in this fix

- `/Users/dev2/Desktop/Testing/web/src/App.jsx` (only file changed)

### Scope discipline

Left untouched, as instructed: `startCollect`'s `{ok, ...}` shape, `Login.jsx`/`Setup.jsx`'s duplicated `busy`/`error`/`.auth` shell, and the absence of a runtime shape check on `me`.
