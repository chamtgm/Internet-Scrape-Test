# Task 6 Report: Web page adapter and registry

## What I implemented

- `tests/fixtures/jina_page.txt` — the exact fixture text from the brief (verified byte-for-byte with `diff` against the brief's literal content).
- `tests/test_adapter_web.py` — the exact test file from the brief (6 tests: Jina URL construction, single-item extraction with title, content-hash `external_id`, idempotency of the hash across repeated fetches of unchanged content, `AdapterError` on empty body, and registry coverage of all three Tier-1 kinds).
- `src/reachstore/adapters/web.py` — `WebPageAdapter(http, timeout=120)`, `kind = "web_page"`, `tier = 1`, module constant `JINA_PREFIX = "https://r.jina.ai/"`. Fetches `JINA_PREFIX + identifier` via the injected `HttpFetcher`, extracts a title (first `Title:` line) and content (everything after the `Markdown Content:` marker, or the whole trimmed body if the marker is absent), raises `AdapterError` if extracted content is empty/whitespace-only, and otherwise returns a single `NormalizedItem` whose `external_id` is `sha256(content_text.encode("utf-8")).hexdigest()`.
- `src/reachstore/adapters/registry.py` — `build_registry(http, runner) -> dict[str, Adapter]`, wiring `RssAdapter(http)`, `GithubRepoAdapter(runner)`, `WebPageAdapter(http)` and keying the result by each adapter's `.kind`.

Implemented exactly as given in the brief's reference code — no deviations in logic or naming.

## TDD Evidence

### RED

Command: `.venv/bin/pytest tests/test_adapter_web.py -v`

Run after creating the fixture and test file, before creating `web.py`/`registry.py`:

```
============================= test session starts ==============================
platform darwin -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- /Users/dev2/Desktop/Testing/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/dev2/Desktop/Testing
configfile: pyproject.toml
plugins: cov-7.1.0, anyio-4.14.2
collecting ... collected 0 items / 1 error

==================================== ERRORS ====================================
__________________ ERROR collecting tests/test_adapter_web.py __________________
ImportError while importing test module '/Users/dev2/Desktop/Testing/tests/test_adapter_web.py'.
...
tests/test_adapter_web.py:6: in <module>
    from reachstore.adapters.registry import build_registry
E   ModuleNotFoundError: No module named 'reachstore.adapters.registry'
=========================== short test summary info ============================
ERROR tests/test_adapter_web.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
=============================== 1 error in 0.07s ===============================
```

This is the expected failure: the test module imports `reachstore.adapters.registry` before `reachstore.adapters.web` (import order in the test file), so the first missing module reported is `registry`, not `web`. Both modules were genuinely absent at this point — this confirms the test file cannot collect until both source files exist, which is the correct RED state.

### GREEN

Command: `.venv/bin/pytest tests/test_adapter_web.py -v`

Run after implementing `web.py` and `registry.py`:

```
============================= test session starts ==============================
platform darwin -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- /Users/dev2/Desktop/Testing/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/dev2/Desktop/Testing
configfile: pyproject.toml
plugins: cov-7.1.0, anyio-4.14.2
collecting ... collected 6 items

tests/test_adapter_web.py::test_fetches_through_jina_reader PASSED       [ 16%]
tests/test_adapter_web.py::test_returns_single_item_with_extracted_title PASSED [ 33%]
tests/test_adapter_web.py::test_external_id_is_content_hash PASSED       [ 50%]
tests/test_adapter_web.py::test_unchanged_page_produces_identical_external_id PASSED [ 66%]
tests/test_adapter_web.py::test_empty_body_raises_adapter_error PASSED   [ 83%]
tests/test_adapter_web.py::test_registry_exposes_all_tier1_kinds PASSED  [100%]

============================== 6 passed in 0.03s ===============================
```

Also re-ran with `-W error::DeprecationWarning` — same 6 passed, no warnings surfaced.

## Full-suite result before committing

Command: `.venv/bin/pytest -q`

```
============================= test session starts ==============================
platform darwin -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/dev2/Desktop/Testing
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, anyio-4.14.2
collected 45 items

tests/test_adapter_github.py .........                                   [ 20%]
tests/test_adapter_rss.py .........                                      [ 40%]
tests/test_adapter_web.py ......                                         [ 53%]
tests/test_query_isolation.py ......                                     [ 66%]
tests/test_query_search.py .....                                         [ 77%]
tests/test_schema.py ...                                                 [ 84%]
tests/test_store.py .......                                              [100%]

============================== 45 passed in 0.28s ==============================
```

45/45 (39 existing + 6 new), confirming database-backed tests still pass alongside the new adapter tests.

## Files changed

- `src/reachstore/adapters/web.py` (new)
- `src/reachstore/adapters/registry.py` (new)
- `tests/fixtures/jina_page.txt` (new)
- `tests/test_adapter_web.py` (new)

Committed as `410c9f6` — "feat: web page adapter via Jina Reader and adapter registry". Staged by explicit filename (not `git add -A`); the pre-existing unrelated modification to `docs/superpowers/plans/2026-08-13-core-store-and-tier1-collection.md` was left untouched and uncommitted, as instructed.

## Reasoning on the three robustness points

1. **Empty vs. malformed distinguishable.** `WebPageAdapter` raises `AdapterError` when the extracted content is empty/whitespace-only (`test_empty_body_raises_adapter_error`). This is a deliberate difference from `RssAdapter`'s fix, not an inconsistency: for RSS, "zero entries" is a normal, expected steady state for a healthy feed that simply hasn't posted anything new — treating it as an error would trip the circuit breaker on a perfectly healthy source. For a single web page, there is no equivalent "legitimately empty" state — a successful fetch of a real page should always yield extractable text. An empty result here means Jina Reader failed to extract anything (blocked, paywalled, JS-only page it couldn't render, dead link, rate-limited empty response, etc.), which is a genuine failure signal Task 7's orchestrator should know about, e.g. to eventually disable a permanently-broken web source. So "empty" and "malformed" collapse into the same case for this adapter by design, and raising is correct.

2. **Only `AdapterError` escapes.** Audited `web.py` for any operation that could raise a different exception type: `_extract_title`/`_extract_content` operate purely on `str` methods (`splitlines`, `startswith`, `removeprefix`, `in`, `split`, `strip`) which cannot raise on any string input; `hashlib.sha256(content.encode("utf-8"))` cannot raise for ordinary text (only theoretical lone-surrogate strings would, which won't arise from Jina's plain-text output). The adapter never indexes into a parsed structure (unlike `GithubRepoAdapter`'s `release["id"]`), so there's no `KeyError`/`AttributeError`/`TypeError` surface from malformed input. The only unguarded call is `self._http.get(...)`, and that's consistent with `RssAdapter`/`GithubRepoAdapter`, neither of which wraps their injected fetcher/runner calls either — fetcher-level failures are out of scope for the adapter layer in this codebase's existing convention.

3. **Input validation before I/O.** I implemented the brief exactly as given: `identifier` is concatenated directly onto `JINA_PREFIX` with no shape validation before the `http.get` call. I considered whether to add a check that `identifier` looks like an absolute URL (e.g. starts with `http://`/`https://`), analogous to `GithubRepoAdapter` validating `owner/repo` shape before shelling out. I chose not to add it, per instructions to implement the brief as written and report the gap rather than silently expand scope. Reasoning for why it's a smaller gap than GitHub's: an invalid identifier here doesn't risk misdirecting a privileged CLI call or constructing a bad REST path — it just becomes part of a URL string. Jina Reader will either fail to fetch it (surfacing at the `http.get` layer) or return some page whose content, if empty, already raises `AdapterError` via the existing check. There's no crash path. I'm flagging this as a considered-but-declined addition rather than a silent gap.

## Self-review findings

- Completeness: all brief steps implemented in order (fixture, test, RED, implementation, GREEN, commit).
- Idempotency: `external_id` is derived solely from `content_text` (the post-marker, stripped body) via SHA-256; no URL, timestamp, or other time-varying data is mixed into the hash. Verified directly with `test_unchanged_page_produces_identical_external_id` and by inspection of `web.py`.
- Protocol conformance: verified interactively that `isinstance(WebPageAdapter(...), Adapter)` is `True` and that every value in `build_registry(...)` satisfies `Adapter` (checked via the `runtime_checkable` protocol).
- Registry coverage: confirmed `build_registry` returns keys `{"rss", "github_repo", "web_page"}` with `rss`/`web_page` wired to the injected `http` and `github_repo` wired to the injected `runner` (checked by inspecting `._http`/`._runner` attribute types on the returned instances).
- Isolation: `grep -nE "^\s*(import|from)\s+(sqlalchemy|subprocess|httpx|requests)"` against both new files returned no matches.
- Consistency: `web.py` matches the shape of `rss.py`/`github.py` — same constructor signature pattern (`__init__(self, dep, timeout: int = 120)`), same `kind`/`tier` class attributes, same `fetch(self, identifier, since)` signature, same "only raise `AdapterError`" discipline.
- Quality/discipline: no extra features added beyond the brief (no caching, retries, HTML parsing, or extra adapters).
- Testing: all 6 new tests exercise real behavior against the committed fixture with a hand-written fake (`FakeHttp`/`FakeRunner`), no mocking of logic under test; output is clean with no warnings.

No issues found; no changes made beyond the brief.

## Issues, concerns, or deviations

None. Implementation matches the brief verbatim. The only judgment call (documented above under robustness point 3) was a deliberate decision *not* to add identifier validation beyond the brief, to avoid silently expanding scope — flagged here as required rather than acted on unilaterally.

---

## Fix Report (review round 1)

Two Important findings from review. Both fixed. Scope held to the files the coordinator authorized: `tests/test_adapter_web.py`, `src/reachstore/adapters/base.py`, and a new `tests/test_adapter_base.py`. Did not touch `rss.py`, `github.py`, `web.py`, `registry.py`, or Tasks 1-3. The two Minor findings (URL-shape validation on the Jina identifier, and the `test_unchanged_page_produces_identical_external_id` name) were left untouched as instructed — deferred to final review.

### Fix 1: registry test could not catch a swapped dependency

**What I changed.** `tests/test_adapter_web.py::test_registry_exposes_all_tier1_kinds` now names the `FakeRunner()` instance and asserts each adapter's private dependency attribute is the same object passed into `build_registry`:

```python
def test_registry_exposes_all_tier1_kinds(http):
    runner = FakeRunner()
    registry = build_registry(http, runner)
    assert set(registry) == {"rss", "github_repo", "web_page"}
    assert all(adapter.tier == 1 for adapter in registry.values())
    assert registry["rss"]._http is http
    assert registry["web_page"]._http is http
    assert registry["github_repo"]._runner is runner
```

Attribute names were read from the actual source rather than assumed: `RssAdapter.__init__` sets `self._http = http` (`src/reachstore/adapters/rss.py`), `GithubRepoAdapter.__init__` sets `self._runner = runner` (`src/reachstore/adapters/github.py`), `WebPageAdapter.__init__` sets `self._http = http` (`src/reachstore/adapters/web.py`) — matching exactly what the coordinator's suggested snippet used, confirmed by inspection rather than assumption.

### Fix 2: `HttpxFetcher` let `httpx` exceptions escape unwrapped

**Confirmation of the pre-fix defect**, run before touching `base.py`:

Command:
```
.venv/bin/python -c "
import httpx
from unittest.mock import patch
from reachstore.adapters.base import HttpxFetcher, AdapterError

def raise_connect_error(*a, **k):
    raise httpx.ConnectError('boom')

with patch('httpx.get', side_effect=raise_connect_error):
    try:
        HttpxFetcher().get('https://example.com', timeout=5)
        print('NO EXCEPTION RAISED')
    except AdapterError as e:
        print('AdapterError raised (unexpected pre-fix):', e)
    except httpx.HTTPError as e:
        print('httpx.HTTPError escaped (confirms defect):', type(e).__name__, e)
    except Exception as e:
        print('other exception escaped:', type(e).__name__, e)
"
```

Output:
```
httpx.HTTPError escaped (confirms defect): ConnectError boom
```

This confirms the pre-fix `HttpxFetcher.get` propagated the raw `httpx.ConnectError` (an `httpx.HTTPError` subclass) instead of `AdapterError`, verifying the defect the review flagged before any fix was applied.

**What I changed.** `src/reachstore/adapters/base.py`, `HttpxFetcher.get` — wrapped the `httpx.get` call and `raise_for_status()` in a `try`/`except httpx.HTTPError`, re-raising as `AdapterError` with `from exc` to preserve the original traceback as `__cause__`. Exact change (`git diff`):

```diff
     def get(self, url: str, *, timeout: int) -> str:
-        response = httpx.get(url, timeout=timeout, follow_redirects=True)
-        response.raise_for_status()
+        try:
+            response = httpx.get(url, timeout=timeout, follow_redirects=True)
+            response.raise_for_status()
+        except httpx.HTTPError as exc:
+            raise AdapterError(f"HTTP request failed for {url}: {exc}") from exc
         return response.text
```

No other change to `base.py`: method signature, `SubprocessRunner`, the protocols, and `NormalizedItem` are untouched.

**New tests** — `tests/test_adapter_base.py` (new file), using `monkeypatch.setattr(httpx, "get", ...)` so no real network call occurs:

```python
import httpx
import pytest

from reachstore.adapters.base import AdapterError, HttpxFetcher


def test_httpx_fetcher_wraps_http_status_error(monkeypatch):
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(404, request=request)

    def raise_status_error(*args, **kwargs):
        raise httpx.HTTPStatusError("404 Not Found", request=request, response=response)

    monkeypatch.setattr(httpx, "get", raise_status_error)

    with pytest.raises(AdapterError) as exc_info:
        HttpxFetcher().get("https://example.com", timeout=5)

    assert isinstance(exc_info.value.__cause__, httpx.HTTPStatusError)


def test_httpx_fetcher_wraps_transport_error(monkeypatch):
    def raise_connect_error(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", raise_connect_error)

    with pytest.raises(AdapterError):
        HttpxFetcher().get("https://example.com", timeout=5)
```

Both the status-error case (`httpx.HTTPStatusError`, constructed with minimal `httpx.Request`/`httpx.Response` objects — this proved straightforward, no fallback to a simpler pair was needed) and the transport-error case (`httpx.ConnectError`) were built cleanly; no case was skipped.

### Covering tests run

Command: `.venv/bin/pytest tests/test_adapter_web.py tests/test_adapter_base.py -v`

```
============================= test session starts ==============================
platform darwin -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- /Users/dev2/Desktop/Testing/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/dev2/Desktop/Testing
configfile: pyproject.toml
plugins: cov-7.1.0, anyio-4.14.2
collecting ... collected 8 items

tests/test_adapter_web.py::test_fetches_through_jina_reader PASSED       [ 12%]
tests/test_adapter_web.py::test_returns_single_item_with_extracted_title PASSED [ 25%]
tests/test_adapter_web.py::test_external_id_is_content_hash PASSED       [ 37%]
tests/test_adapter_web.py::test_unchanged_page_produces_identical_external_id PASSED [ 50%]
tests/test_adapter_web.py::test_empty_body_raises_adapter_error PASSED   [ 62%]
tests/test_adapter_web.py::test_registry_exposes_all_tier1_kinds PASSED  [ 75%]
tests/test_adapter_base.py::test_httpx_fetcher_wraps_http_status_error PASSED [ 87%]
tests/test_adapter_base.py::test_httpx_fetcher_wraps_transport_error PASSED [100%]

============================== 8 passed in 0.04s ===============================
```

Also re-ran with `-W error::DeprecationWarning` for the same 8 tests — identical pass, no warnings surfaced.

### Full suite

Command: `.venv/bin/pytest -q`

```
============================= test session starts ==============================
platform darwin -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/dev2/Desktop/Testing
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, anyio-4.14.2
collected 47 items

tests/test_adapter_base.py ..                                            [  4%]
tests/test_adapter_github.py .........                                   [ 23%]
tests/test_adapter_rss.py .........                                      [ 42%]
tests/test_adapter_web.py ......                                         [ 55%]
tests/test_query_isolation.py ......                                     [ 68%]
tests/test_query_search.py .....                                         [ 78%]
tests/test_schema.py ...                                                 [ 85%]
tests/test_store.py .......                                              [100%]

============================== 47 passed in 0.33s ==============================
```

47/47 passing. `tests/test_adapter_rss.py` — 9/9 passing — confirmed unaffected by the `HttpxFetcher` change, as expected: `RssAdapter`'s tests inject `FakeHttp`, never touching `HttpxFetcher` or real `httpx.get`.

### Files changed (this round)

- `src/reachstore/adapters/base.py` (modified — `HttpxFetcher.get` wraps `httpx.HTTPError` as `AdapterError`)
- `tests/test_adapter_web.py` (modified — dependency-identity assertions added to `test_registry_exposes_all_tier1_kinds`)
- `tests/test_adapter_base.py` (new — 2 tests covering `HttpxFetcher`'s status-error and transport-error wrapping)

Committed as `9ef08c2` — "fix: wrap httpx transport failures as AdapterError; assert registry dependency identity".

### Outcome

Both Important findings resolved with the coordinator's prescribed approach; no deviations. Minor findings deferred as instructed.
