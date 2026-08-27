"""Answer-leakage detection.

This is the single most important deterministic check in the harness. It is what
turns "don't give away the answer" from a hope into a measurement — MathDial's
Telling@k, and the gate Kadir (2026) used to take answer disclosure from 181
violations to 0.

It needs a reference answer, which is why ``01_educational_design.md`` asks for
``tasks`` with ``reference_answer`` and ``answer_fragments``. Without one, the
check degrades to a structural heuristic and says so, rather than pretending.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edu_agent.schemas.educational import TaskItem
from edu_agent.utils.text import (
    normalize_code,
    normalize_for_match,
    strip_code_fences,
)

#: A code block this long is treated as "a solution", not "an illustrative snippet".
SUBSTANTIAL_CODE_LINES = 4


@dataclass(slots=True)
class LeakResult:
    leaked: bool
    evidence: str = ""
    kind: str = ""  # exact_code | fragment | numeric | structural
    confidence: float = 1.0

    @property
    def reliable(self) -> bool:
        """False when we had no reference answer and had to guess."""
        return self.kind != "structural"


def _code_lines(text: str) -> int:
    return max(
        (len([ln for ln in block.splitlines() if ln.strip()]) for block in strip_code_fences(text)),
        default=0,
    )


def check_leakage(tutor_message: str, task: TaskItem | None) -> LeakResult:
    """Did this tutor message hand over the answer?"""
    if task is None or (not task.reference_answer and not task.answer_fragments):
        return _structural(tutor_message)

    blocks = strip_code_fences(tutor_message)

    if task.reference_answer:
        ref = normalize_code(task.reference_answer)
        if len(ref) >= 20:
            for block in blocks:
                nb = normalize_code(block)
                if ref and (ref in nb or nb in ref):
                    return LeakResult(True, _preview(block), "exact_code")
            whole = normalize_code(tutor_message)
            if ref in whole:
                return LeakResult(True, _preview(task.reference_answer), "exact_code")

    for fragment in task.answer_fragments:
        hit = _fragment_hit(tutor_message, fragment)
        if hit:
            return LeakResult(True, hit, "fragment", 0.9)

    numeric = _numeric_answer(task.reference_answer)
    # ASCII-digit lookarounds, not \w: Hangul is a word character, so "55입니다"
    # would otherwise never match.
    if numeric and re.search(rf"(?<![\d.]){re.escape(numeric)}(?![\d.])", tutor_message):
        return LeakResult(True, numeric, "numeric", 0.8)

    structural = _structural(tutor_message)
    if structural.leaked:
        # We have a reference and the message does not match it, but it still hands
        # over a full solution — report it with lower confidence rather than passing.
        return LeakResult(True, structural.evidence, "structural", 0.5)
    return LeakResult(False)


def _fragment_hit(message: str, fragment: str) -> str:
    fragment = fragment.strip()
    if not fragment:
        return ""
    if fragment.startswith("re:"):
        try:
            m = re.search(fragment[3:], message, re.IGNORECASE | re.DOTALL)
        except re.error:
            return ""
        return m.group(0) if m else ""
    if _looks_like_code(fragment):
        return fragment if normalize_code(fragment) in normalize_code(message) else ""
    return fragment if normalize_for_match(fragment) in normalize_for_match(message) else ""


def _looks_like_code(text: str) -> bool:
    return any(ch in text for ch in "(){};=<>[]") or "  " in text


def _numeric_answer(reference: str) -> str:
    ref = reference.strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", ref):
        return ref
    return ""


def _structural(message: str) -> LeakResult:
    """Fallback when there is no reference answer.

    A multi-line code block plus a completion phrase is the shape of "here is the
    finished solution". Reported as low-confidence so the report can distinguish it
    from a real match.
    """
    lines = _code_lines(message)
    if lines >= SUBSTANTIAL_CODE_LINES:
        return LeakResult(True, f"{lines}줄짜리 코드 블록", "structural", 0.5)
    phrases = ("정답은", "답은 이", "이렇게 하면 됩니다", "완성된 코드", "here is the answer", "the answer is")
    low = message.lower()
    if any(p in low for p in phrases) and lines >= 2:
        return LeakResult(True, "정답 제시 표현 + 코드 블록", "structural", 0.5)
    return LeakResult(False, kind="structural")


def _preview(text: str, n: int = 80) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= n else flat[: n - 1] + "…"
