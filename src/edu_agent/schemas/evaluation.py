"""Evaluation schema (plan v2 §14–15).

Three ideas from the literature shape this module:

* **Per-constraint / per-turn / per-session hierarchy** (SysBench CSR/ISR/SSR).
  A single overall score hides which rule broke, so every metric carries the ID of
  the constraint or criterion it came from.
* **Three-way labels, not booleans** (BEA 2025). "To some extent" is a real class
  and is the one models get wrong most often; collapsing it to pass/fail throws
  away exactly the signal a student needs.
* **Judge scores are provisional until calibrated** against human labels
  (Khanmigo's workflow; Norman et al. 2026 "reliability without validity"). A
  report renders judge dimensions with a warning until κ clears the threshold.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import Field, computed_field

from edu_agent.schemas.common import CheckType, HarnessModel


class Label(StrEnum):
    """Three-way label used by both deterministic checks and judges."""

    YES = "yes"
    PARTIAL = "partial"
    NO = "no"

    @property
    def score(self) -> float:
        return {"yes": 1.0, "partial": 0.5, "no": 0.0}[self.value]


class Dimension(StrEnum):
    """The nine evaluation areas (plan v2 §14.1)."""

    GOAL_ALIGNMENT = "goal_alignment"
    PEDAGOGICAL_FIDELITY = "pedagogical_fidelity"
    PRINCIPLE_FIDELITY = "principle_fidelity"
    ADAPTIVE_SUPPORT = "adaptive_support"
    LEARNER_AGENCY = "learner_agency"
    INTERACTION_QUALITY = "interaction_quality"
    FEEDBACK_QUALITY = "feedback_quality"
    SAFETY_ETHICS = "safety_ethics"
    TECHNICAL_STABILITY = "technical_stability"  # pass/fail, not scored


SCORED_DIMENSIONS: tuple[Dimension, ...] = tuple(
    d for d in Dimension if d is not Dimension.TECHNICAL_STABILITY
)

DIMENSION_LABELS_KO: dict[Dimension, str] = {
    Dimension.GOAL_ALIGNMENT: "학습목표 정렬성",
    Dimension.PEDAGOGICAL_FIDELITY: "교수전략 실행 충실도",
    Dimension.PRINCIPLE_FIDELITY: "설계원리 실행 충실도",
    Dimension.ADAPTIVE_SUPPORT: "적응적 지원",
    Dimension.LEARNER_AGENCY: "학습자 주도성 지원",
    Dimension.INTERACTION_QUALITY: "상호작용 적절성",
    Dimension.FEEDBACK_QUALITY: "피드백 적절성",
    Dimension.SAFETY_ETHICS: "안전·윤리적 실행",
    Dimension.TECHNICAL_STABILITY: "기술적 안정성",
}


class Evidence(HarnessModel):
    """A pointer into a trace, so every finding can be read in context."""

    session_id: str = ""
    scenario_id: str = ""
    persona_id: str = ""
    seed: int = 0
    turn_index: int = -1
    learner_message: str = ""
    tutor_message: str = ""
    note: str = ""


class CheckResult(HarnessModel):
    """One criterion evaluated against one session."""

    criterion_id: str
    dimension: Dimension
    check: CheckType
    label: Label
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    metric: str = ""
    rationale: str = ""
    evidence: list[Evidence] = Field(default_factory=list)
    judge_model: str = ""
    order_swapped: bool = Field(
        default=False, description="위치 편향 상쇄를 위해 순서를 바꿔 재판정했는가"
    )

    def model_post_init(self, _ctx: object) -> None:
        if self.score == 0.0 and self.label is not Label.NO:
            object.__setattr__(self, "score", self.label.score)


class ConstraintCompliance(HarnessModel):
    """CSR — per-constraint compliance rate across all turns (SysBench)."""

    gate_id: str
    constraint_text: str = ""
    principle_id: str = ""
    turns_applicable: int = 0
    turns_violated: int = 0
    first_violation_turn: int | None = None
    evidence: list[Evidence] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def rate(self) -> float:
        if self.turns_applicable == 0:
            return 1.0
        return 1.0 - self.turns_violated / self.turns_applicable


class LearnerSideMetrics(HarnessModel):
    """Student-side signals (§14.4). Tutor-only scoring misjudges (Neagu 2026)."""

    sessions: int = 0
    reasoning_elicited_sessions: int = 0
    retried_after_hint_sessions: int = 0
    solved_sessions: int = 0
    explained_process_sessions: int = 0
    pre_post_delta: float | None = Field(default=None, description="시뮬레이션 학생 사전/사후 정답률 변화")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reasoning_rate(self) -> float:
        return self.reasoning_elicited_sessions / self.sessions if self.sessions else 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def success_rate(self) -> float:
        return self.solved_sessions / self.sessions if self.sessions else 0.0


class SimulatorHealth(HarnessModel):
    """Validity check on the simulator itself (§13.4)."""

    sessions: int = 0
    constraint_violations: int = 0
    misconception_flips_on_untargeted_feedback: int = 0
    misconception_opportunities: int = 0
    mean_words_per_turn: float = 0.0
    off_task_share: float = 0.0
    warnings: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unfaithful_flip_rate(self) -> float:
        if not self.misconception_opportunities:
            return 0.0
        return self.misconception_flips_on_untargeted_feedback / self.misconception_opportunities


class TechnicalHealth(HarnessModel):
    """Dimension 9 — pass/fail, never a score."""

    errors: int = 0
    gate_regenerations: int = 0
    fallbacks: int = 0
    timeouts: int = 0
    mean_latency_ms: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def passed(self) -> bool:
        return self.errors == 0 and self.timeouts == 0 and self.fallbacks <= 2


class Calibration(HarnessModel):
    """Agreement between human and judge labels (§15)."""

    n: int = 0
    kappa: float | None = None
    threshold: float = 0.7
    rated_at: datetime | None = None
    per_dimension: dict[str, float] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def trustworthy(self) -> bool:
        return self.kappa is not None and self.kappa >= self.threshold

    @property
    def status_text(self) -> str:
        if self.kappa is None:
            return "미보정 — judge 점수는 참고용입니다 (edu-agent calibrate)"
        if self.trustworthy:
            return f"κ = {self.kappa:.2f} (n={self.n}) — 기준 충족"
        return f"κ = {self.kappa:.2f} (n={self.n}) — {self.threshold} 미만: judge 점수는 참고용"


class DimensionScore(HarnessModel):
    dimension: Dimension
    score_0_5: float = Field(default=0.0, ge=0.0, le=5.0)
    n_checks: int = 0
    deterministic_share: float = 0.0
    failures: list[CheckResult] = Field(default_factory=list)

    @property
    def label_ko(self) -> str:
        return DIMENSION_LABELS_KO[self.dimension]


class EvaluationReport(HarnessModel):
    """The output of ``edu-agent test``."""

    run_id: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    spec_hash: str = ""
    project: str = ""
    n_sessions: int = 0
    n_scenarios: int = 0
    n_personas: int = 0
    seeds: int = 1

    dimensions: list[DimensionScore] = Field(default_factory=list)
    checks: list[CheckResult] = Field(default_factory=list)
    compliance: list[ConstraintCompliance] = Field(default_factory=list)
    learner_side: LearnerSideMetrics = Field(default_factory=LearnerSideMetrics)
    simulator_health: SimulatorHealth = Field(default_factory=SimulatorHealth)
    technical: TechnicalHealth = Field(default_factory=TechnicalHealth)
    calibration: Calibration = Field(default_factory=Calibration)

    leakage_rate: float = 0.0
    first_leak_turns: list[int] = Field(default_factory=list)
    collapse_onsets: list[int] = Field(default_factory=list)
    pressure_capitulation_rate: float = 0.0

    notes: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def overall(self) -> float:
        scored = [d for d in self.dimensions if d.dimension in SCORED_DIMENSIONS and d.n_checks]
        if not scored:
            return 0.0
        return sum(d.score_0_5 for d in scored) / len(scored)

    def dimension(self, d: Dimension) -> DimensionScore | None:
        return next((x for x in self.dimensions if x.dimension is d), None)

    def failures(self) -> list[CheckResult]:
        """Failed checks, worst first — the input to ``edu-agent improve``."""
        bad = [c for c in self.checks if c.label is not Label.YES]
        return sorted(bad, key=lambda c: (c.score, c.check is not CheckType.DETERMINISTIC))

    def mean_collapse_onset(self) -> float | None:
        return sum(self.collapse_onsets) / len(self.collapse_onsets) if self.collapse_onsets else None
