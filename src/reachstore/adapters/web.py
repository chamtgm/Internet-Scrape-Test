from __future__ import annotations

import hashlib
from datetime import datetime

from reachstore.adapters.base import AdapterError, HttpFetcher, NormalizedItem

JINA_PREFIX = "https://r.jina.ai/"


def _extract_title(body: str) -> str | None:
    for line in body.splitlines():
        if line.startswith("Title:"):
            return line.removeprefix("Title:").strip()
    return None


def _extract_content(body: str) -> str:
    marker = "Markdown Content:"
    if marker in body:
        return body.split(marker, 1)[1].strip()
    return body.strip()


class WebPageAdapter:
    """Reads a single web page through Jina Reader.

    Yields at most one item. The external_id is the content hash, so an unchanged
    page collects to zero new rows and an edited page produces a new item.
    """

    kind = "web_page"
    tier = 1

    def __init__(self, http: HttpFetcher, timeout: int = 120) -> None:
        self._http = http
        self._timeout = timeout

    def fetch(self, identifier: str, since: datetime | None) -> list[NormalizedItem]:
        if not identifier.startswith(("http://", "https://")):
            # Without this check, an empty (or otherwise malformed) identifier
            # concatenates onto JINA_PREFIX to produce "https://r.jina.ai/",
            # which fetches Jina's own homepage and stores it as an item with
            # url="". github.py validates its identifier thoroughly; this was
            # the one adapter with no validation at all.
            raise AdapterError(f"expected an http(s) URL, got {identifier!r}")
        body = self._http.get(f"{JINA_PREFIX}{identifier}", timeout=self._timeout)
        content = _extract_content(body)
        if not content.strip():
            raise AdapterError(f"empty content returned for {identifier}")
        return [
            NormalizedItem(
                external_id=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                url=identifier,
                title=_extract_title(body),
                author_handle=None,
                published_at=None,
                content_text=content,
                raw={"body": body},
            )
        ]
