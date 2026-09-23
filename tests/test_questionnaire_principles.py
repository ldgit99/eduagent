"""The 02 questionnaire — what it asks, and that the answers land somewhere.

The questionnaires had no tests, which is how the opening section of
``02_design_principles.md`` ("적용 이론 및 교수학습전략") went unasked: the field
existed, the template rendered it, and nothing filled it. These tests pin each
answer to the field it must reach.

They answer through the injected :class:`edu_agent.ui.Prompter` rather than by
patching module globals, so a change to how the terminal asks cannot silently
break them and they cannot silently stop exercising the real code.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from edu_agent import ui
from edu_agent.questionnaire import principles as q
from edu_agent.schemas.principles import AnswerPolicy, DesignPrinciples

PRINCIPLES_MD = """\
# 우리 수업의 설계원리

## 추론 우선

학습자가 먼저 자기 생각을 말하게 한 뒤에만 힌트를 제공한다.

## 점진적 스캐폴딩

가장 약한 힌트부터 시작해 학습자 반응에 따라 수준을 올린다.
"""


class ScriptedPrompter:
    """Answers in the order the questionnaire asks, falling back to defaults."""

    def __init__(self, *, texts=None, choices=None, multis=None, yes=True) -> None:
        self.texts = list(texts or [])
        self.choices = list(choices or [])
        self.multis = list(multis or [])
        self.yes = yes
        self.asked: list[str] = []

    def ask_text(self, question: str, **kwargs: Any) -> str:
        self.asked.append(question)
        return self.texts.pop(0) if self.texts else str(kwargs.get("default", ""))

    def ask_choice(self, question: str, choices: Sequence[ui.Choice], **kwargs: Any) -> Any:
        self.asked.append(question)
        if self.choices:
            return self.choices.pop(0)
        default = kwargs.get("default", "")
        chosen = next((c for c in choices if c.key == default), choices[0])
        return chosen.value if chosen.value is not None else chosen.key

    def ask_multi(self, question: str, choices: Sequence[ui.Choice], **kwargs: Any) -> list[Any]:
        self.asked.append(question)
        return self.multis.pop(0) if self.multis else []

    def ask_yes_no(self, question: str, **kwargs: Any) -> bool | None:
        self.asked.append(question)
        return self.yes

    def ask_int(self, question: str, **kwargs: Any) -> int | None:
        self.asked.append(question)
        return kwargs.get("default")

    def was_asked(self, fragment: str) -> bool:
        return any(fragment in question for question in self.asked)


@pytest.fixture
def quiet(monkeypatch):
    """Silence output so a test failure shows the assertion, not the transcript."""
    for name in ("say", "note", "info", "ok", "warn", "fail", "header", "why", "panel"):
        monkeypatch.setattr(ui, name, lambda *a, **k: None)


def _doc() -> DesignPrinciples:
    return DesignPrinciples.new(language="ko")


def _run(prompter: ScriptedPrompter, **kwargs) -> DesignPrinciples:
    return q.run_principles(_doc(), provider=None, prompter=prompter, **kwargs)


pytestmark = pytest.mark.usefixtures("quiet")


class TestTheories:
    def test_the_opening_section_is_asked_for(self):
        prompter = ScriptedPrompter(multis=[["소크라테스식 질문법", "인지부하 이론"], []])
        doc = _run(prompter)

        assert doc.theories_and_strategies == ["소크라테스식 질문법", "인지부하 이론"]
        assert prompter.was_asked("이론이나 교수학습전략")

    def test_free_text_theories_are_appended(self):
        doc = _run(ScriptedPrompter(multis=[["인지부하 이론"], []], texts=["동료 교수법"]))
        assert doc.theories_and_strategies == ["인지부하 이론", "동료 교수법"]

    def test_empty_is_allowed(self):
        assert _run(ScriptedPrompter(multis=[[], []])).theories_and_strategies == []


class TestEscalation:
    def test_handover_is_asked_and_stored(self):
        prompter = ScriptedPrompter(multis=[[], []])
        doc = _run(prompter)

        assert "선생님" in doc.escalation
        assert prompter.was_asked("선생님에게 넘겨야")

    def test_custom_handover_text_is_used(self):
        doc = _run(
            ScriptedPrompter(
                multis=[[], []],
                # answer policy, answer condition, own-principles source, escalation
                choices=[AnswerPolicy.CONDITIONAL, "attempts >= 3", "none", "custom"],
                # extra theory, four stances, then the custom handover sentence
                texts=["", "", "", "", "", "보호자 연락이 필요해 보이면 담임에게 알린다"],
            )
        )
        assert doc.escalation == "보호자 연락이 필요해 보이면 담임에게 알린다"


class TestMarkdownSource:
    @pytest.fixture
    def source(self, tmp_path):
        path = tmp_path / "principles.md"
        path.write_text(PRINCIPLES_MD, encoding="utf-8")
        return path

    def test_a_file_is_read_without_asking_how(self, source):
        prompter = ScriptedPrompter(multis=[[], []])
        doc = _run(prompter, source=source)

        assert "추론 우선" in doc.raw_user_text
        # The file replaces the paste prompt entirely.
        assert not prompter.was_asked("붙여넣")

    def test_the_teacher_confirms_what_was_read(self, source):
        prompter = ScriptedPrompter(multis=[[], []])
        _run(prompter, source=source)
        assert prompter.was_asked("구조화할까요")

    def test_declining_keeps_the_original_text_anyway(self, source):
        doc = _run(ScriptedPrompter(multis=[[], []], yes=False), source=source)
        assert "점진적 스캐폴딩" in doc.raw_user_text
        assert doc.principles == []

    def test_a_missing_file_does_not_crash_the_questionnaire(self, tmp_path):
        doc = _run(ScriptedPrompter(multis=[[], []]), source=tmp_path / "nope.md")

        assert doc.raw_user_text == ""
        assert doc.escalation  # the rest of the questionnaire still ran


def test_answer_policy_still_defaults_to_conditional():
    doc = _run(ScriptedPrompter(multis=[[], []]))

    assert doc.answer_policy is AnswerPolicy.CONDITIONAL
    assert doc.answer_condition


def test_the_terminal_prompter_satisfies_the_protocol():
    """The default has to be a real Prompter, not merely duck-typed by luck."""
    for name in ("ask_text", "ask_choice", "ask_multi", "ask_yes_no", "ask_int"):
        assert callable(getattr(ui.TERMINAL, name))
