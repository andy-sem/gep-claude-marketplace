"""Finds new human feedback on a pull request."""

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any


class FeedbackDetector:
    """Decides whether a PR has feedback newer than the last addressed one."""

    @staticmethod
    def _iso(moment: datetime) -> str:
        """ISO 8601 UTC with milliseconds and `Z`, as JS `toISOString()`."""
        return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    @staticmethod
    def _time(value: Any) -> float | None:
        """Epoch seconds of an ISO timestamp, None when absent or unparsable (JS `Date.parse` -> NaN)."""
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.timestamp()

    @classmethod
    def newest_feedback_at(cls, items: Iterable[Mapping] | None, cutoff: Any) -> str | None:
        """Newest human feedback after the cutoff, or None.

        Items are `{login, body, state?, createdAt}`. Feedback: author not a bot, body without
        the marker, created after the cutoff; a review counts when it has a body or requests
        changes, a comment when it has a body. An unparsable cutoff counts everything.
        """
        # Lazy: the watcher module imports this one.
        from gated_dev.watch.watcher import PrWatcher

        parsed_cutoff = cls._time(cutoff)
        after = parsed_cutoff if parsed_cutoff is not None else float("-inf")
        newest: str | None = None
        newest_at = float("-inf")
        for item in items or []:
            if (item.get("login") or "").endswith("[bot]"):
                continue
            body = item.get("body") or ""
            if PrWatcher.MARKER in body:
                continue
            has_body = body.strip() != ""
            if item.get("state") is not None:
                if not has_body and item["state"] != "CHANGES_REQUESTED":
                    continue
            elif not has_body:
                continue
            at = cls._time(item.get("createdAt"))
            if at is None or at <= after:
                continue
            if newest is None or at > newest_at:
                newest, newest_at = item["createdAt"], at
        return newest

    @classmethod
    def new_feedback_at(cls, pr: Mapping | None, last_addressed: Any) -> str | None:
        """Cutoff: the last addressed comment, else the PR creation time."""
        pr = pr or {}
        return cls.newest_feedback_at(
            pr.get("feedback"),
            last_addressed if last_addressed is not None else pr.get("createdAt"),
        )
