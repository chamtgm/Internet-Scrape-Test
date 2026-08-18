from __future__ import annotations

from datetime import UTC, datetime
from time import struct_time
from typing import Any

import feedparser

from reachstore.adapters.base import AdapterError, HttpFetcher, NormalizedItem


def _to_datetime(parsed: struct_time | None) -> datetime | None:
    if parsed is None:
        return None
    return datetime(*parsed[:6], tzinfo=UTC)


def _content_text(entry: Any) -> str:
    """Prefer <content:encoded> over <description>.

    For any feed emitting <content:encoded> (WordPress, Substack, Ghost, most
    of the blogging world), <description> is a teaser and <content:encoded>
    is the full article body. feedparser exposes <content:encoded> as
    `entry.content`, a list of dicts with a `value` key. Atom is unaffected:
    feedparser already backfills `summary` from `<content>` when `<summary>`
    is absent, so falling back to `summary` here does not regress that path.
    """
    content_list = entry.get("content")
    if content_list:
        value = content_list[0].get("value")
        if value:
            return value
    return entry.get("summary", "")


class RssAdapter:
    kind = "rss"
    tier = 1

    def __init__(self, http: HttpFetcher, timeout: int = 120) -> None:
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
            entry_id = entry.get("id") or link
            items.append(
                NormalizedItem(
                    external_id=entry_id,
                    url=link,
                    title=entry.get("title"),
                    author_handle=entry.get("author"),
                    published_at=published,
                    content_text=_content_text(entry),
                    # F6: store the true upstream bytes, not feedparser's parsed
                    # dict (which is not a replayable document, and cannot be
                    # reprocessed after a parser change without re-scraping).
                    # A single response body covers every entry in the feed, so
                    # store it per item alongside the entry's own id, letting a
                    # future reprocessor re-parse the original XML and locate
                    # this entry within it.
                    raw={"feed_xml": body, "entry_id": entry_id},
                )
            )
        return items
