"""Domain model for ``02_design_principles.md`` — the project's core differentiator.

Plan v2 §7. A natural-language principle ("점진적 스캐폴딩을 제공한다") is **not**
copied into a system prompt verbatim. It is converted into an executable structure::

    DesignPrinciple (P02)
      └─ DesignGuideline (G03)
           └─ BehaviorRule (B05)   triggers + escalation ladder + constraints
                └─ Constraint(strength=hard)  ->  runtime policy gate (R)
                └─ EvaluationCriterion (E04)  ->  deterministic check or judge rubric

Two v2 additions matter most:

* ``Strength.HARD`` vs ``Strength.SOFT`` — LearnLM's *pedagogical instruction
  following* distinction. Only hard constraints become runtime gates; soft ones are
  prompt guidance judged by an LLM.
* ``when`` conditions over **learner-state variables** (``attempts >= 2``). This is
  what lets the harness say "the answer may be revealed *now*" instead of the
  research-discredited blanket "never reveal the answer".
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import Field, field_validator, model_validator

from edu_agent.schemas.common import (
    BehaviorId,
    CheckType,
    CriterionId,
    DocumentModel,
    GuidelineId,
    HarnessModel,
    PrincipleId,
    Strength,
)


class TriggerEvent(StrEnum):
    """Learner/session events that can activate a behaviour rule (§7.4)."""

    SESSION_START = "session_start"
    LEARNER_REQUESTS_HELP = "learner_requests_help"
    LEARNER_REQUESTS_ANSWER = "learner_requests_answer"
    LEARNER_INCORRECT = "learner_incorrect"
    LEARNER_CORRECT = "learner_correct"
    LEARNER_STUCK = "learner_stuck"
    LEARNER_MISCONCEPTION = "learner_misconception"
    LEARNER_SHOWS_REASONING = "learner_shows_reasoning"
    LEARNER_OFF_TASK = "learner_off_task"
    LEARNER_FRUSTRATED = "learner_frustrated"
    LEARNER_SHARES_PII = "learner_shares_pii"
    TASK_COMPLETED = "task_completed"
    TURN_ANY = "turn_any"
    CUSTOM = "custom"


class AgentAction(StrEnum):
    """Vocabulary of agent moves, ordered roughly least → most directive.

    Derived from MathDial's teacher-move taxonomy (Focus / Probing / Telling /
    Generic) and Bridge's remediation strategies.
    """

    ASK_FOR_REASONING = "ask_for_reasoning"
    ASK_METACOGNITIVE_QUESTION = "ask_metacognitive_question"
    ASK_CLARIFYING_QUESTION = "ask_clarifying_question"
    PROVIDE_DIRECTIONAL_HINT = "provide_directional_hint"
    PROVIDE_CONCEPTUAL_HINT = "provide_conceptual_hint"
    PROVIDE_PARTIAL_EXAMPLE = "provide_partial_example"
    PROVIDE_WORKED_EXAMPLE = "provide_worked_example"
    PROVIDE_DETAILED_EXPLANATION = "provide_detailed_explanation"
    GIVE_DIRECT_ANSWER = "give_direct_answer"
    GIVE_PROCESS_FEEDBACK = "give_process_feedback"
    GIVE_OUTCOME_FEEDBACK = "give_outcome_feedback"
    ACKNOWLEDGE_AND_ENCOURAGE = "acknowledge_and_encourage"
    PROMPT_REFLECTION = "prompt_reflection"
    PROMPT_SELF_EXPLANATION = "prompt_self_explanation"
    REDIRECT_TO_TASK = "redirect_to_task"
    REFUSE_AND_EXPLAIN = "refuse_and_explain"
    SUMMARIZE_PROGRESS = "summarize_progress"
    ESCALATE_TO_HUMAN = "escalate_to_human"
    CUSTOM = "custom"


#: Directiveness rank used by deterministic checks (higher = more of the answer given).
ACTION_DIRECTIVENESS: dict[AgentAction, int] = {
    AgentAction.ASK_FOR_REASONING: 0,
    AgentAction.ASK_METACOGNITIVE_QUESTION: 0,
    AgentAction.ASK_CLARIFYING_QUESTION: 0,
    AgentAction.PROMPT_REFLECTION: 0,
    AgentAction.PROMPT_SELF_EXPLANATION: 0,
    AgentAction.ACKNOWLEDGE_AND_ENCOURAGE: 0,
    AgentAction.REDIRECT_TO_TASK: 0,
    AgentAction.REFUSE_AND_EXPLAIN: 0,
    AgentAction.SUMMARIZE_PROGRESS: 0,
    AgentAction.ESCALATE_TO_HUMAN: 0,
    AgentAction.GIVE_PROCESS_FEEDBACK: 1,
    AgentAction.PROVIDE_DIRECTIONAL_HINT: 1,
    AgentAction.PROVIDE_CONCEPTUAL_HINT: 2,
    AgentAction.GIVE_OUTCOME_FEEDBACK: 2,
    AgentAction.PROVIDE_PARTIAL_EXAMPLE: 3,
    AgentAction.PROVIDE_WORKED_EXAMPLE: 4,
    AgentAction.PROVIDE_DETAILED_EXPLANATION: 4,
    AgentAction.GIVE_DIRECT_ANSWER: 5,
    AgentAction.CUSTOM: 2,
}

#: Learner-state variables the runtime tracks and that ``when`` conditions may use.
STATE_VARIABLES: tuple[str, ...] = (
    "attempts",
    "help_requests",
    "answer_requests",
    "stuck_turns",
    "ladder_level",
    "misconception_active",
    "reasoning_shown",
    "off_task_count",
    "frustration_flag",
    "pii_detected",
    "task_completed",
    "turn_index",
)

#: ``attempts >= 2``, ``reasoning_shown == true``, ``a >= 1 and b < 3``
_COND_TOKEN = re.compile(
    r"""
    (?P<var>[a-z_][a-z0-9_]*)\s*
    (?P<op><=|>=|==|!=|<|>)\s*
    (?P<val>true|false|\d+)
    """,
    re.VERBOSE,
)
_COND_SHAPE = re.compile(
    r"^\s*(?:[a-z_][a-z0-9_]*\s*(?:<=|>=|==|!=|<|>)\s*(?:true|false|\d+))"
    r"(?:\s+(?:and|or)\s+(?:[a-z_][a-z0-9_]*\s*(?:<=|>=|==|!=|<|>)\s*(?:true|false|\d+)))*\s*$"
)


def validate_condition(expr: str) -> str:
    """Validate a ``when`` expression against the tiny supported grammar.

    Only ``<var> <op> <int|true|false>`` joined by ``and``/``or`` is allowed. The
    grammar is deliberately minimal: it is evaluated by
    :func:`edu_agent.runtime.state.evaluate_condition` without ``eval``.
    """
    expr = expr.strip()
    if not expr:
        return expr
    if not _COND_SHAPE.match(expr):
        raise ValueError(
            f"조건식을 이해할 수 없습니다: {expr!r}. "
            "예: 'attempts >= 2', 'reasoning_shown == true and stuck_turns >= 1'"
        )
    for m in _COND_TOKEN.finditer(expr):
        if m.group("var") not in STATE_VARIABLES:
            raise ValueError(
                f"알 수 없는 학습자 상태 변수 {m.group('var')!r}. 사용 가능: {', '.join(STATE_VARIABLES)}"
            )
    return expr


class StatementType(StrEnum):
    """CAP-CPT policy-statement taxonomy: factual / behavioral / conditional."""

    FACTUAL = "factual"
    BEHAVIORAL = "behavioral"
    CONDITIONAL = "conditional"


class LadderStep(HarnessModel):
    """One rung of an escalation ladder (level 1 = least directive)."""

    level: int = Field(ge=1)
    action: AgentAction
    custom_action: str = Field(default="", description="Used when action == custom")
    when: str = Field(default="", description="학습자 상태 조건 (예: 'attempts >= 2')")
    note: str = ""

    @field_validator("when")
    @classmethod
    def _cond(cls, v: str) -> str:
        return validate_condition(v)

    @model_validator(mode="after")
    def _custom_named(self) -> LadderStep:
        if self.action == AgentAction.CUSTOM and not self.custom_action:
            raise ValueError("custom_action is required when action == 'custom'")
        return self

    @property
    def label(self) -> str:
        return self.custom_action or self.action.value


class ConstraintKind(StrEnum):
    """Machine-checkable constraint templates (§7.4)."""

    NEVER_ACTION = "never_action"  # params: action
    ACTION_ONLY_AFTER_LEVEL = "action_only_after_level"  # params: action, level
    ACTION_ONLY_WHEN = "action_only_when"  # params: action, when
    REQUIRE_ACTION_BEFORE = "require_action_before"  # params: action, before
    MAX_ACTIONS_PER_TURN = "max_actions_per_turn"  # params: action, max
    MAX_DIRECTIVENESS_ON_FIRST_HELP = "max_directiveness_on_first_help"  # params: rank
    REQUIRE_ACTION_AFTER_TRIGGER = "require_action_after_trigger"  # params: trigger, action
    NO_ANSWER_LEAKAGE_UNLESS = "no_answer_leakage_unless"  # params: when
    CUSTOM = "custom"  # params: text -> LLM judge


#: Constraint kinds that can be enforced/checked without an LLM.
DETERMINISTIC_KINDS: frozenset[ConstraintKind] = frozenset(
    k for k in ConstraintKind if k is not ConstraintKind.CUSTOM
)


class Constraint(HarnessModel):
    """A constraint on agent behaviour.

    ``strength=hard`` constraints become runtime policy gates (§11.2) and
    deterministic checks; ``soft`` ones become prompt guidance judged by an LLM.
    """

    kind: ConstraintKind
    strength: Strength = Strength.HARD
    params: dict[str, Any] = Field(default_factory=dict)
    text: str = Field(default="", description="사람이 읽는 제약 문장")

    @model_validator(mode="after")
    def _check_params(self) -> Constraint:
        required: dict[ConstraintKind, tuple[str, ...]] = {
            ConstraintKind.NEVER_ACTION: ("action",),
            ConstraintKind.ACTION_ONLY_AFTER_LEVEL: ("action", "level"),
            ConstraintKind.ACTION_ONLY_WHEN: ("action", "when"),
            ConstraintKind.REQUIRE_ACTION_BEFORE: ("action", "before"),
            ConstraintKind.MAX_ACTIONS_PER_TURN: ("action", "max"),
            ConstraintKind.MAX_DIRECTIVENESS_ON_FIRST_HELP: ("rank",),
            ConstraintKind.REQUIRE_ACTION_AFTER_TRIGGER: ("trigger", "action"),
            ConstraintKind.NO_ANSWER_LEAKAGE_UNLESS: ("when",),
            ConstraintKind.CUSTOM: ("text",),
        }
        for key in required.get(self.kind, ()):
            if key == "text":
                if not (self.text or self.params.get("text")):
                    raise ValueError(f"constraint {self.kind} requires 'text'")
                continue
            if key not in self.params:
                raise ValueError(f"constraint {self.kind} requires param {key!r}")
        if "when" in self.params:
            validate_condition(str(self.params["when"]))
        if self.kind == ConstraintKind.CUSTOM and self.strength is Strength.HARD:
            # A free-text constraint cannot be gated deterministically.
            object.__setattr__(self, "strength", Strength.SOFT)
        return self

    @property
    def check_type(self) -> CheckType:
        if self.kind == ConstraintKind.CUSTOM or self.strength is Strength.SOFT:
            return CheckType.LLM_JUDGE
        return CheckType.DETERMINISTIC

    @property
    def gateable(self) -> bool:
        """Can the runtime block a violating response before it reaches the learner?"""
        return self.strength is Strength.HARD and self.kind in DETERMINISTIC_KINDS


class EvaluationCriterion(HarnessModel):
    """How fidelity to a rule/principle is checked (E01, E02 ...)."""

    id: CriterionId
    statement: str
    check: CheckType = CheckType.LLM_JUDGE
    metric: str = Field(default="", description="deterministic check name or judge rubric key")
    principle_ids: list[str] = Field(default_factory=list)
    behavior_ids: list[str] = Field(default_factory=list)


class BehaviorRule(HarnessModel):
    """Executable behaviour attached to a principle (B01, B02 ...)."""

    id: BehaviorId
    name: str
    triggers: list[TriggerEvent] = Field(default_factory=list)
    custom_trigger: str = ""
    ladder: list[LadderStep] = Field(default_factory=list)
    actions: list[AgentAction] = Field(
        default_factory=list, description="단발성 행동 (사다리가 없을 때)"
    )
    constraints: list[Constraint] = Field(default_factory=list)
    evaluation: list[str] = Field(default_factory=list, description="E-ids")
    guideline_ids: list[str] = Field(default_factory=list, description="G-ids this rule realises")

    @model_validator(mode="after")
    def _validate(self) -> BehaviorRule:
        if self.ladder:
            levels = [s.level for s in self.ladder]
            if levels != sorted(levels) or len(set(levels)) != len(levels):
                raise ValueError(f"ladder levels must be strictly increasing, got {levels}")
        if not self.ladder and not self.actions:
            raise ValueError(f"behaviour {self.id} needs a ladder or at least one action")
        if not self.triggers and not self.custom_trigger:
            raise ValueError(f"behaviour {self.id} needs at least one trigger")
        return self

    def allowed_actions(self) -> set[AgentAction]:
        return {s.action for s in self.ladder} | set(self.actions)


class DesignGuideline(HarnessModel):
    """Design guidance derived from a principle (G01, G02 ...)."""

    id: GuidelineId
    text: str


class DesignPrinciple(HarnessModel):
    """One design principle (P01, P02 ...)."""

    id: PrincipleId
    name: str = Field(description="원리명 (snake_case, 예: progressive_scaffolding)")
    title: str = Field(default="", description="표시용 제목 (예: 점진적 스캐폴딩)")
    description: str = ""
    statement_type: StatementType = StatementType.BEHAVIORAL
    basis: list[str] = Field(default_factory=list, description="근거 이론/문헌")
    library_id: str = Field(default="", description="원리 라이브러리에서 가져왔다면 그 id")
    guidelines: list[DesignGuideline] = Field(default_factory=list)
    required_behaviors: list[str] = Field(default_factory=list, description="AI의 필수 행동 (자연어)")
    prohibited_behaviors: list[str] = Field(default_factory=list, description="AI의 금지 행동 (자연어)")
    applicability: str = Field(default="", description="적용 조건")
    rules: list[BehaviorRule] = Field(default_factory=list)
    confirmed: bool = Field(
        default=False,
        description="사용자가 구조화 결과를 확인했는가. False면 컴파일에 포함되지 않는다.",
    )


class PolicyStatement(HarnessModel):
    """A cross-cutting stance (learner agency, scaffolding, feedback, reflection)."""

    stance: str = ""
    details: str = ""
    principle_ids: list[str] = Field(default_factory=list)


class AnswerPolicy(StrEnum):
    """§4.3 — default is CONDITIONAL, not NEVER."""

    NEVER = "never"
    CONDITIONAL = "conditional"
    ALLOWED = "allowed"


class DesignPrinciples(DocumentModel):
    """Root model for ``02_design_principles.md``."""

    SCHEMA_NAME: ClassVar[str] = "design_principles"

    theories_and_strategies: list[str] = Field(default_factory=list)
    answer_policy: AnswerPolicy = AnswerPolicy.CONDITIONAL
    answer_condition: str = Field(
        default="attempts >= 3 or stuck_turns >= 2",
        description="answer_policy == conditional 일 때 정답 제공이 허용되는 학습자 상태 조건",
    )
    principles: list[DesignPrinciple] = Field(default_factory=list)
    learner_agency: PolicyStatement = Field(default_factory=PolicyStatement)
    scaffolding: PolicyStatement = Field(default_factory=PolicyStatement)
    feedback: PolicyStatement = Field(default_factory=PolicyStatement)
    reflection: PolicyStatement = Field(default_factory=PolicyStatement)
    escalation: str = Field(
        default="",
        description="에이전트가 혼자 감당하지 않고 사람에게 넘겨야 하는 상황 (§14 안전 정책으로 컴파일됨)",
    )
    criteria: list[EvaluationCriterion] = Field(default_factory=list)
    raw_user_text: str = Field(
        default="", description="사용자가 붙여넣은 원문 (출처 추적용, 절대 버리지 않음)"
    )

    @field_validator("answer_condition")
    @classmethod
    def _cond(cls, v: str) -> str:
        return validate_condition(v)

    # --- convenience -----------------------------------------------------
    def all_rules(self) -> list[BehaviorRule]:
        return [r for p in self.principles for r in p.rules]

    def confirmed_principles(self) -> list[DesignPrinciple]:
        return [p for p in self.principles if p.confirmed]

    def hard_constraints(self) -> list[tuple[DesignPrinciple, BehaviorRule, Constraint]]:
        out = []
        for p in self.principles:
            for r in p.rules:
                for c in r.constraints:
                    if c.gateable:
                        out.append((p, r, c))
        return out

    def criterion(self, cid: str) -> EvaluationCriterion | None:
        return next((c for c in self.criteria if c.id == cid), None)

    def used_ids(self) -> set[str]:
        ids: set[str] = {c.id for c in self.criteria}
        for p in self.principles:
            ids.add(p.id)
            ids |= {g.id for g in p.guidelines}
            ids |= {r.id for r in p.rules}
        return ids

    def missing_required(self) -> list[str]:
        missing: list[str] = []
        if not self.principles:
            missing.append("principles")
        for p in self.principles:
            if not p.confirmed:
                missing.append(f"principles[{p.id}].confirmed")
            elif not p.rules:
                missing.append(f"principles[{p.id}].rules")
        return missing

    @model_validator(mode="after")
    def _unique_ids(self) -> DesignPrinciples:
        seen: set[str] = set()
        for i in [
            *(p.id for p in self.principles),
            *(g.id for p in self.principles for g in p.guidelines),
            *(r.id for p in self.principles for r in p.rules),
            *(c.id for c in self.criteria),
        ]:
            if i in seen:
                raise ValueError(f"중복된 id: {i}")
            seen.add(i)
        return self
