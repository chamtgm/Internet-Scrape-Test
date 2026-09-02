# Task 10 report: update the living architecture doc

Commit: `18e45e7` "docs: update architecture.md now that the web layer is built"
Branch: `feat/web-ui-and-api` (already checked out, clean tree before starting)

## What changed, section by section

**Header / Status.** Date bumped to 2026-09-02. Status line rewritten from "designed and about to be built" to "shipped and running," merged with the Plan 1 clause since both are now true together.

**§2 layer diagram.** Dropped `(planned)` after `api/`, repadded the trailing comment so the `←` column stays aligned with the other three diagram lines (verified column 51 in all four lines both before and after).

**§3 invariants.**
- Clock-read invariant: was "Only `cli.py` — and, once built, `api/routes.py` — calls `datetime.now(UTC)`." Checked this against the actual code first — `routes.py` reads no clock; `collect_runner.py` does (`datetime.now(UTC)` at line 91, inside `run_collection`). Rewrote to name `collect_runner.py` specifically rather than `routes.py`, since the brief's own draft phrasing would have been wrong.
- Test-count invariant: "86 tests run in 1.5 seconds" → "116 tests run in under 2 seconds" (see verification output below; also updated the timing since the old value was stale too — 1.5s vs measured ~1.76-1.78s — leaving one wrong number while fixing the other would fail the same self-review this task requires).

**§6 Collection.** Added one paragraph after the SAVEPOINT explanation, before "Backoff and circuit breaker are derived": `collect_tier` commits after every source, not once at the end; two reasons (progress visibility, crash-durability of the circuit breaker's failure rows), and the commit itself sits inside the bulkhead — a commit failure rewrites the result to `failed` rather than leaving a stale success claim for rolled-back work. Verified against `src/reachstore/collect.py:143-193` (`collect_tier`), including the `try/except`+`session.rollback()`+`replace(...)` block.

**§7, retitled "Web layer" (dropped "(planned)").** Rewrote fully in present tense:
- Names all five endpoints and confirms `query.py` remains the only reader (cross-checked against `no SQL of its own` invariant via the grep below).
- Frontend description updated from "two-pane reader" (the old design-doc description) to what's actually in `web/src/`: feed pane, search, item detail, health strip — confirmed via `App.jsx` and `components/`.
- `api/deps.py` composition-root paragraph: module-level `lru_cache`d engine, `DEFAULT_USER_ID`, `assert_loopback` — all verified by reading `deps.py` and `app.py` directly.
- New paragraph on `POST /api/collect`: background task, `try_start()` claimed synchronously in the handler before scheduling, truthful 409. Verified against `routes.py` and `collect_runner.py`.
- New paragraph (the one the brief flagged as most important): `collecting` as the completion signal, and why `fetch_runs` can't serve that role — `collect_tier` commits only terminal statuses, so no second connection ever observes a `running` row. Verified the frontend actually behaves this way by grepping `web/src/App.jsx` for `collecting`/`poll` — it reads `r.collecting` from `/api/sources` and drives the poll loop off it (`if (!r.collecting) { ...stop... }`).

**§8 Development.** `86 tests` → `116 tests` in the pytest comment; kept the `~1.5s` → `~1.8s` update here too, for the same reason as §3. Added a short "Running the app takes both servers" paragraph with the two commands: `python -c "from reachstore.api.app import serve; serve()"` for the backend, `cd web && npm run dev` for the frontend, noting Vite's `/api` proxy keeps the browser same-origin (this is the actual comment in `web/vite.config.js`, not invented).

**§9 Decisions.** Added one entry: in-process flag over inferring completion from `fetch_runs`, with the reason (`collect_tier` commits only terminal statuses) and the single-worker caveat from `collect_runner.run_collection`'s docstring (multi-worker would need a Postgres advisory lock instead).

## What I left alone (and checked)

Re-read §1, §4, §5, and the untouched parts of §3/§9 for staleness. Nothing there references the web layer or is contradicted by it:
- §2's module table (models/store/query/adapters/collect/cli) doesn't gain an `api/` row — it never listed `cli.py`'s package-mates either (no `registry.py`, `config.py`, `db.py` rows), so this is consistent with how the table already scopes itself. Not one of the brief's 8 edits; left it.
- §3's opening sentence ("verified tree-wide by the Plan 1 final review") is a historical claim about that specific review event, not a claim that covers every file added since. Still literally true. Left it.
- §9's closing line ("8 tasks and 10 review rounds... in `docs/superpowers/reviews/`") — checked `docs/superpowers/reviews/` on disk: it only contains Plan 1's task-1..8 reports and the execution ledger. This branch's task/review artifacts live under `.superpowers/sdd/2026-09-02-web-ui-and-api/`, a different directory the sentence doesn't mention. The claim is still accurate as scoped. Left it.

Nothing else in the document was rewritten. No changelog section was added — §9 stays a list of standing decisions, and the new entry follows the existing "why, not what happened" format of its neighbors.

## Verification commands — raw output

```
$ .venv/bin/pytest -q 2>&1 | tail -10
tests/test_cli.py ......                                                 [ 51%]
tests/test_collect.py ...............                                    [ 64%]
tests/test_collect_commits.py ......                                     [ 68%]
tests/test_conftest_safety.py ...                                        [ 71%]
tests/test_query_isolation.py ..............                             [ 83%]
tests/test_query_search.py .........                                     [ 91%]
tests/test_schema.py ...                                                 [ 93%]
tests/test_store.py .......                                              [100%]

============================= 116 passed in 1.75s ==============================
```

Re-run for timing consistency: `116 passed in 1.76s` (second run). Both figures round to "under 2 seconds" as written.

**Disagreement with the task brief:** the brief's own Definition of Done estimated "~111 tests (86 from Plan 1, plus 25 added here)". The actual count is **116**, not 111. Trusting the command per instructions — the doc says 116.

```
$ grep -rn "datetime.now\|utcnow" src/
src/reachstore/cli.py:65:            created_at=datetime.now(UTC),
src/reachstore/cli.py:88:        now=datetime.now(UTC),
src/reachstore/api/collect_runner.py:91:                now=datetime.now(UTC),
```

Three hits total: two in `cli.py`, one in `src/reachstore/api/collect_runner.py`. None in `routes.py` — this is why the invariant in §3 now names `collect_runner.py` specifically rather than reusing the brief's draft wording ("`api/routes.py`"), which would have put the clock read in the wrong file.

```
$ grep -rn "select(" src/reachstore/api/ || echo "none — correct"
none — correct
```

```
$ cd web && npm run test:e2e 2>&1 | tail -5
  ✓  1 tests/smoke.spec.js:3:1 › the feed lists items and clicking one opens its full text (323ms)
  ✓  2 tests/smoke.spec.js:21:1 › searching narrows the list and clearing restores it (207ms)
  ✓  3 tests/smoke.spec.js:41:1 › the health strip expands to show per-source detail (147ms)

  3 passed (2.2s)
```

Port 8000 and 5173 were both free before running (`lsof -i :8000`/`:5173` returned nothing) — did not kill anything, no occupant to report.

## Additional source reads used to verify claims (not just the brief's numbers)

- `src/reachstore/api/deps.py` — `DEFAULT_USER_ID`, `lru_cache`d `get_engine`/`get_session_factory`, docstrings confirming the "second composition root" framing.
- `src/reachstore/api/app.py` — `assert_loopback`, `create_app`, `serve()` signature (`host="127.0.0.1", port=8000` defaults — used for the §8 run command).
- `src/reachstore/api/routes.py` — all five route handlers, confirmed endpoint paths/methods and the 202/409 status codes on `POST /api/collect`.
- `src/reachstore/api/collect_runner.py` — `is_running`, `try_start`, `run_collection`, and their docstrings, which independently corroborate the brief's claim about why `collecting` must be in-process.
- `src/reachstore/collect.py:143-193` — `collect_tier`'s per-source commit/rollback/`replace(...)` logic.
- `src/reachstore/query.py` — confirmed `selectinload(Item.source)` in `get_item`, `feed`, `search`, and `error_text`/`item_count` fields on `SourceStatus` (not written into the doc, since the brief's 8 edits don't ask for it and the existing §4 text about `source_health` was already accurate).
- `src/reachstore/models.py:100` — `source: Mapped["Source"] = relationship(lazy="raise")`.
- `web/README.md`, `web/vite.config.js` — confirmed the same-origin/proxy claim and the exact proxy target.
- `web/src/App.jsx`, `web/src/components/SearchBar.jsx` — confirmed the `collecting` poll-and-stop behavior actually exists in the frontend, not just in the backend contract.

## Self-review

- **Accuracy:** every claim added or edited was checked against the actual source, not copied from the brief or from the task-description message. One discrepancy found and corrected (see below).
- **Numbers:** test count (116) and timing (~1.75-1.78s) both come from two separate `pytest -q` runs; the clock-read grep and the SQL grep are both quoted verbatim above.
- **Restraint:** did not touch §1, §4, §5, the diagram's module table, or the two other §3/§9 sentences that don't need it. No changelog section added.
- **Completeness:** all 8 edits from the brief's Step 1 applied — verified against the list above and the diff.

## Where the brief's own text disagreed with the verified facts

1. **Test count:** brief's Definition of Done said "~111 tests"; actual is 116. Used 116.
2. **Clock-read location inside `api/`:** the task-description message (from the orchestrating agent, not the brief file) said the invariant should read "`cli.py` and the `api/` package, `collect_runner.py` included" — that phrasing is correct and is what I used. The brief file itself said "`api/routes.py`" — that's the one that's wrong; `routes.py` doesn't call `datetime.now`, `collect_runner.py` does. I followed the correct (task-description) version, confirmed against `grep -rn "datetime.now\|utcnow" src/`.

---

## Fix report (post-review)

Commit: `eec5ec0` "docs: add the No-CORS decision and fix a generous timing rounding (review fix)"

**Finding 1 — missing "No CORS anywhere" decision.** Added as a new entry in §9, placed between "Content-hash identity for web pages" and "An in-process flag over inferring completion from `fetch_runs`."

Chose §9 over folding it into §7's opening paragraph because it's a decision with a rationale and a consequence for future readers ("CORS middleware appearing here means a second origin was introduced"), which is exactly the shape every other §9 entry already has — bold one-line claim, then the reasoning. §7 is architecture description (what exists and why it's built that way); §9 is the standing list of choices an engineer would otherwise have to rediscover. This is squarely the latter. Placed it next to the other web-layer decision (the `collecting` flag) so the two web-layer entries sit adjacent, consistent with how the Plan-1 decisions above them are also grouped by subject (SQLite-vs-Postgres, `gh`-vs-API, counters, content-hash).

Text sourced from `web/vite.config.js`'s proxy comment and `web/README.md`'s "no CORS setup needed" line — not invented.

**Finding 2 — generous rounding in §8.** Changed `# 116 tests, ~1.8s, offline` to `# 116 tests, under 2s, offline`, matching §3's existing "under two seconds" phrasing. No new measurement taken, per the coordinator's note that the numbers are already settled.

Verified: `grep -i cors docs/architecture.md` now returns the new line (previously empty). Diff reviewed above the commit; nothing else touched.
