"""The unit a human and a judge both rate: one metric, on one turn, in one session.

This identity was a bare ``tuple[str, int, str]`` assembled by hand in nine
places, and encoded for JSON by joining on ``"|"`` — which breaks the moment a
session id contains that character, silently mispairing a human rating with the
wrong judge verdict. Since κ is computed from exactly those pairings, the failure
would show up as a calibration number rather than as an error.

One frozen value type, one encoding, one place to fix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class _Rated(Protocol):
    """Anything that names a rated item: a human rating, a piece of evidence."""

    session_id: str
    turn_index: int
    metric: str


@dataclass(frozen=True, slots=True)
class RatedItem:
    """A (session, turn, metric) triple, hashable and JSON-safe."""

    session_id: str
    turn_index: int
    metric: str

    @classmethod
    def of(cls, source: _Rated | Any, metric: str | None = None) -> RatedItem:
        """Build from anything carrying the three fields.

        ``metric`` may be supplied separately because a judge verdict names the
        metric on the check while the turn it cites lives on the evidence.
        """
        return cls(
            session_id=str(getattr(source, "session_id", "")),
            turn_index=int(getattr(source, "turn_index", -1)),
            metric=str(metric if metric is not None else getattr(source, "metric", "")),
        )

    def key(self) -> str:
        """A string key for JSON. Lengths are prefixed so no separator can collide."""
        return f"{len(self.session_id)}:{self.session_id}|{self.turn_index}|{self.metric}"

    @classmethod
    def from_key(cls, raw: str) -> RatedItem | None:
        """Read :meth:`key` back. Returns ``None`` rather than raising on junk."""
        head, _, rest = raw.partition(":")
        if not head.isdigit():
            return None
        width = int(head)
        session_id, sep, remainder = rest[:width], rest[width : width + 1], rest[width + 1 :]
        if sep != "|" or len(session_id) != width:
            return None
        turn, _, metric = remainder.partition("|")
        if not turn.lstrip("-").isdigit():
            return None
        return cls(session_id=session_id, turn_index=int(turn), metric=metric)

    def __str__(self) -> str:
        return f"{self.session_id} · 턴 {self.turn_index} · {self.metric}"


__all__ = ["RatedItem"]
