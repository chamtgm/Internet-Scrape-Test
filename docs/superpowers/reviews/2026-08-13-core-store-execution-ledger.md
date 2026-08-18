# SDD ledger — plan: /Users/dev2/Desktop/Testing/docs/superpowers/plans/2026-08-13-core-store-and-tier1-collection.md

Base commit (branch start): 773ad51
Branch: feat/core-store-tier1
Runtime: colima + docker compose; Python 3.12 via uv (system python3 is 3.9.6)

Task 1: review returned 1 Important (plan-mandated: models.py declares no Index for the 3 indexes the migration creates) + 3 Minor.
Task 1: minor (deferred): conftest.py:22,35 fixtures lack return-type annotations (plan-mandated, verbatim from brief Step 14)
Task 1: minor (deferred): models.py uses client-side default=, migration uses server_default= for the same columns; deliberate dual-layer defaulting, undocumented
Task 1: minor (deferred): test_schema.py asserts content_tsv is generated but never that the tsvector expression computes correctly on a real insert
Task 1: controller ruling on reviewer's ⚠️ "raw SQL outside store.py/query.py" — NOT a violation. The constraint scopes to application modules; Alembic migrations and the conftest schema-reset are schema plumbing, not read/write paths. Constraint intent is that adapters/collect/cli never write SQL. No action.
Task 1: plan-mandated finding put to human — ruling: reviewer's finding governs; add Index declarations to models.py (deviation from plan Step 10, additive only). Fix round 1 dispatched.
Task 1: fix round 1/5 (1 addressed, 0 open; commits 61e4bc9..10a1f76)
Task 1: complete (commits 773ad51..10a1f76, review clean)
Task 2: review ✅ spec compliant, quality Approved. 1 Important (plan-mandated: raw payload filename collision) + 4 Minor.
Task 2: minor (deferred): _write_raw's `raw: dict` param unparameterized vs NormalizedItem.raw: dict[str, Any]
Task 2: minor (deferred): one INSERT round-trip per item rather than a batched statement (plan-mandated, fine at Tier-1 volumes)
Task 2: minor (deferred): no explicit test for duplicate external_id within one batch, nor for an item with empty raw dict (both traced correct, untested)
Task 2: fix round 1/5 (1 addressed, 0 open; commits e4fb563..c5b097c) — raw file now keyed on content_hash(external_id), written only on successful insert; 2 regression tests added (7/7, suite 10/10)
Task 2: complete (commits 10a1f76..c5b097c, review clean)
Task 3: implementer DONE_WITH_CONCERNS — plan Step 4's feed ordering desc(Item.published_at.nulls_last()) is invalid Postgres (compiles to "NULLS LAST DESC"); corrected to Item.published_at.desc().nulls_last(). Controller ruling: not a which-governs question — the plan's form is non-executable, so there is no viable alternative. Same intent, no change to the isolation predicate. Plan amended.
Task 3: review ✅ spec compliant, quality Approved. 1 Important (plan-mandated: ranking test confounded by term frequency) + 4 Minor.
Task 3: minor (deferred): kinds=[] silently treated as kinds=None (falsy) — undocumented, untested
Task 3: minor (deferred): empty q and limit=0 untested edge cases
Task 3: fix round 1/5 (1 addressed, 0 open; commits 8aa462a..eaa632d) — ranking test replaced with a field-weighting-isolating fixture (weighted 0.608 vs 0.243; unweighted exact tie), plus before_id and kinds+subscribed_only coverage (11 focused, suite 21/21)
Task 3: complete (commits c5b097c..eaa632d, review clean)
Task 4: review ✅ spec compliant, quality Approved. 2 Important (both plan-mandated: mid-file imports in base.py; AdapterError raised for legitimately-empty valid feeds) + 4 Minor.
Task 4: verified by reviewer — feedparser normalizes published_parsed to UTC before returning, so _to_datetime's tzinfo=UTC attach is correct for non-zero-offset feeds. Undated entries correctly survive the `since` filter. Both behaviors untested.
Task 4: minor (deferred): RssAdapter.__init__ lacks -> None annotation (plan-mandated)
Task 4: minor (deferred): FakeHttp.calls tracked but never asserted — no test confirms fetch calls http.get with the right identifier/timeout
Task 4: fix round 1/5 (2 addressed, 0 open; commits 3c2352c..f4ea3af) — imports moved to top of base.py; empty-but-valid feeds now return [] via feed.bozo check (garbage bozo=1, empty-valid bozo=False, both verified); 3 tests added (9 focused, suite 30/30)
Task 4: complete (commits eaa632d..f4ea3af, review clean)
Task 5: review ❌ Needs fixes. 2 Important (both plan-mandated: identifier validation accepts "/repo" and "owner/"; no isinstance(list) guard so a non-list JSON payload raises AttributeError instead of AdapterError) + 3 Minor.
Task 5: verified by reviewer — external_id is str(release["id"]) not tag_name; gh args exact; undated releases kept (consistent with rss.py); Z-to-+00:00 replace preserves non-Z offsets; protocol conformance exact.
Task 5: minor (deferred): a release missing the `id` key raises KeyError not AdapterError
Task 5: minor (deferred): test_maps_release_fields asserts nothing about the `raw` field
Task 5: NOTE FOR TASK 7 — collect_source must catch broad Exception, not only AdapterError. Adapters can leak KeyError/AttributeError on malformed upstream payloads; bulkhead isolation depends on the orchestrator being the backstop.
CONTROLLER NOTE (user instruction, 2026-08-18): "proceed until you finish everything" — standing authorization to adjudicate plan-mandated findings myself instead of asking per-finding. Rulings still recorded here. Default: fix real defects with contained fixes; defer cosmetic ones to the final review.
Task 5: fix round 1/5 (2 addressed, 0 open; commits 2d58b11..0ada09b) — empty owner/repo segments now rejected (count("/") clause preserved, so "a/b/c" still rejected); isinstance(list) guard added so non-list JSON raises AdapterError; 3 tests added + 1 strengthened with runner.calls == [] (9 focused, suite 39/39)
Task 5: complete (commits f4ea3af..0ada09b, review clean)
Task 6: review ❌ Needs fixes. 1 Important (plan-mandated: registry test asserts key set + tier but not dependency identity, so a swapped http/runner would pass), 2 Minor.
Task 6: verified by reviewer — external_id hashes content only (never identifier/timestamp); registry keys derive from adapter.kind so they cannot drift; empty/whitespace Jina body correctly raises AdapterError (defensible here, unlike RSS: a web_page fetch always re-emits one item, so there is no legitimate steady-state-empty case).
Task 6: minor (deferred): no URL-shape validation before JINA_PREFIX concatenation; empty identifier yields a syntactically valid URL and could produce an item with url=""
Task 6: minor (deferred): test_unchanged_page_produces_identical_external_id proves determinism, not content-purity; purity is actually established by test_external_id_is_content_hash
Task 6: CONTROLLER RULING — reviewer's ⚠️ escalated to an Important fix in this round. HttpxFetcher.get (base.py, Task 4) calls response.raise_for_status() without wrapping, so ordinary HTTP failures (404/429/timeout) leak httpx exceptions from every http-based adapter in production. SubprocessRunner already wraps non-zero exits in AdapterError; HttpxFetcher must be symmetric. Authorizing a Task 4 file edit — the "adapters only raise AdapterError" contract that Task 7 depends on does not currently hold end-to-end.
Task 6: fix round 1/5 (2 addressed, 0 open; commits 410c9f6..9ef08c2) — registry test now asserts dependency identity with `is`; HttpxFetcher.get wraps httpx.HTTPError as AdapterError with `from exc`; 2 new tests in test_adapter_base.py via monkeypatch (suite 47/47, rss 9/9 unaffected)
Task 6: complete (commits 0ada09b..9ef08c2, review clean)
Task 7: implementer DONE_WITH_CONCERNS — brief Step 3's collect.py imports sqlalchemy and runs raw select(), contradicting the Global Constraint "All SQL lives in store.py and query.py". CONTROLLER RULING: the constraint governs; a Global Constraint is a project-wide invariant, the step's reference code is one sketch of satisfying it. Relocation of the three queries into query.py (recent_fetch_statuses, last_run_started_at, sources_by_tier) stands. `Session` imported in collect.py for type hints only is acceptable. NOTE: this contradiction should have been caught in my pre-flight scan; it was not.
Task 7: review ❌ Needs fixes. 1 CRITICAL (collect_source can still raise: a DB-level error inside upsert_items aborts the transaction, and the except-block's own session.flush() then raises PendingRollbackError uncaught — defeating the bulkhead) + 3 Minor.
Task 7: verified by reviewer — no wall-clock reads; recent_fetch_statuses orders DESC and the loop breaks on first success (streak counted correctly); should_attempt uses >= at the boundary and the exact instant IS tested; force bypasses both gates (should_attempt never called); MAX_BACKOFF clamp correct though unreachable under FAILURE_LIMIT=5; relocated queries preserve filters/ordering/limits exactly (scalar_one -> scalar_one_or_none is strictly safer); no import cycle; both controller rulings satisfied with a genuine bulkhead-proving test.
Task 7: minor (deferred): consecutive_failures is capped at FAILURE_LIMIT by construction — a source that failed 40 times reports 5. Fine for breaker logic; matters only if source_health is surfaced verbatim in an operator UI (relevant to Plan 2/4).
Task 7: fix round 1/5 (1 Critical addressed, 0 open; commits 911ea8f..3c14dd2) — pre-fix defect reproduced (InFailedSqlTransaction escaping collect.py:96); risky work wrapped in session.begin_nested(); run row still flushed before the savepoint so it survives rollback; failure-recording flush wrapped in its own guard with error_text computed beforehand so the returned CollectResult always reports the failure; docstring narrowed to match; both minors folded in (desc(FetchRun.id) tie-breaker, cycle-explaining comment). Suite 60/60.
Task 7: residual (disclosed, not a defect): a double DB failure — savepoint recovery succeeds but the recording flush also fails — could leave the outer transaction aborted for the next source's initial unguarded flush. Requires two independent DB failures in sequence; documented in the docstring rather than silently decided.
Task 7: complete (commits 9ef08c2..3c14dd2, review clean)
Task 8: review ✅ spec compliant, quality Approved. 1 Important (plan-mandated: `collect` exits 0 even when every source fails) + 3 Minor.
Task 8: verified by reviewer — all four commands' kwargs match callee signatures exactly (incl. keyword-only params); --user-id is typer.Option on both search and health; exactly two datetime.now(UTC) calls, both in cli.py, zero utcnow anywhere in src/; no query construction in cli.py; _session resolved at call time so monkeypatch intercepts; commits present in add-source and collect, correctly absent in read-only commands.
Task 8: CONTROLLER RULING on exit codes — the plan never considered them; this is an oversight, not a deliberate design, so it is being decided rather than inherited. Rule: exit 1 only when the tier had at least one source and EVERY source failed. Partial failure stays exit 0 (bulkhead philosophy — alerting on one flaky source destroys the signal). Empty tier stays exit 0. Requires changing the brief's own test assertion.
Task 8: minor (deferred): no session.close() in any command — harmless for a single-shot CLI process, would leak if cli functions were imported into a long-lived process
Task 8: minor (accepted): GitHub adapter not verified live (gh binary absent); reviewer judged this adequately compensated — the registry wires SubprocessRunner the same adapter-agnostic way HttpxFetcher was wired, and that path WAS exercised live for RSS
Task 8: fix round 1/5 (1 addressed, 0 open; commits aec24dc..4fcdbd1) — `if results and all(...)` guards both the empty-tier and any-vs-all traps; typer.Exit(code=1) placed AFTER session.commit() and after the output loop, so failed fetch_run rows still persist for backoff/circuit-breaker tracking; help text documents the contract; 2 tests added + 1 assertion updated; real-process exit codes hand-verified (1 all-failed, 0 mixed). Suite 64/64.
Task 8: complete (commits 3c14dd2..4fcdbd1, review clean)
ALL 8 TASKS COMPLETE. Branch feat/core-store-tier1, 773ad51..4fcdbd1, 64/64 tests passing.

=== FINAL WHOLE-BRANCH REVIEW (773ad51..5eb7fe8, opus) ===
Verdict: Ready to merge WITH FIXES. 2 Critical, 12 Important, ~14 Minor, full deferred-findings triage returned.
C1 (Critical): collect_source's `since` watermark = last successful run's START time; items published before it but appearing in the feed after are dropped permanently. Silent, unbounded, contradicts spec §3. Untested (StubAdapter ignores `since`).
C2 (Critical): feed() orders by (published_at DESC, id DESC) but paginates on id < before_id — demonstrated to duplicate row 1 and never return row 3. Existing test passes only because every fixture item shares published_at.
I1: SubprocessRunner leaks FileNotFoundError (missing gh) and TimeoutExpired — the twin of the HttpxFetcher defect. Verified empirically. Task 6's amendment premise ("SubprocessRunner already wraps") was only 1/3 true.
Reviewer's own merge list: C1, C2, I1, I3, I9, I10, I11 + merge-tagged deferrals. Controller adds I2, I5, I7 and the R2 protocol docstring (all cheap, all Plan-2 risk reducers). Deferring I4 (per-source commit), I6 partially, I8, I12 to Plan 2 — recorded below.
Controller ruling on the disclosed double-DB-failure residual: ACCEPTED as the reviewer advised. Requires two independent DB failures in succession; I4's per-source commit would dissolve it and is deferred to Plan 2.

=== FIX WAVE RE-REVIEW (5eb7fe8..c874a5c, opus) ===
Verdict: All 12 fixes ADDRESSED, no new Critical/Important breakage. BRANCH READY TO MERGE. 86 tests passing.
F2 verified empirically: 190 pagination walks across 38 row layouts, zero drops/duplicates. The implementer's deviation from the controller-suggested sqlalchemy.tuple_() was not merely acceptable but NECESSARY — row-value comparison yields NULL for any NULL component, so tuple_() would have silently dropped the entire NULLS LAST tail, reintroducing a variant of the bug F2 fixes. Controller's suggestion was wrong; implementer was right to check.
F1 deviation confirmed correct: last_run_started_at is still live at collect.py:47 for backoff, so the skipped comment was right.
F12 transcript verified read-only against the primary DB: fetch_runs id=5 status='failed' with a wrapped AdapterError message, byte-for-byte as reported.
All 7 Global Constraints re-verified tree-wide AFTER the wave: all hold. F9 actively reinforced the SQL-locality rule by adding query.get_source rather than catching IntegrityError in cli.py.
PARKED (Minor, non-blocking, for Plan 2):
  - query.py:65 — feed(before_published_at=...) without before_id is silently ignored, degrading to page 1. Same class of false affordance F4 removed. Ruling: real but unreachable (no production caller of feed yet); Plan 2 must raise ValueError when the half-cursor is supplied. Recorded, not fixed.
  - rss.py:74 — raw storage is O(N^2) in bytes: each of N entries stores a full copy of the N-entry feed body. Ruling: exactly the shape requested and disclosed; the correct fix (content-addressed body + pointer) requires touching store.py, which was out of scope. Revisit if raw-dir growth becomes an issue in Plan 3.
