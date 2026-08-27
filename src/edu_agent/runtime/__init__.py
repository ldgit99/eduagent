"""Spec-interpreting runtime (plan v2 §11).

``edu-agent run`` executes ``04_agent_spec.md`` directly — no code generation. This
is the decision that makes the harness usable by a student who has never
programmed (ADR-02), and it also means the policy-gate logic exists in exactly one
place instead of being copied into every generated project.

Turn loop::

    learner input
      → detect triggers, update learner state
      → compute the set of actions the ladder and constraints currently allow
      → call the model with the system prompt + state summary + allowed actions
      → run policy gates on the candidate response (block → regenerate → fallback)
      → emit the response and append a span to the trace
"""

from edu_agent.runtime.gates import GateOutcome, GateRunner
from edu_agent.runtime.loop import AgentRuntime, TurnResult
from edu_agent.runtime.state import LearnerState, evaluate_condition
from edu_agent.runtime.triggers import detect_triggers

__all__ = [
    "AgentRuntime",
    "GateOutcome",
    "GateRunner",
    "LearnerState",
    "TurnResult",
    "detect_triggers",
    "evaluate_condition",
]
