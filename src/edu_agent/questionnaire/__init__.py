"""Interactive questionnaires (plan v2 §6, §7, §8).

Shared workflow for all three: ask a few questions → structure the answers →
show a summary → confirm/edit/add → save. Every step is resumable, because this
gets written across several sittings, not in one.
"""

from edu_agent.questionnaire.educational import run_educational
from edu_agent.questionnaire.principles import run_principles
from edu_agent.questionnaire.technical import run_technical

__all__ = ["run_educational", "run_principles", "run_technical"]
