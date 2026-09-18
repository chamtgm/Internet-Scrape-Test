# Internet-Scrape-Test

## Security posture — read this before inviting anyone

This service is **loopback-only**. It binds `127.0.0.1` and refuses any other
interface unless `REACHSTORE_ALLOW_NONLOCAL=1` is set. That guard is load-bearing,
not a formality: the session cookie deliberately does not set `Secure` (there is
no HTTPS on localhost, and setting it would stop the cookie being sent at all),
there are no CSRF tokens, and there is no login rate limiting. On loopback none of
those matter; on any other interface all three do, and the cookie would travel in
cleartext. **Exposing this beyond localhost means building HTTPS, CSRF tokens, and
login rate limiting first — not flipping the override.**

## Accounts

There is no signup page. An account starts with a shell command:

```bash
.venv/bin/python -m reachstore.cli invite someone@example.com --name "Someone"
.venv/bin/python -m reachstore.cli invite boss@example.com --name "Boss" --admin
```

Each prints a one-time setup link, valid 7 days, that the person opens to
choose a password. `WEB_BASE_URL` in `.env` controls the host and port the
link is built against — 5173 for the Vite dev server, 8000 when FastAPI
serves the built frontend.

Two other commands:

```bash
.venv/bin/python -m reachstore.cli set-password someone@example.com
.venv/bin/python -m reachstore.cli revoke-sessions someone@example.com
```

Use `set-password` when someone forgets theirs, and `revoke-sessions` when someone
leaves. **After any password reset prompted by a compromise, run both:**
`set-password` writes a new hash but does not end existing sessions, so every
browser already signed in as that account stays signed in for up to 30 days. The
two are deliberately separate — an ordinary forgotten password should not log the
person out of their other browsers.

Email addresses are case-insensitive: `invite` stores them lowercased, and login
normalises the same way, so the case you type here is not the case they have to
remember.

Note on migrations: Alembic does not read `.env` — `migrations/env.py` takes
the URL from the real environment. Export it first:

```bash
export $(grep -E '^DATABASE_URL=' .env | xargs)
.venv/bin/alembic upgrade head
```

The CLI and the API do not need this; they load `.env` through pydantic
`Settings`.

`--admin` grants the operator surface: the health strip, and the Collect
button. Everyone else can read, search, and subscribe.

See `docs/architecture.md` for the full system design.