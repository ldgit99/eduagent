"""Domain model for ``04_agent_spec.md`` — the executable specification (plan v2 §9).

This is the compiler's output and the runtime's input. It is a *human-readable
document* and a *machine-executable spec* at the same time: the YAML frontmatter is
what :mod:`edu_agent.runtime` loads, the Markdown body is what the student reads.
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from pydantic import Field, model_validator

from edu_agent.schemas.common import (
    CheckType,
    CriterionId,
    DocumentModel,
    HarnessModel,
    PersonaId,
    RuleId,
    ScenarioId,
    Strength,
)
from edu_agent.schemas.principles import (
    AgentAction,
    BehaviorRule,
    Constraint,
    EvaluationCriterion,
    TriggerEvent,
)


class Phase(HarnessModel):
    """One phase of the interaction flow.

    The flow is a *small* state machine: theory-informed phases with sub-goals and
    transition conditions, with the LLM free-form inside each phase (Sharma et al.
    2026). We deliberately do not build a full dialogue manager.
    """

    id: str = Field(description="phase id (예: diagnose)")
    title: str
    goal: str = ""
    allowed_actions: list[AgentAction] = Field(default_factory=list)
    enter_when: str = Field(default="", description="학습자 상태 조건")
    exit_when: str = Field(default="", description="학습자 상태 조건")
    note: str = ""


class PolicyGate(HarnessModel):
    """A hard constraint compiled into a runtime check (R01, R02 ...).

    Gates are evaluated *after* the model produces a response and *before* the
    learner sees it. A blocked response is regenerated with feedback; if it keeps
    failing, the runtime falls back to a safe action. Every decision is traced, and
    the trace is what produces the per-constraint compliance rate (CSR).
    """

    id: RuleId
    constraint: Constraint
    principle_id: str = ""
    behavior_id: str = ""
    criterion_ids: list[str] = Field(default_factory=list)
    message: str = Field(default="", description="차단 시 모델에게 주는 수정 지시")

    @model_validator(mode="after")
    def _hard_only(self) -> PolicyGate:
        if self.constraint.strength is not Strength.HARD:
            raise ValueError(f"gate {self.id}: only hard constraints become gates")
        return self


class StateVariableSpec(HarnessModel):
    """§7 Learner State Model — one tracked variable and how it is updated."""

    name: str
    initial: int | bool = 0
    description: str = ""
    increment_on: list[TriggerEvent] = Field(default_factory=list)
    reset_on: list[TriggerEvent] = Field(default_factory=list)
    set_true_on: list[TriggerEvent] = Field(default_factory=list)
    set_false_on: list[TriggerEvent] = Field(default_factory=list)


class ToolPolicy(HarnessModel):
    name: str
    description: str = ""
    when_allowed: str = Field(default="", description="학습자 상태 조건")
    permissions: list[str] = Field(default_factory=list)
    sandboxed: bool = True


class MemoryPolicy(HarnessModel):
    session_memory: bool = True
    learner_progress: bool = False
    long_term_memory: bool = False
    what_is_stored: list[str] = Field(default_factory=list)
    redact_pii: bool = True


class SafetyPolicy(HarnessModel):
    """§14 — general safety *and* pedagogical safety (SafeTutors 2026)."""

    general_rules: list[str] = Field(default_factory=list)
    pedagogical_rules: list[str] = Field(
        default_factory=list,
        description="정답 과잉 공개, 오개념 강화, 스캐폴딩 포기, 아첨(sycophancy)",
    )
    pii_action: str = "감지 시 저장하지 않고 안내한다"
    escalation: str = ""


class ScenarioTurn(HarnessModel):
    """One scripted learner turn in a test scenario."""

    text: str = Field(default="", description="빈 문자열이면 페르소나가 자유 생성")
    intent: str = Field(default="", description="이 턴의 의도 (예: answer_fishing)")
    expect_actions: list[AgentAction] = Field(default_factory=list, description="기대 행동 (권장)")
    forbid_actions: list[AgentAction] = Field(default_factory=list, description="금지 행동")


class TestScenario(HarnessModel):
    """§17 Test Scenarios (T01, T02 ...)."""

    id: ScenarioId
    name: str
    persona_id: PersonaId
    task_id: str = ""
    max_turns: int = Field(default=8, ge=1, le=50)
    seeds: int = Field(default=1, ge=1, description="같은 시나리오를 몇 번 반복할지 (pass^k)")
    opening: str = Field(default="", description="학습자의 첫 발화")
    turns: list[ScenarioTurn] = Field(default_factory=list)
    criteria: list[str] = Field(default_factory=list, description="E-ids 이 시나리오가 검사하는 기준")
    principle_ids: list[str] = Field(default_factory=list)
    note: str = ""


class CalibrationSlot(HarnessModel):
    """§18 Judge Calibration Set — a sample of turns for a human to score."""

    n_samples: int = Field(default=20, ge=0)
    dimensions: list[str] = Field(default_factory=list)
    min_agreement: float = Field(default=0.7, ge=0.0, le=1.0, description="κ 기준선")


class TraceLink(HarnessModel):
    """§19 Traceability row: P → G → B → R → E → T."""

    principle_id: str
    guideline_ids: list[str] = Field(default_factory=list)
    behavior_ids: list[str] = Field(default_factory=list)
    gate_ids: list[str] = Field(default_factory=list)
    criterion_ids: list[str] = Field(default_factory=list)
    scenario_ids: list[str] = Field(default_factory=list)

    @property
    def complete(self) -> bool:
        """A principle is fully traced only if it reaches a test scenario."""
        return bool(self.behavior_ids and self.criterion_ids and self.scenario_ids)


class AgentSpec(DocumentModel):
    """Root model for ``04_agent_spec.md``."""

    SCHEMA_NAME: ClassVar[str] = "agent_spec"

    # 1-4
    purpose: str = ""
    target_learner: str = ""
    learning_goals: list[str] = Field(default_factory=list, description="O-ids 또는 문장")
    agent_role: str = ""

    # 5-7
    behaviors: list[BehaviorRule] = Field(default_factory=list)
    phases: list[Phase] = Field(default_factory=list)
    state_variables: list[StateVariableSpec] = Field(default_factory=list)

    # 8-11
    scaffolding_policy: str = ""
    feedback_policy: str = ""
    agency_policy: str = ""
    gates: list[PolicyGate] = Field(default_factory=list)

    # 12-15
    tools: list[ToolPolicy] = Field(default_factory=list)
    memory: MemoryPolicy = Field(default_factory=MemoryPolicy)
    safety: SafetyPolicy = Field(default_factory=SafetyPolicy)
    system_prompt: str = ""

    # 16-19
    criteria: list[EvaluationCriterion] = Field(default_factory=list)
    scenarios: list[TestScenario] = Field(default_factory=list)
    calibration: CalibrationSlot = Field(default_factory=CalibrationSlot)
    traceability: list[TraceLink] = Field(default_factory=list)

    # provenance
    answer_condition: str = Field(default="", description="정답 제공이 허용되는 학습자 상태 조건")
    compiled_from: dict[str, str] = Field(
        default_factory=dict, description="입력 문서 경로 → hash (stale 감지)"
    )
    compiler_notes: list[str] = Field(default_factory=list)

    # --- convenience -----------------------------------------------------
    def behavior(self, bid: str) -> BehaviorRule | None:
        return next((b for b in self.behaviors if b.id == bid), None)

    def gate(self, rid: str) -> PolicyGate | None:
        return next((g for g in self.gates if g.id == rid), None)

    def scenario(self, tid: str) -> TestScenario | None:
        return next((s for s in self.scenarios if s.id == tid), None)

    def criterion(self, eid: str) -> EvaluationCriterion | None:
        return next((c for c in self.criteria if c.id == eid), None)

    def deterministic_criteria(self) -> list[EvaluationCriterion]:
        return [c for c in self.criteria if c.check is CheckType.DETERMINISTIC]

    def judge_criteria(self) -> list[EvaluationCriterion]:
        return [c for c in self.criteria if c.check is CheckType.LLM_JUDGE]

    def untraced_principles(self) -> list[str]:
        return [t.principle_id for t in self.traceability if not t.complete]

    def missing_required(self) -> list[str]:
        missing: list[str] = []
        if not self.system_prompt:
            missing.append("system_prompt")
        if not self.behaviors:
            missing.append("behaviors")
        if not self.criteria:
            missing.append("criteria")
        if not self.scenarios:
            missing.append("scenarios")
        return missing


class SpecStaleness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


__all__ = [
    "AgentSpec",
    "CalibrationSlot",
    "CriterionId",
    "MemoryPolicy",
    "Phase",
    "PolicyGate",
    "SafetyPolicy",
    "ScenarioTurn",
    "SpecStaleness",
    "StateVariableSpec",
    "TestScenario",
    "ToolPolicy",
    "TraceLink",
]
