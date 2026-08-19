# Task 1 Report: Project scaffold, schema, and migrations

## Status: DONE

## What I implemented

Followed the brief step by step (Steps 2–17; Step 1 skipped per environment resolution #1, Steps 6/7 adapted per resolutions #3/#4). All file contents match the brief verbatim except one additive fix noted below.

Files created:
- `pyproject.toml` — package metadata, deps, pytest config (verbatim from brief)
- `docker-compose.dev.yml` — Postgres 16 on host port 5433 (verbatim)
- `.env.example` — DATABASE_URL / TEST_DATABASE_URL / RAW_DIR (verbatim)
- `alembic.ini` — Alembic config (verbatim + one additive line, see Deviations)
- `migrations/env.py` — Alembic runtime wiring, reads `ALEMBIC_DATABASE_URL` or `DATABASE_URL` (verbatim)
- `migrations/versions/0001_initial.py` — full 7-table schema, GIN index on `content_tsv`, two supporting indexes, downgrade path (verbatim)
- `src/reachstore/__init__.py` — empty package marker
- `src/reachstore/config.py` — `Settings` (pydantic-settings) + `get_settings()` (verbatim)
- `src/reachstore/db.py` — `make_engine`, `make_session_factory` (verbatim)
- `src/reachstore/models.py` — `Base` + `User`, `Collector`, `Source`, `Subscription`, `Item` (with `Computed` tsvector column), `FetchRun`, `ItemTag` (verbatim)
- `tests/conftest.py` — `test_database_url`, `engine` (drops/recreates schema, runs Alembic to head), `session` (savepoint-rollback isolation), `raw_dir`, `fixtures_dir` fixtures (verbatim)
- `tests/test_schema.py` — 3 tests: all tables exist, `content_tsv` is a generated column (`is_generated = 'ALWAYS'`), GIN index exists (verbatim)

Files modified:
- `.gitignore` — appended the brief's 11 lines after the two pre-existing lines (`.DS_Store`, `.superpowers/`); both survived.

## Environment resolutions applied

1. Skipped `git init` / `git branch -M main` entirely — repo already existed on `feat/core-store-tier1`.
2. Appended to existing `.gitignore` rather than overwriting.
3. Used `uv venv --python 3.12 .venv` + `uv pip install --python .venv/bin/python -e ".[dev]"` instead of `python3 -m venv` (system Python was 3.9.6). Package installed cleanly; SQLAlchemy 2.0.52, Alembic 1.19.1, pydantic-settings 2.15.0, psycopg 3.3.4 resolved.
4. Started Postgres via `docker compose -f docker-compose.dev.yml up -d`, polled `pg_isready -U reachstore` until "accepting connections" (came up in ~1 poll), then ran `CREATE DATABASE reachstore_test OWNER reachstore;` — succeeded (`CREATE DATABASE`, first attempt, no pre-existing DB).

## Testing

### Schema tests (Step 16 target)

```
$ .venv/bin/pytest tests/test_schema.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- /Users/dev2/Desktop/Testing/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/dev2/Desktop/Testing
configfile: pyproject.toml
plugins: cov-7.1.0, anyio-4.14.2
collecting ... collected 3 items

tests/test_schema.py::test_all_tables_exist PASSED                       [ 33%]
tests/test_schema.py::test_items_has_generated_tsvector_column PASSED    [ 66%]
tests/test_schema.py::test_tsvector_index_exists PASSED                  [100%]

============================== 3 passed in 0.11s ===============================
```

### Full suite (run twice to confirm the drop-schema/upgrade-to-head fixture logic is idempotent across sessions)

```
$ .venv/bin/pytest -v
============================= test session starts ==============================
...
collecting ... collected 3 items

tests/test_schema.py::test_all_tables_exist PASSED                       [ 33%]
tests/test_schema.py::test_items_has_generated_tsvector_column PASSED    [ 66%]
tests/test_schema.py::test_tsvector_index_exists PASSED                  [100%]

============================== 3 passed in 0.09s ===============================
```
(second run: `3 passed in 0.09s`, identical, pristine — no warnings either run)

### Additional manual verification (not part of the brief's test suite, done for confidence)

- Imported `reachstore.config`, `reachstore.db`, `reachstore.models` directly; confirmed `Settings` loads `database_url`, `test_database_url`, `raw_dir` from `.env`; confirmed `Base.metadata.tables` contains exactly the 7 expected table names.
- Ran `alembic upgrade head` / `alembic downgrade base` / `alembic upgrade head` against the primary dev database (`reachstore`, not just the test DB) to exercise the migration's `downgrade()` path, which the pytest suite never calls. All three completed without error; `\dt` afterward showed all 7 tables + `alembic_version` present.
- Confirmed `git add -A` staged exactly the 13 files the brief's file list implies (plus `.gitignore`) — no `.env`, `__pycache__`, `.pytest_cache`, or `*.egg-info` leaked into the stage, confirming the `.gitignore` additions work.

## Files changed

- `/Users/dev2/Desktop/Testing/.gitignore` (modified — appended)
- `/Users/dev2/Desktop/Testing/pyproject.toml` (new)
- `/Users/dev2/Desktop/Testing/docker-compose.dev.yml` (new)
- `/Users/dev2/Desktop/Testing/.env.example` (new)
- `/Users/dev2/Desktop/Testing/alembic.ini` (new)
- `/Users/dev2/Desktop/Testing/migrations/env.py` (new)
- `/Users/dev2/Desktop/Testing/migrations/versions/0001_initial.py` (new)
- `/Users/dev2/Desktop/Testing/src/reachstore/__init__.py` (new)
- `/Users/dev2/Desktop/Testing/src/reachstore/config.py` (new)
- `/Users/dev2/Desktop/Testing/src/reachstore/db.py` (new)
- `/Users/dev2/Desktop/Testing/src/reachstore/models.py` (new)
- `/Users/dev2/Desktop/Testing/tests/conftest.py` (new)
- `/Users/dev2/Desktop/Testing/tests/test_schema.py` (new)

Not tracked by git (correctly ignored): `.env` (created via `cp .env.example .env` per Step 6), `__pycache__/`, `.pytest_cache/`, `src/reachstore.egg-info/`.

## Self-review findings

- **Completeness:** every file the brief lists under "Files: Create" and "Test" exists with the exact specified content, except the one additive line noted below. All interface names (`Settings`, `get_settings`, `make_engine`, `make_session_factory`, `Base`, the 7 models, the `engine`/`session`/`raw_dir`/`fixtures_dir` fixtures) match the brief's required signatures exactly — verified by direct import and by the fixtures being consumed successfully in `test_schema.py`.
- **Quality:** no naming deviations. `models.py` matches the brief's `Computed(...)` tsvector approach for `Item.content_tsv`, confirmed generated as `ALWAYS` by the passing test.
- **Discipline:** built nothing beyond the brief's 13 files. Did not add `cli.py`, `store.py`, `query.py`, or adapters — those are later tasks. Did not add extra tests beyond the brief's `test_schema.py`.
- **Testing:** output is pristine on both runs — 3 passed, 0 warnings, 0 stray noise.

## Deviation from the brief

One line added to `alembic.ini` beyond the brief's verbatim content: `path_separator = os` under `[alembic]`.

**Why:** The brief's `pyproject.toml` pins `alembic>=1.13`; `uv` resolved `alembic==1.19.1` (newest compatible). Running `pytest tests/test_schema.py -v` with the brief's exact `alembic.ini` produced a passing but noisy result:
```
DeprecationWarning: No path_separator found in configuration; falling back to legacy
splitting on spaces, commas, and colons for prepend_sys_path. Consider adding
path_separator=os to Alembic config.
```
The task instructions' self-review checklist explicitly requires pristine test output ("no stray warnings or noise... a clean run matters"). Adding `path_separator = os` is Alembic's own documented remedy, is purely additive configuration, does not touch any table/column/constraint name or test code, and eliminates the warning with no behavior change (verified: migrations still apply correctly, all 3 tests still pass, `alembic upgrade/downgrade/upgrade` cycle still works on the dev DB). No other deviations.

## Concerns

None. All target interfaces are in place for Tasks 2–8 to import: `reachstore.config.{Settings, get_settings}`, `reachstore.db.{make_engine, make_session_factory}`, `reachstore.models.{Base, User, Collector, Source, Subscription, Item, FetchRun, ItemTag}`, and pytest fixtures `engine`, `session`, `raw_dir`, `fixtures_dir`.

---

## Fix report: review finding — missing index metadata in models.py

### Finding addressed

Reviewer found `src/reachstore/models.py` declared no `Index` metadata for the three indexes `migrations/versions/0001_initial.py` creates via `op.execute` (`items_content_tsv_idx`, `items_source_published_idx`, `fetch_runs_source_started_idx`). Only the `UniqueConstraint`s were present, leaving `Base.metadata` an incomplete description of the schema — a future `alembic revision --autogenerate` would have proposed dropping all three, including the GIN index full-text search depends on.

### What I changed

`src/reachstore/models.py` — additive only, no migration or column changes:

1. Added `Index` and `text` to the existing `from sqlalchemy import (...)` block.
2. `Item.__table_args__` — added alongside the existing `UniqueConstraint`:
   - `Index("items_content_tsv_idx", "content_tsv", postgresql_using="gin")`
   - `Index("items_source_published_idx", "source_id", text("published_at DESC"))`
3. `FetchRun` — added a new `__table_args__` (previously had none):
   - `Index("fetch_runs_source_started_idx", "source_id", text("started_at DESC"))`

All three index names match the migration exactly. No table, column, type, nullability, FK, or unique-constraint definition was touched.

### Covering tests run

**1. Schema tests, exact command from the review request:**

```
$ .venv/bin/pytest tests/test_schema.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- /Users/dev2/Desktop/Testing/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/dev2/Desktop/Testing
configfile: pyproject.toml
plugins: cov-7.1.0, anyio-4.14.2
collecting ... collected 3 items

tests/test_schema.py::test_all_tables_exist PASSED                       [ 33%]
tests/test_schema.py::test_items_has_generated_tsvector_column PASSED    [ 66%]
tests/test_schema.py::test_tsvector_index_exists PASSED                  [100%]

============================== 3 passed in 0.24s ===============================
```

All 3 still pass, output pristine (no warnings).

**2. Full suite, run again after the fix for good measure:**

```
$ .venv/bin/pytest -v
============================= test session starts ==============================
...
collecting ... collected 3 items

tests/test_schema.py::test_all_tables_exist PASSED                       [ 33%]
tests/test_schema.py::test_items_has_generated_tsvector_column PASSED    [ 66%]
tests/test_schema.py::test_tsvector_index_exists PASSED                  [100%]

============================== 3 passed in 0.11s ===============================
```

**3. ORM metadata vs. live database comparison, exact command from the review request:**

```
$ .venv/bin/python -c "
from sqlalchemy import inspect
from reachstore.db import make_engine
from reachstore.models import Base
from reachstore.config import get_settings
eng = make_engine(get_settings().test_database_url)
insp = inspect(eng)
for t in ('items', 'fetch_runs'):
    live = {i['name'] for i in insp.get_indexes(t)}
    orm = {i.name for i in Base.metadata.tables[t].indexes}
    print(t, 'live:', sorted(live), 'orm:', sorted(orm), 'missing_from_orm:', sorted(live - orm))
"
items live: ['items_content_tsv_idx', 'items_source_published_idx', 'uq_items_source_external'] orm: ['items_content_tsv_idx', 'items_source_published_idx'] missing_from_orm: ['uq_items_source_external']
fetch_runs live: ['fetch_runs_source_started_idx'] orm: ['fetch_runs_source_started_idx'] missing_from_orm: []
```

`missing_from_orm` for `fetch_runs` is empty. For `items` the only entry is `uq_items_source_external`, which is the backing index for the `UniqueConstraint` (not one of the three named indexes) — per the review request this is expected and not a failure. All three required named indexes (`items_content_tsv_idx`, `items_source_published_idx`, `fetch_runs_source_started_idx`) are present in both `live` and `orm`.

**4. Extra verification — confirmed the GIN index type is actually preserved (not silently downgraded to btree):**

```
$ docker compose -f docker-compose.dev.yml exec postgres psql -U reachstore -d reachstore_test -c "\di+ items_content_tsv_idx"
                                                List of relations
 Schema |         Name          | Type  |   Owner    | Table | Persistence | Access method | Size  | Description
--------+-----------------------+-------+------------+-------+-------------+---------------+-------+-------------
 public | items_content_tsv_idx | index | reachstore | items | permanent   | gin           | 16 kB |
(1 row)
```

Access method is `gin`, matching the ORM declaration's `postgresql_using="gin"`.

### Files changed

- `/Users/dev2/Desktop/Testing/src/reachstore/models.py` (modified — additive `Index` declarations only)

### Commit

`10a1f76` — fix: declare index metadata on models.py to match migration

### Concerns

None. The fix is additive-only as instructed: no migration file, column definition, or test was changed.
