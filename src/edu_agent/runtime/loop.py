"""The turn loop.

Kept deliberately small (the mini-swe-agent lesson): one function you can read top
to bottom, with the interesting behaviour pushed into ``state``, ``gates`` and
``triggers``. The agent is a stateless reducer — ``fn(state, learner_message) ->
(state, response)`` — which makes replay, testing and tracing straightforward.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from edu_agent.providers.base import ChatMessage, Completion, Provider, ProviderError
from edu_agent.runtime.gates import (
    Candidate,
    GateOutcome,
    GateRunner,
    allowed_actions,
    safe_fallback,
)
from edu_agent.runtime.leakage import check_leakage
from edu_agent.runtime.prompt import (
    TURN_SCHEMA,
    build_system_prompt,
    build_turn_prompt,
)
from edu_agent.runtime.state import LearnerState, apply_triggers
from edu_agent.runtime.triggers import detect_triggers
from edu_agent.schemas.agent import AgentSpec, Phase
from edu_agent.schemas.educational import TaskItem
from edu_agent.schemas.principles import AgentAction, TriggerEvent
from edu_agent.schemas.trace import (
    LearnerStateSnapshot,
    Message,
    Role,
    SessionTrace,
    TurnRecord,
)

MAX_REGENERATIONS = 2


@dataclass(slots=True)
class TurnResult:
    """What the caller (CLI chat, simulator) needs after one turn."""

    message: str
    action: AgentAction
    record: TurnRecord
    gate_outcome: GateOutcome
    fallback_used: bool = False


@dataclass(slots=True)
class AgentRuntime:
    """Executes an :class:`AgentSpec` against a live or simulated learner."""

    spec: AgentSpec
    provider: Provider
    task: TaskItem | None = None
    max_regenerations: int = MAX_REGENERATIONS
    trace: SessionTrace = field(default_factory=SessionTrace)

    state: LearnerState = field(default_factory=LearnerState)
    history: list[ChatMessage] = field(default_factory=list)
    action_history: list[AgentAction] = field(default_factory=list)
    _gates: GateRunner = field(init=False)
    _system: str = field(init=False, default="")

    def __post_init__(self) -> None:
        self._gates = GateRunner(self.spec.gates, self.task)
        self._system = build_system_prompt(self.spec)
        self.trace.model = getattr(self.provider, "model", "")
        if self.task is not None:
            self.trace.task_id = self.task.id

    # --- public API -------------------------------------------------------
    def turn(self, learner_message: str, *, previous_correct: bool | None = None) -> TurnResult:
        """Process one learner utterance and return the tutor's reply."""
        started = time.perf_counter()
        turn_index = len(self.trace.turns)
        state_before = self.state.snapshot()

        triggers = detect_triggers(
            learner_message,
            previous_correct=previous_correct,
            first_turn=turn_index == 0,
        )
        apply_triggers(self.state, triggers, self.spec.state_variables or None)

        allowed, level = allowed_actions(self.spec.behaviors, self.state, triggers, self.spec.gates)
        phase = self._current_phase()

        candidate, outcome, regenerations, fallback, error, usage = self._generate(
            learner_message, allowed, level, phase, triggers
        )

        self.history.append(ChatMessage("user", learner_message))
        self.history.append(ChatMessage("assistant", candidate.message))
        self.action_history.append(candidate.action)

        leak = outcome.leak or check_leakage(candidate.message, self.task)
        record = TurnRecord(
            turn_index=turn_index,
            learner_message=learner_message,
            tutor_message=candidate.message,
            triggers=triggers,
            declared_action=candidate.action,
            ladder_level=level,
            state_before=LearnerStateSnapshot(values=state_before),
            state_after=LearnerStateSnapshot(values=self.state.snapshot()),
            gates=outcome.decisions,
            regenerations=regenerations,
            fallback_used=fallback,
            leaked_answer=leak.leaked,
            leak_evidence=leak.evidence,
            error=error,
            latency_ms=int((time.perf_counter() - started) * 1000),
            usage=usage,
        )
        self.trace.turns.append(record)
        if error:
            self.trace.errors.append(error)

        return TurnResult(
            message=candidate.message,
            action=candidate.action,
            record=record,
            gate_outcome=outcome,
            fallback_used=fallback,
        )

    def messages(self) -> list[Message]:
        out = [Message(role=Role.SYSTEM, content=self._system)]
        for m in self.history:
            out.append(Message(role=Role(m.role), content=m.content))
        return out

    def system_prompt(self) -> str:
        return self._system

    # --- internals --------------------------------------------------------
    def _generate(
        self,
        learner_message: str,
        allowed: set[AgentAction],
        level: int,
        phase: Phase | None,
        triggers: list[TriggerEvent],
    ) -> tuple[Candidate, GateOutcome, int, bool, str, dict[str, int]]:
        correction = ""
        usage_total: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
        last_outcome = GateOutcome()
        error = ""

        for attempt in range(1, self.max_regenerations + 2):
            turn_prompt = build_turn_prompt(
                self.state,
                allowed,
                phase=phase,
                task=self.task,
                correction=correction,
                ladder_level=level,
            )
            messages = [
                ChatMessage("system", self._system),
                *self.history,
                ChatMessage("user", f"{learner_message}\n\n{turn_prompt}"),
            ]
            try:
                completion = self.provider.complete(messages, response_schema=TURN_SCHEMA)
            except ProviderError as exc:
                error = str(exc)
                break

            _accumulate(usage_total, completion)
            candidate = _parse_candidate(completion, allowed, level)
            outcome = self._gates.check(
                candidate,
                self.state,
                triggers=triggers,
                history_actions=self.action_history,
                attempt=attempt,
            )
            last_outcome = outcome
            if outcome.passed:
                return candidate, outcome, attempt - 1, False, error, usage_total
            correction = outcome.feedback()

        fallback = safe_fallback(allowed)
        final_outcome = self._gates.check(
            fallback,
            self.state,
            triggers=triggers,
            history_actions=self.action_history,
            attempt=self.max_regenerations + 2,
        )
        # Keep the record of *why* we fell back, not just the clean final check.
        final_outcome.decisions = last_outcome.decisions + final_outcome.decisions
        return fallback, final_outcome, self.max_regenerations, True, error, usage_total

    def _current_phase(self) -> Phase | None:
        from edu_agent.runtime.state import evaluate_condition

        active: Phase | None = None
        for phase in self.spec.phases:
            if phase.enter_when and not evaluate_condition(phase.enter_when, self.state):
                continue
            if phase.exit_when and evaluate_condition(phase.exit_when, self.state):
                continue
            active = phase
        return active or (self.spec.phases[0] if self.spec.phases else None)


def _accumulate(total: dict[str, int], completion: Completion) -> None:
    total["input_tokens"] += completion.usage.input_tokens
    total["output_tokens"] += completion.usage.output_tokens


def _parse_candidate(completion: Completion, allowed: set[AgentAction], level: int) -> Candidate:
    """Read the model's structured turn, degrading gracefully if it wrote prose."""
    try:
        data = completion.parse_json()
    except ProviderError:
        return Candidate(action=_default_action(allowed), message=completion.text, ladder_level=level)

    if not isinstance(data, dict):
        return Candidate(action=_default_action(allowed), message=completion.text, ladder_level=level)

    message = str(data.get("message") or completion.text).strip()
    raw_action = str(data.get("action") or "").strip()
    try:
        action = AgentAction(raw_action)
    except ValueError:
        action = _default_action(allowed)
    return Candidate(action=action, message=message, ladder_level=level)


def _default_action(allowed: set[AgentAction]) -> AgentAction:
    for a in (AgentAction.ASK_FOR_REASONING, AgentAction.PROVIDE_DIRECTIONAL_HINT):
        if a in allowed:
            return a
    return next(iter(sorted(allowed, key=lambda x: x.value))) if allowed else AgentAction.CUSTOM
