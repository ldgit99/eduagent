"""Trace schema (plan v2 §3, ADR-11).

Traces are JSONL spans whose attribute keys follow the OpenTelemetry **GenAI
semantic conventions** (``gen_ai.*``) even though we do not depend on the OTel SDK:
those conventions are still marked *Development* and rename things between
releases, so we keep the key names compatible and convert on demand.

A run produces one file per session::

    .edu-agent/traces/<run_id>/<session_id>.jsonl

Each line is one :class:`Span`. The evaluator reads these files; nothing else in
the harness needs the raw model payloads.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from edu_agent.schemas.common import HarnessModel
from edu_agent.schemas.principles import AgentAction, TriggerEvent


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:16]}"


def now() -> datetime:
    return datetime.now(UTC)


class SpanKind(StrEnum):
    """Span names follow OTel GenAI: ``invoke_agent`` → ``chat`` → ``execute_tool``."""

    SESSION = "invoke_agent"
    CHAT = "chat"
    TOOL = "execute_tool"
    GATE = "policy_gate"  # harness-specific
    TURN = "turn"  # harness-specific
    STUDENT = "simulated_student"  # harness-specific


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(HarnessModel):
    """OTel GenAI message shape: ``{role, parts:[{type, ...}]}`` flattened to text."""

    role: Role
    content: str
    redacted: bool = False


class GateDecision(HarnessModel):
    """The result of evaluating one policy gate against a candidate response."""

    gate_id: str
    passed: bool
    reason: str = ""
    constraint_kind: str = ""
    attempt: int = Field(default=1, ge=1, description="몇 번째 생성 시도에서의 판정인지")


class LearnerStateSnapshot(HarnessModel):
    """Learner-state variables at the moment the turn was produced."""

    values: dict[str, int | bool] = Field(default_factory=dict)

    def get(self, name: str, default: int | bool = 0) -> int | bool:
        return self.values.get(name, default)


class TurnRecord(HarnessModel):
    """Everything the evaluator needs about one tutor turn.

    ``declared_action`` is what the model said it was doing (Bridge: the *decision*
    drives quality, so we make the model commit to one) and ``observed_action`` is
    what an independent classifier read off the text. Disagreement between the two
    is itself a signal.
    """

    turn_index: int = Field(ge=0)
    learner_message: str = ""
    tutor_message: str = ""
    triggers: list[TriggerEvent] = Field(default_factory=list)
    declared_action: AgentAction | None = None
    observed_action: AgentAction | None = None
    ladder_level: int = 0
    state_before: LearnerStateSnapshot = Field(default_factory=LearnerStateSnapshot)
    state_after: LearnerStateSnapshot = Field(default_factory=LearnerStateSnapshot)
    gates: list[GateDecision] = Field(default_factory=list)
    regenerations: int = Field(default=0, ge=0)
    fallback_used: bool = False
    leaked_answer: bool = False
    leak_evidence: str = ""
    error: str = ""
    latency_ms: int = 0
    usage: dict[str, int] = Field(default_factory=dict)

    @property
    def blocked_gates(self) -> list[GateDecision]:
        return [g for g in self.gates if not g.passed]


class Span(HarnessModel):
    """One JSONL line. Convertible to OTLP-JSON by renaming a few keys."""

    trace_id: str = Field(default_factory=lambda: new_id())
    span_id: str = Field(default_factory=lambda: new_id())
    parent_id: str | None = None
    name: SpanKind = SpanKind.TURN
    started_at: datetime = Field(default_factory=now)
    ended_at: datetime | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    messages: list[Message] = Field(default_factory=list)
    turn: TurnRecord | None = None

    @staticmethod
    def gen_ai_attrs(
        provider: str, model: str, usage: dict[str, int] | None = None, **extra: Any
    ) -> dict[str, Any]:
        """Build OTel GenAI attributes (``gen_ai.provider.name`` since semconv 1.37)."""
        attrs: dict[str, Any] = {
            "gen_ai.provider.name": provider,
            "gen_ai.request.model": model,
            "gen_ai.operation.name": "chat",
        }
        if usage:
            if "input_tokens" in usage:
                attrs["gen_ai.usage.input_tokens"] = usage["input_tokens"]
            if "output_tokens" in usage:
                attrs["gen_ai.usage.output_tokens"] = usage["output_tokens"]
        attrs.update(extra)
        return attrs


class SessionTrace(HarnessModel):
    """An in-memory view of one conversation (the evaluator's unit of analysis)."""

    session_id: str = Field(default_factory=lambda: new_id("s_"))
    run_id: str = ""
    scenario_id: str = ""
    persona_id: str = ""
    task_id: str = ""
    seed: int = 0
    started_at: datetime = Field(default_factory=now)
    ended_at: datetime | None = None
    turns: list[TurnRecord] = Field(default_factory=list)
    spec_hash: str = ""
    model: str = ""
    student_model: str = ""
    errors: list[str] = Field(default_factory=list)
    simulator_violations: list[str] = Field(default_factory=list)

    # --- derived signals used all over the evaluator ---------------------
    @property
    def n_turns(self) -> int:
        return len(self.turns)

    def first_leak_turn(self) -> int | None:
        return next((t.turn_index for t in self.turns if t.leaked_answer), None)

    def collapse_onset(self) -> int | None:
        """First turn where a hard gate was violated (Shao et al. 2026)."""
        return next((t.turn_index for t in self.turns if t.blocked_gates), None)

    def total_regenerations(self) -> int:
        return sum(t.regenerations for t in self.turns)

    def actions(self) -> list[AgentAction]:
        return [t.observed_action or t.declared_action for t in self.turns if (t.observed_action or t.declared_action)]  # type: ignore[misc]
