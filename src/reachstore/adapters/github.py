from __future__ import annotations

import json
from datetime import UTC, datetime

from reachstore.adapters.base import AdapterError, CommandRunner, NormalizedItem


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        # GitHub always sends an offset (`Z`) today, but fromisoformat returns
        # a naive datetime for any offset-free string, which either raises
        # TypeError when compared against an aware `since` or lands in a
        # TIMESTAMPTZ column interpreted in the session timezone. The Global
        # Constraint is that timestamps are timezone-aware UTC.
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


class GithubRepoAdapter:
    """Collects releases from a GitHub repository via the gh CLI."""

    kind = "github_repo"
    tier = 1

    def __init__(self, runner: CommandRunner, timeout: int = 120) -> None:
        self._runner = runner
        self._timeout = timeout

    def fetch(self, identifier: str, since: datetime | None) -> list[NormalizedItem]:
        owner, _, repo = identifier.partition("/")
        if not owner or not repo or identifier.count("/") != 1:
            raise AdapterError(f"expected 'owner/repo', got {identifier!r}")

        raw = self._runner.run(
            ["gh", "api", f"repos/{identifier}/releases", "--paginate"], timeout=self._timeout
        )
        try:
            releases = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AdapterError(f"gh returned unparseable JSON for {identifier}: {exc}") from exc

        if not isinstance(releases, list):
            raise AdapterError(
                f"expected a JSON array from gh for {identifier}, got {type(releases).__name__}"
            )

        items: list[NormalizedItem] = []
        for release in releases:
            release_id = release.get("id")
            if release_id is None:
                raise AdapterError(f"release missing 'id' field for {identifier}: {release!r}")
            published = _parse_iso(release.get("published_at"))
            if since is not None and published is not None and published < since:
                continue
            items.append(
                NormalizedItem(
                    external_id=str(release_id),
                    url=release.get("html_url", ""),
                    title=release.get("name") or release.get("tag_name"),
                    author_handle=(release.get("author") or {}).get("login"),
                    published_at=published,
                    content_text=release.get("body") or "",
                    raw=release,
                )
            )
        return items
