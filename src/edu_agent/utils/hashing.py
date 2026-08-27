"""Content hashing used for drift detection and spec staleness."""

from __future__ import annotations

import hashlib


def hash_text(text: str) -> str:
    """Stable SHA-256 of text with newlines normalised.

    Line endings are normalised so that a file checked out on Windows and on Linux
    produces the same hash — otherwise every student on Windows would see a spurious
    "본문이 수정되었습니다" warning.
    """
    normalised = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return "sha256:" + hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def short_hash(text: str, n: int = 12) -> str:
    return hash_text(text).split(":", 1)[1][:n]
