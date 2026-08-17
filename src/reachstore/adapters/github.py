from __future__ import annotations

import json
from datetime import datetime

from reachstore.adapters.base import AdapterError, CommandRunner, NormalizedItem


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class GithubRepoAdapter:
    """Collects releases from a GitHub repository via the gh CLI."""

    kind = "github_repo"
    tier = 1

    def __init__(self, runner: CommandRunner, timeout: int = 120):
        self._runner = runner
        self._timeout = timeout

    def fetch(self, identifier: str, since: datetime | None) -> list[NormalizedItem]:
        if identifier.count("/") != 1:
            raise AdapterError(f"expected 'owner/repo', got {identifier!r}")

        raw = self._runner.run(
            ["gh", "api", f"repos/{identifier}/releases", "--paginate"], timeout=self._timeout
        )
        try:
            releases = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AdapterError(f"gh returned unparseable JSON for {identifier}: {exc}") from exc

        items: list[NormalizedItem] = []
        for release in releases:
            published = _parse_iso(release.get("published_at"))
            if since is not None and published is not None and published < since:
                continue
            items.append(
                NormalizedItem(
                    external_id=str(release["id"]),
                    url=release.get("html_url", ""),
                    title=release.get("name") or release.get("tag_name"),
                    author_handle=(release.get("author") or {}).get("login"),
                    published_at=published,
                    content_text=release.get("body") or "",
                    raw=release,
                )
            )
        return items
