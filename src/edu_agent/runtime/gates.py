"""Policy gates — hard constraints enforced between the model and the learner.

Borrowed shape: OpenAI Agents SDK guardrails (a typed check that trips, with the
reason carried in the result rather than parsed out of a string) and Claude Code
hooks (a policy layer that lives *outside* the model and returns allow/deny).

The important property is that a gate is checked against the **candidate**
response. A blocked response never reaches the learner; the model is asked again
with the reason attached (a Reflexion-style compact error), and after
``max_regenerations`` the runtime falls back to a safe action. Every decision is
recorded, which is what produces the per-constraint compliance rate later.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from edu_agent.runtime.leakage import LeakResult, check_leakage
from edu_agent.runtime.state import LearnerState, evaluate_condition
from edu_agent.schemas.agent import PolicyGate
from edu_agent.schemas.educational import TaskItem
from edu_agent.schemas.principles import (
    ACTION_DIRECTIVENESS,
    AgentAction,
    ConstraintKind,
    TriggerEvent,
)
from edu_agent.schemas.trace import GateDecision


@dataclass(slots=True)
class Candidate:
    """A model response about to be shown to the learner."""

    action: AgentAction
    message: str
    ladder_level: int = 0


@dataclass(slots=True)
class GateOutcome:
    """Result of running every gate against a candidate."""

    decisions: list[GateDecision] = field(default_factory=list)
    leak: LeakResult | None = None

    @property
    def blocked(self) -> list[GateDecision]:
        return [d for d in self.decisions if not d.passed]

    @property
    def passed(self) -> bool:
        return not self.blocked

    def feedback(self) -> str:
        """Compact correction instruction for the regeneration attempt."""
        if self.passed:
            return ""
        lines = ["이전 응답이 다음 규칙을 위반했습니다. 규칙을 지켜 다시 작성하세요."]
        for d in self.blocked:
            lines.append(f"- {d.reason}")
        return "\n".join(lines)


class GateRunner:
    """Evaluates the spec's policy gates against candidate responses."""

    def __init__(self, gates: list[PolicyGate], task: TaskItem | None = None) -> None:
        self.gates = gates
        self.task = task

    def check(
        self,
        candidate: Candidate,
        state: LearnerState,
        *,
        triggers: list[TriggerEvent] | None = None,
        history_actions: list[AgentAction] | None = None,
        attempt: int = 1,
    ) -> GateOutcome:
        outcome = GateOutcome()
        triggers = triggers or []
        history = history_actions or []

        for gate in self.gates:
            passed, reason = self._check_one(gate, candidate, state, triggers, history, outcome)
            outcome.decisions.append(
                GateDecision(
                    gate_id=gate.id,
                    passed=passed,
                    reason=reason,
                    constraint_kind=gate.constraint.kind.value,
                    attempt=attempt,
                )
            )
        return outcome

    # --- individual constraint kinds -------------------------------------
    def _check_one(
        self,
        gate: PolicyGate,
        cand: Candidate,
        state: LearnerState,
        triggers: list[TriggerEvent],
        history: list[AgentAction],
        outcome: GateOutcome,
    ) -> tuple[bool, str]:
        c = gate.constraint
        p = c.params

        match c.kind:
            case ConstraintKind.NEVER_ACTION:
                if cand.action.value == p.get("action"):
                    return False, c.text or f"{p['action']} 행동은 허용되지 않습니다."

            case ConstraintKind.ACTION_ONLY_AFTER_LEVEL:
                if cand.action.value == p.get("action") and cand.ladder_level < int(p.get("level", 0)):
                    return False, (
                        c.text
                        or f"{p['action']} 는 {p['level']}단계 이후에만 가능합니다 (현재 {cand.ladder_level}단계)."
                    )

            case ConstraintKind.ACTION_ONLY_WHEN:
                if cand.action.value == p.get("action") and not evaluate_condition(str(p.get("when", "")), state):
                    return False, (
                        c.text or f"{p['action']} 는 조건({p.get('when')})을 만족할 때만 가능합니다."
                    )

            case ConstraintKind.REQUIRE_ACTION_BEFORE:
                required = str(p.get("before"))
                if cand.action.value == p.get("action") and not any(a.value == required for a in history):
                    return False, c.text or f"{required} 를 먼저 수행해야 합니다."

            case ConstraintKind.MAX_ACTIONS_PER_TURN:
                # Repetition control: only a violation when the same action is used
                # back-to-back *and* has already hit its allowance. Counting across
                # the whole session alone would ban a move the ladder legitimately
                # returns to later.
                limit = max(1, int(p.get("max", 1)))
                used = sum(1 for a in history if a.value == p.get("action"))
                repeated = bool(history) and history[-1].value == p.get("action")
                if cand.action.value == p.get("action") and used >= limit and repeated:
                    return False, c.text or f"{p['action']} 를 연속으로 반복하지 않습니다."

            case ConstraintKind.MAX_DIRECTIVENESS_ON_FIRST_HELP:
                first_help = int(state.get("help_requests") or 0) <= 1
                if first_help and ACTION_DIRECTIVENESS.get(cand.action, 0) > int(p.get("rank", 0)):
                    return False, (
                        c.text or "첫 도움 요청에는 더 낮은 수준의 지원만 제공해야 합니다."
                    )

            case ConstraintKind.REQUIRE_ACTION_AFTER_TRIGGER:
                trigger = str(p.get("trigger"))
                if any(t.value == trigger for t in triggers) and cand.action.value != p.get("action"):
                    return False, c.text or f"{trigger} 상황에서는 {p['action']} 가 필요합니다."

            case ConstraintKind.NO_ANSWER_LEAKAGE_UNLESS:
                allowed = evaluate_condition(str(p.get("when", "")), state)
                if not allowed:
                    leak = check_leakage(cand.message, self.task)
                    outcome.leak = leak
                    if leak.leaked:
                        return False, (
                            (c.text or "아직 정답을 제공할 조건이 아닙니다.")
                            + f" (근거: {leak.evidence})"
                        )

            case ConstraintKind.CUSTOM:
                # Soft/free-text constraints are not gated; the judge handles them.
                return True, ""

        return True, ""


def allowed_actions(
    behaviors: list,
    state: LearnerState,
    triggers: list[TriggerEvent],
    gates: list[PolicyGate],
) -> tuple[set[AgentAction], int]:
    """Compute the action set the ladder and gates currently permit.

    Returns ``(actions, ladder_level)``. Giving the model an explicit menu is the
    ACI lesson from SWE-agent: a short, well-named command set beats a long prose
    description of what it may do.
    """
    fired = set(triggers)
    allowed: set[AgentAction] = set()
    level = 0

    for behavior in behaviors:
        if fired and not (set(behavior.triggers) & fired) and TriggerEvent.TURN_ANY not in behavior.triggers:
            continue
        allowed |= set(behavior.actions)
        for step in behavior.ladder:
            if evaluate_condition(step.when, state):
                allowed.add(step.action)
                level = max(level, step.level)
            else:
                break

    if not allowed:
        allowed = {
            AgentAction.ASK_FOR_REASONING,
            AgentAction.ASK_CLARIFYING_QUESTION,
            AgentAction.ACKNOWLEDGE_AND_ENCOURAGE,
        }

    # Remove actions a hard gate would reject outright, so the model is never
    # offered a move it cannot legally make.
    for gate in gates:
        c = gate.constraint
        if c.kind is ConstraintKind.NEVER_ACTION or (c.kind is ConstraintKind.ACTION_ONLY_AFTER_LEVEL and level < int(
            c.params.get("level", 0)
        )) or (c.kind is ConstraintKind.ACTION_ONLY_WHEN and not evaluate_condition(
            str(c.params.get("when", "")), state
        )):
            allowed.discard(AgentAction(c.params["action"]))
        elif (
            c.kind is ConstraintKind.MAX_DIRECTIVENESS_ON_FIRST_HELP
            and int(state.get("help_requests") or 0) <= 1
        ):
            rank = int(c.params.get("rank", 0))
            allowed = {a for a in allowed if ACTION_DIRECTIVENESS.get(a, 0) <= rank}

    if not allowed:
        allowed = {AgentAction.ASK_FOR_REASONING}
    return allowed, level


def safe_fallback(allowed: set[AgentAction]) -> Candidate:
    """The response used when regeneration keeps failing.

    Asking the learner to explain their thinking is the least directive move and is
    almost never the wrong thing to do — but the runtime records that it happened,
    because a tutor that keeps falling back is a tutor with a broken spec.
    """
    for action in (
        AgentAction.ASK_FOR_REASONING,
        AgentAction.ASK_METACOGNITIVE_QUESTION,
        AgentAction.ASK_CLARIFYING_QUESTION,
    ):
        if action in allowed:
            return Candidate(
                action=action,
                message="지금까지 어떻게 생각했는지 먼저 말해 줄 수 있나요? 어느 부분이 막혔는지 알면 더 잘 도울 수 있어요.",
            )
    return Candidate(
        action=next(iter(allowed)),
        message="조금 더 자세히 설명해 줄 수 있나요?",
    )
