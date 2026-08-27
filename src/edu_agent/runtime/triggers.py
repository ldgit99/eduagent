"""Trigger detection: turning a learner utterance into typed events.

Two layers, in this order:

1. **Rules** — Korean/English keyword and shape patterns. Fast, free, deterministic,
   and auditable by a student who wants to know why their agent reacted.
2. **Classifier** (optional) — one structured model call for the events rules are
   bad at (misconception, off-task, reasoning). Off by default in ``--no-llm``.

Rules run first and their result is never overridden for the *safety-critical*
events (PII, explicit answer requests): a classifier that mislabels those would
silently open a hard gate.
"""

from __future__ import annotations

import re

from edu_agent.schemas.principles import TriggerEvent
from edu_agent.utils.text import has_code_block, word_count

# --- PII ------------------------------------------------------------------
# Deliberately conservative: Korean RRN, phone, email, and "my name is ..." forms.
#
# NOTE: Hangul is a word character in Python's Unicode regex, so ``\b`` is *not* a
# boundary between "5678" and "이에요" — the most common way a Korean phone number
# actually appears. These patterns use explicit ASCII-digit lookarounds instead.
_PII_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<!\d)\d{6}\s*-\s*[1-4]\d{6}(?!\d)"),  # 주민등록번호
    re.compile(r"(?<!\d)01[016-9][-\s]?\d{3,4}[-\s]?\d{4}(?!\d)"),  # 휴대전화
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # email
    re.compile(r"(제|내)\s*이름은\s*\S+"),
    re.compile(r"(우리\s*집|저희\s*집)\s*주소는"),
    re.compile(r"(?<!\d)\d{1,2}\s*학년\s*\d{1,2}\s*반\s*\d{1,2}\s*번"),
)

_ANSWER_REQUEST = (
    "정답", "답만", "답좀", "답 좀", "그냥 알려", "그냥 답", "답을 주", "답 주",
    "코드 줘", "코드좀", "코드 좀", "코드 알려", "코드 보여",
    "완성된 코드", "전체 코드", "고친 코드", "다 알려",
    "just give me", "give me the answer", "show me the code", "tell me the answer",
)

_HELP_REQUEST = (
    "도와줘", "도와주세요", "모르겠", "어떻게 해", "어떡해", "힌트",
    "막혔", "안 돼요", "안돼요", "안 되는데", "잘 안", "어려워",
    "help", "stuck", "hint", "i don't know", "i dont know",
)

_FRUSTRATION = (
    "포기", "짜증", "화나", "그만할래", "너무 어려", "하기 싫", "못 하겠",
    "give up", "frustrated", "this is too hard",
)

_OFF_TASK = (
    "점심", "게임", "축구", "아이돌", "날씨", "숙제 말고", "다른 얘기",
    "노래", "영화", "심심", "너 누구", "너는 뭐",
    "what's the weather", "tell me a joke", "who are you",
)

_MISCONCEPTION_MARKERS = (
    "아니야", "아닌데", "맞잖아", "분명히", "확실히", "무조건",
    "원래 그런", "그건 상관없", "선생님이 그랬",
    "i'm sure", "definitely", "it must be",
)

_REASONING_MARKERS = (
    "때문에", "그래서", "왜냐하면", "인 것 같", "라고 생각", "생각해요",
    "확인해 봤", "해봤는데", "돌려봤", "출력이", "여기서",
    "because", "i think", "so i", "i tried",
)

_AUTHORITY_PRESSURE = (
    "선생님이", "교수님이", "허락", "괜찮다고 했", "시간이 없", "곧 제출",
    "마감", "teacher said", "deadline",
)

_COMPLETION = (
    "해결했", "됐어요", "됐다", "성공", "고쳤", "이제 돼", "잘 나와",
    "it works", "solved", "fixed it",
)


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(n in text for n in needles)


def detect_pii(text: str) -> str | None:
    """Return the matched PII snippet, or None."""
    for pattern in _PII_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(0)
    return None


def detect_pressure(text: str) -> bool:
    """Is the learner applying social pressure to get the answer?"""
    low = text.lower()
    return _contains_any(low, _AUTHORITY_PRESSURE) or _contains_any(low, _ANSWER_REQUEST)


def detect_triggers(
    learner_message: str,
    *,
    previous_correct: bool | None = None,
    first_turn: bool = False,
) -> list[TriggerEvent]:
    """Rule-based trigger detection for one learner utterance."""
    text = learner_message.strip()
    low = text.lower()
    events: list[TriggerEvent] = []

    if first_turn:
        events.append(TriggerEvent.SESSION_START)

    if detect_pii(text):
        events.append(TriggerEvent.LEARNER_SHARES_PII)

    if _contains_any(low, _ANSWER_REQUEST):
        events.append(TriggerEvent.LEARNER_REQUESTS_ANSWER)
        events.append(TriggerEvent.LEARNER_REQUESTS_HELP)
    elif _contains_any(low, _HELP_REQUEST):
        events.append(TriggerEvent.LEARNER_REQUESTS_HELP)

    if _contains_any(low, _FRUSTRATION):
        events.append(TriggerEvent.LEARNER_FRUSTRATED)

    if _contains_any(low, _OFF_TASK) and not has_code_block(text):
        events.append(TriggerEvent.LEARNER_OFF_TASK)

    if _contains_any(low, _COMPLETION):
        events.append(TriggerEvent.TASK_COMPLETED)
        events.append(TriggerEvent.LEARNER_CORRECT)

    if _contains_any(low, _MISCONCEPTION_MARKERS):
        events.append(TriggerEvent.LEARNER_MISCONCEPTION)

    shows_reasoning = _contains_any(low, _REASONING_MARKERS) or (
        word_count(text) >= 12 and TriggerEvent.LEARNER_REQUESTS_ANSWER not in events
    )
    if shows_reasoning:
        events.append(TriggerEvent.LEARNER_SHOWS_REASONING)

    if previous_correct is False:
        events.append(TriggerEvent.LEARNER_INCORRECT)

    if not events or events == [TriggerEvent.SESSION_START]:
        events.append(TriggerEvent.TURN_ANY)

    # Deduplicate, keep order.
    seen: set[TriggerEvent] = set()
    ordered: list[TriggerEvent] = []
    for e in events:
        if e not in seen:
            seen.add(e)
            ordered.append(e)
    return ordered


#: Events a classifier is allowed to add. Safety-critical events stay rule-owned so
#: a hallucinated label can never unlock a hard gate.
CLASSIFIER_EVENTS: frozenset[TriggerEvent] = frozenset(
    {
        TriggerEvent.LEARNER_MISCONCEPTION,
        TriggerEvent.LEARNER_OFF_TASK,
        TriggerEvent.LEARNER_SHOWS_REASONING,
        TriggerEvent.LEARNER_STUCK,
        TriggerEvent.LEARNER_FRUSTRATED,
        TriggerEvent.LEARNER_INCORRECT,
        TriggerEvent.LEARNER_CORRECT,
    }
)
