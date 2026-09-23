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
from edu_agent.runtime.tools import (
    MAX_CALLS_PER_TURN,
    ToolCall,
    ToolRuntime,
    parse_tool_call,
)
from edu_agent.runtime.triggers import detect_triggers
from edu_agent.schemas.agent import AgentSpec, Phase
from edu_agent.schemas.educational import TaskItem
from edu_agent.schemas.principles import AgentAction, TriggerEvent
from edu_agent.schemas.trace import (
    LearnerStateSnapshot,
    Message,
    Role,
    SessionTrace,
    ToolInvocation,
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

    @property
    def tool_calls(self) -> list[ToolInvocation]:
        return self.record.tool_calls


@dataclass(slots=True)
class Generated:
    """The outcome of one generate-check-maybe-regenerate cycle."""

    candidate: Candidate
    outcome: GateOutcome
    regenerations: int
    fallback_used: bool
    error: str
    usage: dict[str, int]
    tool_calls: list[ToolInvocation]


@dataclass(slots=True)
class AgentRuntime:
    """Executes an :class:`AgentSpec` against a live or simulated learner."""

    spec: AgentSpec
    provider: Provider
    task: TaskItem | None = None
    max_regenerations: int = MAX_REGENERATIONS
    trace: SessionTrace = field(default_factory=SessionTrace)
    tools: ToolRuntime | None = None

    state: LearnerState = field(default_factory=LearnerState)
    history: list[ChatMessage] = field(default_factory=list)
    action_history: list[AgentAction] = field(default_factory=list)
    _gates: GateRunner = field(init=False)
    _system: str = field(init=False, default="")
    _tool_block: str = field(init=False, default="")

    def __post_init__(self) -> None:
        self._gates = GateRunner(self.spec.gates, self.task)
        self._system = build_system_prompt(self.spec)
        if self.tools is None and self.spec.tools:
            self.tools = ToolRuntime(self.spec.tools, task=self.task)
        self._tool_block = self.tools.describe() if self.tools else ""
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

        generated = self._generate(learner_message, allowed, level, phase, triggers)
        candidate, outcome = generated.candidate, generated.outcome

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
            tool_calls=generated.tool_calls,
            regenerations=generated.regenerations,
            fallback_used=generated.fallback_used,
            leaked_answer=leak.leaked,
            leak_evidence=leak.evidence,
            error=generated.error,
            latency_ms=int((time.perf_counter() - started) * 1000),
            usage=generated.usage,
        )
        self.trace.turns.append(record)
        if generated.error:
            self.trace.errors.append(generated.error)

        return TurnResult(
            message=candidate.message,
            action=candidate.action,
            record=record,
            gate_outcome=outcome,
            fallback_used=generated.fallback_used,
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
    ) -> Generated:
        correction = ""
        tool_results: list[str] = []
        tool_calls: list[ToolInvocation] = []
        usage_total: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
        last_outcome = GateOutcome()
        error = ""
        attempt = 0

        # One budget covers both kinds of extra round trip — gate regenerations and
        # tool calls — so a model that alternates between them still terminates.
        for _ in range(self.max_regenerations + 1 + MAX_CALLS_PER_TURN):
            turn_prompt = build_turn_prompt(
                self.state,
                allowed,
                phase=phase,
                task=self.task,
                correction=correction,
                ladder_level=level,
                tools=self._tool_block,
                tool_results=tool_results,
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
            candidate, requested_tool = _parse_candidate(completion, allowed, level)

            if requested_tool is not None and self.tools is not None:
                if len(tool_calls) >= MAX_CALLS_PER_TURN:
                    tool_results.append(
                        "## 도구 결과\n이번 턴에는 도구를 더 쓸 수 없습니다. "
                        "지금까지의 결과로 학습자에게 할 말을 완성하세요."
                    )
                    continue
                record = self.tools.call(requested_tool, self.state)
                tool_calls.append(record)
                tool_results.append(_render_tool_result(record))
                continue

            attempt += 1
            outcome = self._gates.check(
                candidate,
                self.state,
                triggers=triggers,
                history_actions=self.action_history,
                attempt=attempt,
            )
            last_outcome = outcome
            if outcome.passed:
                return Generated(candidate, outcome, attempt - 1, False, error, usage_total,
                                 tool_calls)
            correction = outcome.feedback()
            if attempt > self.max_regenerations:
                break

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
        return Generated(fallback, final_outcome, self.max_regenerations, True, error,
                         usage_total, tool_calls)

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


def _render_tool_result(call: ToolInvocation) -> str:
    """Hand the tool's outcome back to the model — refusals included, with the reason."""
    if not call.allowed:
        return f"## 도구 결과 · {call.name}\n요청이 거부되었습니다: {call.blocked_reason}"
    body = call.output or call.error or "(결과 없음)"
    return f"## 도구 결과 · {call.name}\n{body}"


def _parse_candidate(
    completion: Completion, allowed: set[AgentAction], level: int
) -> tuple[Candidate, ToolCall | None]:
    """Read the model's structured turn, degrading gracefully if it wrote prose."""
    try:
        data = completion.parse_json()
    except ProviderError:
        data = None

    if not isinstance(data, dict):
        fallback = Candidate(
            action=_default_action(allowed), message=completion.text, ladder_level=level
        )
        return fallback, None

    message = str(data.get("message") or completion.text).strip()
    raw_action = str(data.get("action") or "").strip()
    try:
        action = AgentAction(raw_action)
    except ValueError:
        action = _default_action(allowed)
    return Candidate(action=action, message=message, ladder_level=level), parse_tool_call(
        data.get("tool_call")
    )


def _default_action(allowed: set[AgentAction]) -> AgentAction:
    for a in (AgentAction.ASK_FOR_REASONING, AgentAction.PROVIDE_DIRECTIONAL_HINT):
        if a in allowed:
            return a
    return next(iter(sorted(allowed, key=lambda x: x.value))) if allowed else AgentAction.CUSTOM
