"""Domain model for ``01_educational_design.md`` (plan v2 §6).

Everything here is *decided by the user*; the harness only structures it and flags
what is missing. Sections 7–9 (tasks, learner-state signals, "what success looks
like") were added in v2 because they are what makes deterministic evaluation and
runtime state tracking possible.
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from pydantic import Field

from edu_agent.schemas.common import ActivityId, DocumentModel, HarnessModel, ObjectiveId


class SupportType(StrEnum):
    """Kinds of support the user expects from the AI (§6 of the document)."""

    QUESTION = "question"
    HINT = "hint"
    FEEDBACK = "feedback"
    EXPLANATION = "explanation"
    ASSESSMENT = "assessment"
    RECOMMENDATION = "recommendation"
    OTHER = "other"


class LearningContext(HarnessModel):
    """§1 학습 맥락."""

    target_learners: str = Field(default="", description="대상 학습자 (예: 중학교 2학년)")
    age_or_grade: str = Field(default="", description="연령 또는 학년")
    subject: str = Field(default="", description="교과/영역")
    topic: str = Field(default="", description="학습 주제")
    usage_situation: str = Field(default="", description="활용 상황 (수업 중, 과제, 자율학습 ...)")
    expected_users: int | None = Field(default=None, ge=1, description="예상 사용자 수")


class LearningProblem(HarnessModel):
    """§2 학습 문제."""

    current_difficulties: str = Field(default="", description="현재 학습자가 겪는 어려움")
    core_problem: str = Field(default="", description="해결하고자 하는 핵심 문제")
    limitations_of_existing_support: str = Field(default="", description="기존 학습방법/지원의 한계")


class LearningObjective(HarnessModel):
    """§3 학습목표 (O01, O02 ...)."""

    id: ObjectiveId
    statement: str = Field(description="학습자가 ... 할 수 있다")
    evidence: str = Field(default="", description="달성을 확인할 수 있는 관찰 가능한 행동/산출물")


class LearningActivity(HarnessModel):
    """§4 학습활동 (A01, A02 ...)."""

    id: ActivityId
    name: str
    description: str = ""
    order: int = Field(default=0, ge=0, description="학습 순서 (0 = 순서 없음)")
    learner_self_directed: bool = Field(default=False, description="학생이 스스로 수행해야 하는 활동")


class AIUsageContext(HarnessModel):
    """§5 AI 활용 맥락."""

    intervention_points: list[str] = Field(default_factory=list, description="AI가 개입하는 시점")
    before_ai: str = Field(default="", description="AI 활용 전 학습자 활동")
    during_ai: str = Field(default="", description="AI 활용 중 학습자 활동")
    after_ai: str = Field(default="", description="AI 활용 후 학습자 활동")


class ExpectedAISupport(HarnessModel):
    """§6 기대하는 AI 지원."""

    types: list[SupportType] = Field(default_factory=list)
    other_description: str = ""
    must_do: list[str] = Field(default_factory=list, description="AI가 반드시 해야 하는 행동")
    must_not_do: list[str] = Field(default_factory=list, description="AI가 해서는 안 되는 행동")


class TaskItem(HarnessModel):
    """§7 과제와 정답 기준.

    The reference answer is what makes the *deterministic* answer-leakage check
    possible (MathDial Telling@k). Without it the harness can only judge leakage
    with an LLM, which is far less reliable.
    """

    id: str = Field(description="과제 id (예: t01)")
    title: str = ""
    prompt_file: str = Field(default="", description="tasks/ 내 과제 파일 경로")
    reference_answer: str = Field(default="", description="정답 (코드/수식/값). 누출 검사 기준")
    answer_fragments: list[str] = Field(
        default_factory=list,
        description="정답의 핵심 조각들 (부분 노출도 잡기 위한 문자열/정규식)",
    )
    common_errors: list[str] = Field(default_factory=list, description="흔한 오류 유형")
    misconceptions: list[str] = Field(default_factory=list, description="관련 오개념 문장")


class LearnerStateSignal(HarnessModel):
    """§8 학습자 상태 신호 — runtime이 추적할 변수와 그 의미."""

    variable: str = Field(description="attempts | stuck_turns | misconception_active | ...")
    meaning: str = ""
    how_detected: str = Field(default="", description="어떻게 감지하는가 (규칙/분류)")


class SuccessIndicator(HarnessModel):
    """§9 성공의 모습 — 학습자 측에서 관찰되어야 하는 것 (학생 측 지표로 연결)."""

    statement: str
    metric: str = Field(default="", description="evaluator의 학생 측 지표 이름")


class EducationalDesign(DocumentModel):
    """Root model for ``01_educational_design.md``."""

    SCHEMA_NAME: ClassVar[str] = "educational_design"

    title: str = Field(default="", description="프로젝트/에이전트 이름")
    context: LearningContext = Field(default_factory=LearningContext)
    problem: LearningProblem = Field(default_factory=LearningProblem)
    objectives: list[LearningObjective] = Field(default_factory=list)
    activities: list[LearningActivity] = Field(default_factory=list)
    ai_usage: AIUsageContext = Field(default_factory=AIUsageContext)
    expected_support: ExpectedAISupport = Field(default_factory=ExpectedAISupport)
    tasks: list[TaskItem] = Field(default_factory=list)
    learner_state_signals: list[LearnerStateSignal] = Field(default_factory=list)
    success_indicators: list[SuccessIndicator] = Field(default_factory=list)

    def missing_required(self) -> list[str]:
        missing: list[str] = []
        if not self.context.target_learners:
            missing.append("context.target_learners")
        if not self.context.subject and not self.context.topic:
            missing.append("context.subject|topic")
        if not self.problem.core_problem:
            missing.append("problem.core_problem")
        if not self.objectives:
            missing.append("objectives")
        if not self.expected_support.types:
            missing.append("expected_support.types")
        return missing
