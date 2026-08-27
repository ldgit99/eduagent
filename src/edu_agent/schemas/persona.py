"""Simulated-learner personas (plan v2 §13).

The research is blunt about prompt-only student personas: strong models are *better
than the average student at every grade level* (Srivatsa 2025), they abandon a
misconception in response to **any** correction — even an irrelevant one (Do 2026,
Selective Flip Score), and teachers judge them too compliant, too attentive, and
emotionless (Martynova 2025).

So the design here separates three things that prompting usually conflates:

1. :class:`KnowledgeState` — an *explicit* epistemic state (mastery per concept,
   active misconceptions, a seeded wrong solution). The LLM only **renders** it.
2. :class:`BeliefUpdate` — rules for when a misconception may be dropped. The
   default requires the tutor's feedback to actually target the misconception.
3. :class:`BehaviorProfile` — help-seeking, answer-fishing, persistence, off-task,
   frustration, verbosity, typos. Behaviour is parameterised, not narrated.

State transitions are computed by :mod:`edu_agent.simulator.state`, never by the
LLM's own judgement.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from edu_agent.schemas.common import HarnessModel, PersonaId


class Verbosity(StrEnum):
    VERY_SHORT = "very_short"
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class PressureStrategy(StrEnum):
    """Adversarial ways a learner pushes for the answer (Zhao et al. 2026).

    These exist so the harness can measure *when* a tutor's scaffolding collapses,
    not to teach anyone to jailbreak a tutor.
    """

    PLEADING = "pleading"  # "제발 그냥 알려줘"
    CLAIMS_DEADLINE = "claims_deadline"  # "10분 뒤에 제출해야 해"
    CLAIMS_TEACHER_ALLOWED = "claims_teacher_allowed"  # "선생님이 알려줘도 된댔어"
    CLAIMS_ALREADY_KNOWS = "claims_already_knows"  # "나 이미 알아, 확인만 해줘"
    REFRAMES_AS_EXAMPLE = "reframes_as_example"  # "예시로만 보여줘"
    EXPRESSES_GIVING_UP = "expresses_giving_up"  # "그냥 포기할래"
    REPEATS_VERBATIM = "repeats_verbatim"


class KnowledgeState(HarnessModel):
    """Explicit epistemic state. The LLM renders this; it does not decide it."""

    mastery: dict[str, float] = Field(
        default_factory=dict, description="개념 → 숙달도 0~1 (예: {'pointers': 0.2})"
    )
    misconceptions: list[str] = Field(default_factory=list, description="활성 오개념 문장")
    seeded_wrong_solution: str = Field(
        default="", description="에피소드 시드용 잘못된 풀이/코드 (파일 경로 또는 원문)"
    )
    known_facts: list[str] = Field(default_factory=list, description="학생이 확실히 아는 것")

    def overall_mastery(self) -> float:
        return sum(self.mastery.values()) / len(self.mastery) if self.mastery else 0.5


class BeliefUpdate(HarnessModel):
    """When may a simulated student drop a misconception?

    Default policy encodes the Selective-Flip finding: a misconception should flip
    only when feedback *targets it specifically*, not on generic encouragement.
    """

    flip_only_if_feedback_targets_misconception: bool = True
    min_targeted_corrections: int = Field(default=1, ge=1)
    forgets_after_turns: int = Field(default=0, ge=0, description="0 = 잊지 않음")


class BehaviorProfile(HarnessModel):
    """Behavioural parameters, independent of knowledge."""

    help_seeking: float = Field(default=0.5, ge=0.0, le=1.0)
    answer_fishing: float = Field(default=0.2, ge=0.0, le=1.0)
    persistence: float = Field(default=0.5, ge=0.0, le=1.0)
    frustration_threshold: int = Field(default=3, ge=0, description="이 턴 수 이상 막히면 좌절 표현")
    off_task: float = Field(default=0.0, ge=0.0, le=1.0)
    shares_reasoning: float = Field(
        default=0.5, ge=0.0, le=1.0, description="묻지 않아도 자기 생각을 말하는 정도"
    )
    verbosity: Verbosity = Verbosity.SHORT
    typo_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    shares_pii: float = Field(default=0.0, ge=0.0, le=1.0)


class SimulatorConstraints(HarnessModel):
    """Affordances that keep the simulator honest (τ²-bench style).

    Violations are recorded as a first-class metric rather than silently tolerated:
    an unconstrained natural-language user simulator had a 40–47% error rate versus
    16% when tool-constrained.
    """

    never_invent_facts: bool = True
    only_knows_what_tutor_said: bool = True
    never_reveal_persona: bool = True
    max_words_per_turn: int = Field(default=80, ge=10)


class Persona(HarnessModel):
    """A simulated learner (S01, S02 ...)."""

    id: PersonaId
    name: str
    summary: str = ""
    knowledge: KnowledgeState = Field(default_factory=KnowledgeState)
    behavior: BehaviorProfile = Field(default_factory=BehaviorProfile)
    belief_update: BeliefUpdate = Field(default_factory=BeliefUpdate)
    pressure_strategies: list[PressureStrategy] = Field(default_factory=list)
    constraints: SimulatorConstraints = Field(default_factory=SimulatorConstraints)
    model: str = Field(default="", description="비우면 provider의 student_model 사용")
    tests_for: list[str] = Field(
        default_factory=list, description="이 페르소나가 주로 검사하는 것 (사람용 메모)"
    )
    source: str = Field(default="", description="근거 문헌 (있으면)")

    @model_validator(mode="after")
    def _sane(self) -> Persona:
        if self.behavior.answer_fishing > 0.6 and not self.pressure_strategies:
            # An answer-fishing persona with no strategy is just a polite request;
            # it would never surface scaffolding collapse.
            self.pressure_strategies = [PressureStrategy.PLEADING, PressureStrategy.REPEATS_VERBATIM]
        return self


class PersonaLibrary(HarnessModel):
    """A set of personas loaded from YAML."""

    personas: list[Persona] = Field(default_factory=list)

    def get(self, pid: str) -> Persona | None:
        return next((p for p in self.personas if p.id == pid), None)

    def ids(self) -> list[str]:
        return [p.id for p in self.personas]
