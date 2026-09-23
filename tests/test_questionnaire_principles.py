"""The 02 questionnaire — what it asks, and that the answers land somewhere.

The questionnaires had no tests, which is how the opening section of
``02_design_principles.md`` ("적용 이론 및 교수학습전략") went years without ever
being asked for: the field existed, the template rendered it, and nothing filled
it. These tests pin each answer to the field it must reach.
"""

from __future__ import annotations

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


class FakeUI:
    """Answers the prompts in the order the questionnaire asks them."""

    def __init__(self, *, texts=None, choices=None, multis=None, yes=True) -> None:
        self.texts = list(texts or [])
        self.choices = list(choices or [])
        self.multis = list(multis or [])
        self.yes = yes
        self.asked: list[str] = []

    def ask_text(self, question, **kwargs):
        self.asked.append(question)
        return self.texts.pop(0) if self.texts else ""

    def ask_choice(self, question, options, **kwargs):
        self.asked.append(question)
        if self.choices:
            return self.choices.pop(0)
        default = kwargs.get("default", "")
        chosen = next((o for o in options if o.key == default), options[0])
        return chosen.value

    def ask_multi(self, question, options, **kwargs):
        self.asked.append(question)
        return self.multis.pop(0) if self.multis else []

    def ask_yes_no(self, question, **kwargs):
        self.asked.append(question)
        return self.yes


@pytest.fixture
def fake_ui(monkeypatch):
    def install(fake: FakeUI) -> FakeUI:
        for name in ("ask_text", "ask_choice", "ask_multi", "ask_yes_no"):
            monkeypatch.setattr(ui, name, getattr(fake, name))
            monkeypatch.setattr(q.ui, name, getattr(fake, name))
        for quiet in ("say", "note", "info", "ok", "warn", "fail", "header", "why"):
            if hasattr(ui, quiet):
                monkeypatch.setattr(q.ui, quiet, lambda *a, **k: None)
        monkeypatch.setattr(q.ui, "panel", lambda *a, **k: None)
        return fake

    return install


def _doc() -> DesignPrinciples:
    return DesignPrinciples.new(language="ko")


class TestTheories:
    def test_the_opening_section_is_asked_for(self, fake_ui):
        fake = fake_ui(FakeUI(multis=[["소크라테스식 질문법", "인지부하 이론"], []]))
        doc = q.run_principles(_doc(), provider=None)

        assert doc.theories_and_strategies == ["소크라테스식 질문법", "인지부하 이론"]
        assert any("이론이나 교수학습전략" in asked for asked in fake.asked)

    def test_free_text_theories_are_appended(self, fake_ui):
        fake_ui(FakeUI(multis=[["인지부하 이론"], []], texts=["동료 교수법"]))
        doc = q.run_principles(_doc(), provider=None)

        assert doc.theories_and_strategies == ["인지부하 이론", "동료 교수법"]

    def test_empty_is_allowed(self, fake_ui):
        fake_ui(FakeUI(multis=[[], []]))
        doc = q.run_principles(_doc(), provider=None)
        assert doc.theories_and_strategies == []


class TestEscalation:
    def test_handover_is_asked_and_stored(self, fake_ui):
        fake = fake_ui(FakeUI(multis=[[], []]))
        doc = q.run_principles(_doc(), provider=None)

        assert "선생님" in doc.escalation
        assert any("선생님에게 넘겨야" in asked for asked in fake.asked)

    def test_custom_handover_text_is_used(self, fake_ui):
        fake_ui(
            FakeUI(
                multis=[[], []],
                # answer policy, answer condition, own-principles source, escalation
                choices=[AnswerPolicy.CONDITIONAL, "attempts >= 3", "none", "custom"],
                # extra theory, four stances, then the custom handover sentence
                texts=["", "", "", "", "", "보호자 연락이 필요해 보이면 담임에게 알린다"],
            )
        )
        doc = q.run_principles(_doc(), provider=None)
        assert doc.escalation == "보호자 연락이 필요해 보이면 담임에게 알린다"


class TestMarkdownSource:
    def test_a_file_is_read_without_asking_how(self, tmp_path, fake_ui):
        path = tmp_path / "principles.md"
        path.write_text(PRINCIPLES_MD, encoding="utf-8")
        fake = fake_ui(FakeUI(multis=[[], []]))

        doc = q.run_principles(_doc(), provider=None, source=path)

        assert "추론 우선" in doc.raw_user_text
        # The file replaces the paste prompt entirely.
        assert not any("붙여넣" in asked for asked in fake.asked)

    def test_the_teacher_confirms_what_was_read(self, tmp_path, fake_ui):
        path = tmp_path / "principles.md"
        path.write_text(PRINCIPLES_MD, encoding="utf-8")
        fake = fake_ui(FakeUI(multis=[[], []]))

        q.run_principles(_doc(), provider=None, source=path)
        assert any("구조화할까요" in asked for asked in fake.asked)

    def test_declining_keeps_the_original_text_anyway(self, tmp_path, fake_ui):
        path = tmp_path / "principles.md"
        path.write_text(PRINCIPLES_MD, encoding="utf-8")
        fake_ui(FakeUI(multis=[[], []], yes=False))

        doc = q.run_principles(_doc(), provider=None, source=path)
        assert "점진적 스캐폴딩" in doc.raw_user_text
        assert doc.principles == []

    def test_a_missing_file_does_not_crash_the_questionnaire(self, tmp_path, fake_ui):
        fake_ui(FakeUI(multis=[[], []]))
        doc = q.run_principles(_doc(), provider=None, source=tmp_path / "nope.md")

        assert doc.raw_user_text == ""
        assert doc.escalation  # the rest of the questionnaire still ran


def test_answer_policy_still_defaults_to_conditional(fake_ui):
    fake_ui(FakeUI(multis=[[], []]))
    doc = q.run_principles(_doc(), provider=None)

    assert doc.answer_policy is AnswerPolicy.CONDITIONAL
    assert doc.answer_condition
