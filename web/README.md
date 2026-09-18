# reachstore web

React + Vite frontend for reachstore's reader UI.

In development, `vite.config.js` proxies `/api` to the FastAPI backend on
`http://127.0.0.1:8000`, so the browser stays same-origin — no CORS setup
needed.

## Run

```bash
npm install
npm run dev       # http://localhost:5173, backend must be running on :8000
npm run build     # production build to dist/
```

## End-to-end test

```bash
npm run test:e2e
```

This seeds the TEST database (`TEST_DATABASE_URL` from `../.env`) with deterministic data, then
starts both the API (pointed at that same test database) and the Vite dev server, and runs
`tests/smoke.spec.js` and `tests/auth.spec.js` against them with Playwright. Port 8000 must be
free — the API server is started fresh for the test run, never reused, so it does not silently
run against a database someone else pointed it at. It seeds and asserts an exact 12 items/1
source, so a fresh clone with `npm ci` behaves the same as any other checkout.

Most specs sign in first, using the admin account `seed_e2e.py` creates
(`e2e-admin@example.test`). Those credentials are duplicated in `seed_e2e.py`
and in the spec files themselves (`smoke.spec.js`, `auth.spec.js`) rather than
shared from one place, so all three must be kept in step by hand.

The setup spec is the exception: it creates its own account by consuming an
invite. `seed_e2e.py` issues that invite and writes the raw token to
`tests/.e2e-invite-token`, which is gitignored — a single-use credential, even
one for a throwaway database, does not belong in the repository. `auth.spec.js`
reads that file at load time, so run the suite through `npm run test:e2e`,
which always seeds first. Running `npx playwright test` directly against a
fresh clone fails the whole file with `ENOENT` on that path. Re-running is
safe: each seed deletes and reissues both the account and the invite, so a
consumed invite never breaks the next run.

`@playwright/test` needs a matching Chromium build downloaded to
`~/Library/Caches/ms-playwright`. If `npm run test:e2e` fails with
`browserType.launch: Executable doesn't exist at .../chromium_headless_shell-XXXX/...`, run:

```bash
npx playwright install chromium
```

The version in `package.json` is pinned (not a caret left to float) to whatever Chromium
revision happens to already be cached in this environment — see the comment at the top of
`playwright.config.js` before bumping it.
