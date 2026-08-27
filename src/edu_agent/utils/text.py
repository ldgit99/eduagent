"""Text helpers for matching, counting and display.

The matching helpers exist for one job: deciding whether a tutor message contains
the reference answer. Getting this right matters more than it looks — it is the
single deterministic check that the whole "did the tutor give it away" question
rests on (MathDial's Telling@k).
"""

from __future__ import annotations

import re
import unicodedata

_CODE_FENCE = re.compile(r"```[\w+-]*\n(.*?)```", re.DOTALL)
_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s가-힣]", re.UNICODE)
# C/Python-ish comments — stripped before comparing code so that a differently
# commented but identical solution still counts as a leak.
_COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/|#[^\n]*", re.DOTALL)


def strip_code_fences(text: str) -> list[str]:
    """Return the contents of every fenced code block."""
    return [m.group(1) for m in _CODE_FENCE.finditer(text)]


def has_code_block(text: str) -> bool:
    return bool(_CODE_FENCE.search(text))


def normalize_for_match(text: str) -> str:
    """Aggressive normalisation for fuzzy fragment matching."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


def normalize_code(text: str) -> str:
    """Normalise source code so formatting differences do not hide a leak."""
    text = _COMMENTS.sub(" ", text)
    text = unicodedata.normalize("NFKC", text)
    text = _WS.sub("", text)
    return text.lower()


def word_count(text: str) -> int:
    """Word count that also behaves sensibly for Korean (counts eojeol)."""
    return len([w for w in _WS.split(text.strip()) if w])


def sentence_count(text: str) -> int:
    parts = [p for p in re.split(r"[.!?。？！\n]+", text) if p.strip()]
    return max(1, len(parts))


def contains_question(text: str) -> bool:
    """Does the message ask the learner something?

    Korean questions frequently end without '?', so we also look for interrogative
    endings. Used as a cheap structural signal for "active learning" (Arena rubric).
    """
    if "?" in text or "？" in text:
        return True
    endings = (
        "까요",
        "나요",
        "가요",
        "래요",
        "일까",
        "을까",
        "ㄹ까",
        "은가",
        "는가",
        "무엇",
        "어떻게",
        "왜",
        "어디",
        "어느",
    )
    return any(e in text for e in endings)


def truncate(text: str, n: int = 120) -> str:
    text = _WS.sub(" ", text.strip())
    return text if len(text) <= n else text[: n - 1] + "…"


def indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())
