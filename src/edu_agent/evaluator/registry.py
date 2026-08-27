"""Registry mapping metric names → dimensions and check implementations.

Inspect AI's ``@scorer`` registry is the model here: a check is a plain function
with a known signature, registered by name, so the spec can refer to it as a string
and a project can add its own later without touching the evaluator.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from edu_agent.schemas.common import CheckType
from edu_agent.schemas.evaluation import Dimension

#: metric name → dimension it contributes to.
METRIC_DIMENSIONS: dict[str, Dimension] = {
    # deterministic
    "answer_leakage": Dimension.PRINCIPLE_FIDELITY,
    "reasoning_elicited_before_hint": Dimension.LEARNER_AGENCY,
    "ladder_progression": Dimension.ADAPTIVE_SUPPORT,
    "pressure_capitulation": Dimension.SAFETY_ETHICS,
    "pii_handling": Dimension.SAFETY_ETHICS,
    "off_task_redirect": Dimension.SAFETY_ETHICS,
    "reflection_after_completion": Dimension.LEARNER_AGENCY,
    "response_length": Dimension.INTERACTION_QUALITY,
    "question_present": Dimension.LEARNER_AGENCY,
    "action_declaration_match": Dimension.PEDAGOGICAL_FIDELITY,
    "gate_compliance": Dimension.PRINCIPLE_FIDELITY,
    "collapse_onset": Dimension.PRINCIPLE_FIDELITY,
    # judge
    "no_unproductive_withholding": Dimension.ADAPTIVE_SUPPORT,
    "misconception_handling": Dimension.INTERACTION_QUALITY,
    "actionability": Dimension.FEEDBACK_QUALITY,
    "process_feedback_present": Dimension.FEEDBACK_QUALITY,
    "learner_agency_preserved": Dimension.LEARNER_AGENCY,
    "goal_alignment": Dimension.GOAL_ALIGNMENT,
    "mistake_identification": Dimension.PEDAGOGICAL_FIDELITY,
    "guidance_quality": Dimension.PEDAGOGICAL_FIDELITY,
    "coherence": Dimension.INTERACTION_QUALITY,
    "tutor_tone": Dimension.INTERACTION_QUALITY,
    "adaptation": Dimension.ADAPTIVE_SUPPORT,
    "pedagogical_safety": Dimension.SAFETY_ETHICS,
}

DETERMINISTIC_METRICS: frozenset[str] = frozenset(
    m for m, _ in METRIC_DIMENSIONS.items()
) - frozenset(
    {
        "no_unproductive_withholding",
        "misconception_handling",
        "actionability",
        "process_feedback_present",
        "learner_agency_preserved",
        "goal_alignment",
        "mistake_identification",
        "guidance_quality",
        "coherence",
        "tutor_tone",
        "adaptation",
        "pedagogical_safety",
    }
)


def dimension_for_metric(metric: str) -> Dimension:
    """Best-effort mapping; unknown metrics land in principle fidelity."""
    if metric in METRIC_DIMENSIONS:
        return METRIC_DIMENSIONS[metric]
    for value in Dimension:
        if metric == value.value:
            return value
    return Dimension.PRINCIPLE_FIDELITY


def check_type_for_metric(metric: str) -> CheckType:
    return CheckType.DETERMINISTIC if metric in DETERMINISTIC_METRICS else CheckType.LLM_JUDGE


@dataclass(frozen=True, slots=True)
class RegisteredCheck:
    name: str
    dimension: Dimension
    fn: Callable
    description: str = ""


_REGISTRY: dict[str, RegisteredCheck] = {}


def register_check(name: str, dimension: Dimension, description: str = ""):
    """Decorator registering a deterministic check by name."""

    def wrap(fn: Callable) -> Callable:
        _REGISTRY[name] = RegisteredCheck(name=name, dimension=dimension, fn=fn, description=description)
        METRIC_DIMENSIONS.setdefault(name, dimension)
        return fn

    return wrap


def get_check(name: str) -> RegisteredCheck | None:
    return _REGISTRY.get(name)


def registered_checks() -> dict[str, RegisteredCheck]:
    return dict(_REGISTRY)
