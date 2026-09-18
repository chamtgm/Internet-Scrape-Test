# Task 12: Documentation — Report

Commit: `ac86902` "docs: auth, subscriptions, and why the loopback guard stays" on branch `feat/auth-and-subscriptions`.

## What changed, file by file

### `src/reachstore/api/app.py` (Step 1)
Replaced `assert_loopback`'s docstring and the `RuntimeError` message verbatim per the brief: dropped "no authentication in this slice" in favor of naming the three specific gaps (non-`Secure` cookie, no CSRF tokens, no login rate limiting) and explaining why the loopback boundary still matters. No code path, condition, or control flow touched — only the docstring and the f-string literal changed.

### `src/reachstore/query.py` (Step 1b)
`source_health`'s docstring no longer claims subscriptions "has no write path yet" (Task 8 added `store.subscribe`/`store.unsubscribe`). Replaced with the real reason the function stays global: it's the operator's diagnostics view, and per-user narrowing belongs to `/api/catalog`. Function body is byte-for-byte unchanged.

### `web/tests/seed_e2e.py` (Step 3b)
Module docstring now states that the script also resets the seeded user's subscriptions to unsubscribed on every run, and why: `unsubscribe` is a soft delete (only clears `active`), so without the reset a second `npm run test:e2e` would fail the "nothing subscribed" precondition. Verified by running the script twice in a row: first run seeded 12 items (12 new); second run seeded 12 items (0 new), confirming the idempotency claim the docstring makes.

### `docs/architecture.md` (Step 2 + consistency sweep)
- **§3 Invariants** — added the three bullets from the brief verbatim (session-required, one-owning-module-per-table, shell-only account creation).
- **§4 Data model** — added the three paragraphs from the brief verbatim (`users.is_admin`, `sessions`, `invites`). Also fixed, for internal consistency with content I was adding in the same section:
  - "Seven tables." → "Nine tables." (there are 9 SQLAlchemy models now: the original 7 plus `sessions` and `invites`).
  - The `subscriptions` table row's "no write path yet" → "filters reads, never collection" (same stale claim as the query.py fix, same table).
- **§7 Web layer** — replaced the description of the request path: removed the stale "five endpoints" enumeration and "No authentication in this slice" claim from the intro paragraph; inserted the brief's three new paragraphs (session cookie / `auth.py` dependencies, frontend has no router, subscriptions filter reading not collection) verbatim; kept the still-accurate `api/deps.py` lru_cache-engine reasoning but removed the `DEFAULT_USER_ID` sentence and rewrote the `assert_loopback` justification to point at §9 instead of repeating the false "no authentication" claim.
- **§9 Decisions worth knowing** — added the five bullets from the brief verbatim (scrypt, non-`Secure` cookie, uniform login failure response, setup-link-as-fragment, soft-delete unsubscribe).
- **Extra fixes beyond the brief's literal four sections**, made because they were directly, obviously false and in the same living document:
  - §2's diagram and module table both said "7 tables" — bumped to "9 tables" to match §4.
  - §3's "116 tests run in under 2 seconds" and §8's `# 116 tests, under 2s, offline` comment — both now say "202 tests... a few seconds" (measured: 5.4s), matching the actual suite.
  - §8's uvicorn-bypass sentence repeated "no authentication in front of it" (lowercase, so it was also caught by the grep sweep) — reworded to name the cookie/CSRF/rate-limit gap, same as the other two fixes.
  - "Last updated 2026-09-02" → "Last updated 2026-09-19" (today), standard living-document hygiene for an edit that touches nearly every section.

### `README.md` (Step 3)
**Discrepancy found and worth flagging**: the brief says to "add a section after the setup instructions," but the root `README.md` has never had setup instructions — it has been a single line, `# Internet-Scrape-Test`, since the initial commit (`git log --oneline -- README.md` shows exactly one commit, `78d4207 Initial commit`; no prior task in this plan's report list mentions touching it). There is nothing to insert "after." I added the brief's `## Accounts` section verbatim directly under the title, and appended one extra line pointing to `docs/architecture.md` for the full system design, since a bare `## Accounts` section with no other context looked orphaned in an otherwise-empty file. I did not invent generic setup instructions (docker/venv/alembic) to backfill the missing section — that content already lives in `docs/architecture.md` §8, and inventing a second copy in the README felt like unrequested scope for a task whose brief lists three specific stale claims plus this operator-workflow addition.

Verified every command and flag mentioned (`invite --name --admin`, `set-password`, `revoke-sessions`, the `WEB_BASE_URL` fragment format, the Alembic `.env`-doesn't-get-read caveat) directly against `src/reachstore/cli.py` and `src/reachstore/config.py` before writing it — all accurate.

### `web/README.md` (Step 3)
Added the note that the e2e specs sign in first, using the admin account `seed_e2e.py` creates. **Second discrepancy**: the brief says credentials are "duplicated in both files" — I found they're actually duplicated in **three** places: `seed_e2e.py`, `smoke.spec.js`, and `auth.spec.js` (confirmed by `grep -rn "e2e-admin@example.test|e2e-password" web/tests/`). I wrote the note to name all three files rather than repeat the brief's "both," since "both" would have undercounted by one and been wrong the moment someone checked.

## Python suite

```
$ .venv/bin/pytest -q
202 passed in 5.43s
```
Zero warnings. Ran three times across the session (before any edits as a baseline, immediately after the three Python-file edits, and once more post-commit) — all three runs: 202 passed, clean.

`tests/test_api_app.py` specifically, immediately after the `app.py` edit:
```
tests/test_api_app.py::test_loopback_hosts_are_allowed PASSED
tests/test_api_app.py::test_non_loopback_host_is_refused PASSED
tests/test_api_app.py::test_non_loopback_host_allowed_with_explicit_override PASSED
3 passed in 0.14s
```
Unchanged from before the edit — `"REACHSTORE_ALLOW_NONLOCAL"` is still in the `RuntimeError` message, as required.

Note: the brief's Step 1b says to run `.venv/bin/pytest tests/test_query.py -v` — that file doesn't exist under that name (the actual files are `tests/test_query_isolation.py` and `tests/test_query_search.py`; `source_health` itself is exercised from `tests/test_collect.py` and `tests/test_cli.py`). I ran the full suite instead, which is a superset of what that command would have covered.

## Scoped consistency sweep (Step 5)

```
$ grep -rn "DEFAULT_USER_ID" src/ web/src/ docs/architecture.md
clean

$ grep -rn "no authentication" src/ docs/architecture.md
clean
```

Both clean, run twice (before commit and after, identical result). I additionally ran a case-insensitive pass over `docs/architecture.md` alone (`grep -in "no authentication"`) to catch the capitalized "No authentication in this slice" that opened §7 — the case-sensitive sweep as specified wouldn't have caught it, but it was directly false and inside one of the four named sections, so I fixed it as part of the §7 rewrite regardless.

```
$ git check-ignore .env && echo ".env is ignored"
.env
.env is ignored
```

```
$ git status --porcelain docs/superpowers/
(no output)
```
Nothing under `docs/superpowers/` was touched — confirmed both by `git status --porcelain` scoped to that path and by the fact I never opened any file under `docs/superpowers/specs/`, `docs/superpowers/plans/`, or `docs/superpowers/reviews/` for editing.

## Which suites I ran, and which I skipped

- **Ran**: the full Python suite (`pytest`, three times — 202/202 each time, zero warnings), `web/tests/seed_e2e.py` (twice, confirming idempotency including the new subscription-reset behavior), and `cd web && npm run build` (clean, 70ms, 25 modules).
- **Skipped**: `npm run test:e2e`. Per the brief's own warning, `web/playwright.config.js` starts the API on port 8000 with `reuseExistingServer: false`, and port 8000 is held by the user's long-running `php` process (PID 29601, confirmed still listening via `lsof -i :8000` at the end of this task — untouched). I did not attempt the temporary-port-8100 workaround Task 11 used, since this task changes only comments and markdown (no code paths that e2e tests exercise), and Task 11 already verified 12/12 e2e passing twice immediately before this task. Running the Python suite was the check that mattered here, and it's green.

## Confirmations

- No file under `docs/superpowers/` was modified. Confirmed via `git status --porcelain docs/superpowers/` (empty) and by never opening those paths.
- `tests/test_api_app.py` passes unchanged — same 3 tests, same names, same assertions; verified `"REACHSTORE_ALLOW_NONLOCAL"` still appears in the refusal message.
- Neither PHP dev-server process was touched: `lsof -i :8000 -i :8001` at the end of the session still shows `php 29601` and `php 53638` LISTENing. No `8100` override was ever introduced (`grep -rn "8100"` across the repo, excluding `node_modules`, returns nothing) — I never needed the port-override workaround since I skipped the e2e run.
- Final `git status --porcelain` shows exactly the six files the brief's `git add` list should have named: `README.md`, `docs/architecture.md`, `src/reachstore/api/app.py`, `src/reachstore/query.py`, `web/README.md`, `web/tests/seed_e2e.py`. Note: **the brief's own Step 6 `git add` command omits `src/reachstore/query.py` and `web/tests/seed_e2e.py`** — an oversight, since Steps 1b and 3b explicitly require editing those two files. I staged and committed all six.

## Self-review findings

**Discipline** — `git diff` on the three Python files shows changes confined to docstrings, one f-string literal, and (in `seed_e2e.py`) the module docstring's leading comment block. No `if`/`return`/assignment/import line was touched in any of the three. Confirmed by reading the full diff before committing.

**Completeness** — `app.py` docstring and `RuntimeError` both fixed; `query.py` fixed; `seed_e2e.py` fixed; `docs/architecture.md` §3, §4, §7, §9 all edited per the brief's literal blocks; both READMEs updated.

**Accuracy** — every new sentence was checked against the actual current code before writing it:
- §7's auth-dependency description checked against `src/reachstore/api/auth.py` (`get_current_user` → 401, `require_admin` → 403).
- §7's frontend-routing description checked against `web/src/App.jsx` (three states: `undefined`/`null`/object; `#setup=` fragment; renders `Login`/`Setup`/`Store`).
- §9's `ON CONFLICT DO UPDATE` claim checked against `src/reachstore/store.py`'s `subscribe`/`unsubscribe` functions.
- The root README's CLI commands and flags checked against `src/reachstore/cli.py` (`invite --name --admin`, `set-password`, `revoke-sessions`, all present with those exact names/options) and the `[project.scripts]` / `python -m reachstore.cli` entry point.
- The endpoint list in §7's intro paragraph checked against `src/reachstore/api/routes.py`'s route decorators (12 endpoints across sources/feed/search/catalog/subscriptions/items/collect/auth) — rewritten to describe them by category rather than enumerate an exact count, so it won't go stale again the next time an endpoint is added.
- The credentials-duplication note in `web/README.md` checked by grepping `web/tests/` directly (three files, not the brief's "both").

**Formatting note**: the brief's given blocks for §3 and §9 use `-` bulleted lists, but every other entry in those two sections is a bare bold-lead paragraph with no bullet. I kept the bullets as literally given rather than reformatting to match — the parent task's instructions call the brief's blocks "the complete replacement prose... your requirements," and reformatting would be a silent deviation from that. The result is a minor, cosmetic style mix (bulleted new content next to un-bulleted old content) in those two sections. Flagging it rather than silently picking one convention.

## Concerns

1. **Root `README.md` had no setup-instructions section to add "after"** (see above) — I added `## Accounts` at the top instead and flagged this rather than inventing setup docs that would duplicate `docs/architecture.md` §8.
2. **Credential duplication is three-way, not two ("both files")** — corrected in the `web/README.md` note to name all three files.
3. **Brief's Step 6 `git add` omits `query.py` and `seed_e2e.py`** — staged and committed anyway, since Steps 1b/3b require editing them.
4. **Brief's Step 1b test command (`tests/test_query.py`) doesn't exist** — ran the full suite instead, which covers it.
5. None of these change behavior or require a decision from the requester before merging; all are documentation-accuracy judgment calls made in favor of what's actually true in the repo, and are called out above for visibility.

---

## Fix report — review round 2

Commit: `2d25703` "docs: fix remaining stale write-path claim and table-count mismatch" (follows `ac86902`).

### Important 1 — `src/reachstore/query.py`, second occurrence of the stale write-path claim

Read the entire `source_health` docstring top to bottom before touching anything, and grepped `write path|no authentication|DEFAULT_USER_ID` against the file to confirm coverage. Found exactly one remaining occurrence, in the paragraph explaining why the function used to take an ignored `user_id` parameter:

> "...so exposing this to anything but an operator requires adding real per-user scoping first, once subscriptions have a write path."

This directly contradicted the paragraph immediately above it (already fixed in round 1 to say per-user narrowing exists today via `/api/catalog`). Replaced with:

> "...which is why per-user scoping now lives in `/api/catalog` rather than here."

Confirmed via `grep -n "write path"` afterward that no instance remains anywhere in `query.py`. Function body untouched — `source_health` still takes no `user_id` and stays global, as required.

### Important 2 — `docs/architecture.md` §4, "Nine tables." over a seven-row table

Chose the **reword-the-count-sentence** option over adding `sessions`/`invites` as table rows, because the brief's own template put those two tables in prose paragraphs (with fuller explanations — SHA-256-only storage, `consumed_at` for single-use) immediately below the table, and duplicating them as terse table rows too would either repeat the same information twice in one section or force the row entries to be strictly worse (less explanation) than the prose already gives them. Reducing to one true sentence was the smaller, more honest fix:

> "Nine tables." → "Seven content tables, plus the two authentication tables described below."

This also resolved the ambiguity cleanly: §2's diagram and module table ("models.py ← 9 tables") describe the total across `models.py`, and 7 + 2 = 9, so the two sections are now consistent with each other rather than contradicting.

### Suite and sweep, post-fix

```
$ .venv/bin/pytest -q
202 passed in 5.43s
```
Zero warnings.

```
$ grep -rn "DEFAULT_USER_ID" src/ web/src/ docs/architecture.md
clean

$ grep -rni "no authentication\|no write path" src/ web/src/ docs/architecture.md
clean
```

Both clean. The case-insensitive, write-path-inclusive sweep is the one that would have caught Important 1 had it been run in round 1 — confirmed it's clean now.

### Confirmation

- Read the whole `source_health` docstring (not just the two flagged lines) before editing, to rule out a third occurrence. There was none.
- `git diff` on both files in this round touches only docstring/markdown prose — no logic, no test, no import changed.
- Did not touch the two items the coordinator is carrying to final review (§3/§9 bullet-vs-paragraph formatting; `README.md`'s Accounts section not mentioning the loopback constraint or explaining `set-password`/`revoke-sessions`).
- Did not run the e2e suite; port 8000 still held by the user's `php` process (PID 29601), untouched.

---

## Fix report — review round 3

Commit: `03258dc` "docs: stop labelling the data-model table group, just count it" (follows `2d25703`).

### Important — `docs/architecture.md:81`, "content tables" mislabelled two of the seven

Round 2's fix ("Seven content tables, plus the two authentication tables described below.") solved the count mismatch but introduced a classification the document itself contradicts nine lines above: §3 names `users` as one of "the three auth tables," while §4's new sentence called the table containing `users` a "content" table. `collectors` fits neither label.

Per the coordinator's guidance, did not hunt for a better collective noun — there isn't one that covers all seven rows without contradicting §3's ownership taxonomy (which only classifies 7 of the 9 tables and never mentions `collectors` or `subscriptions`). Replaced with a sentence that counts and points, and asserts no category:

> "Nine tables. The seven below, plus `sessions` and `invites`, which are described after the table."

### Scan for other characterizing sentences in §4

Checked every sentence in §4 for group-level characterization, not just line 81:
- The "Sharing model: content is shared, interest is per-user" sentence talks about `items.owner_user_id` specifically, not the table group as a whole — not a label of the section's seven rows.
- The three added prose paragraphs (`users.is_admin`, `sessions`, `invites`) each describe one table by name, no collective label.

No other characterizing sentence found.

### Both requested greps, post-fix

```
$ grep -rni "no authentication\|no write path" src/ web/src/ docs/architecture.md
clean
```

```
$ grep -n "content table\|auth table\|authentication table" docs/architecture.md
71:  `query.py` for reads. The three auth tables (`users`, `sessions`, `invites`)
```

Only one hit, and it's §3's original "one owning module" bullet from round 1 (verbatim brief text) — an accurate, different classification (which module owns writes/reads for `users`/`sessions`/`invites`), not a description of the §4 table. With line 81 now asserting no category, this is the only place in the document that classifies any table, and there is nothing left for it to disagree with.

### Suite, post-fix

```
$ .venv/bin/pytest -q
202 passed in 5.42s
```
Zero warnings. Did not run the e2e suite — port 8000 still held by the user's `php` process (PID 29601), untouched, and this was a one-sentence prose change.
