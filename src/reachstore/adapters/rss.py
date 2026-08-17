from __future__ import annotations

from datetime import UTC, datetime
from time import struct_time

import feedparser

from reachstore.adapters.base import AdapterError, HttpFetcher, NormalizedItem


def _to_datetime(parsed: struct_time | None) -> datetime | None:
    if parsed is None:
        return None
    return datetime(*parsed[:6], tzinfo=UTC)


class RssAdapter:
    kind = "rss"
    tier = 1

    def __init__(self, http: HttpFetcher, timeout: int = 120):
        self._http = http
        self._timeout = timeout

    def fetch(self, identifier: str, since: datetime | None) -> list[NormalizedItem]:
        body = self._http.get(identifier, timeout=self._timeout)
        feed = feedparser.parse(body)
        if not feed.entries:
            if feed.bozo:
                raise AdapterError(f"could not parse {identifier}: {feed.bozo_exception}")
            return []

        items: list[NormalizedItem] = []
        for entry in feed.entries:
            published = _to_datetime(entry.get("published_parsed") or entry.get("updated_parsed"))
            if since is not None and published is not None and published < since:
                continue
            link = entry.get("link", "")
            items.append(
                NormalizedItem(
                    external_id=entry.get("id") or link,
                    url=link,
                    title=entry.get("title"),
                    author_handle=entry.get("author"),
                    published_at=published,
                    content_text=entry.get("summary", ""),
                    raw=dict(entry),
                )
            )
        return items
