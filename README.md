# Internet-Scrape-Test

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