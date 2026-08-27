"""Loading the design-principle library and instantiating principles from it.

The library is a *starting point with citations*, never a default that slips into a
project unnoticed: :func:`to_principle` always returns ``confirmed=False`` so the
student has to look at the generated rules and say yes.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field

from edu_agent.schemas.common import HarnessModel, IdPrefix, make_id, next_id
from edu_agent.schemas.evaluation import Dimension
from edu_agent.schemas.principles import (
    BehaviorRule,
    Constraint,
    DesignGuideline,
    DesignPrinciple,
    EvaluationCriterion,
    StatementType,
)

_LIB_DIR = Path(__file__).parent / "library"


class LibraryCriterion(HarnessModel):
    statement: str
    check: str = "llm_judge"
    metric: str = ""
    dimension: str = Dimension.PRINCIPLE_FIDELITY.value


class LibraryRule(HarnessModel):
    name: str
    triggers: list[str] = Field(default_factory=list)
    ladder: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    constraints: list[dict[str, Any]] = Field(default_factory=list)
    criteria: list[LibraryCriterion] = Field(default_factory=list)


class LibraryEntry(HarnessModel):
    """One entry in the library — a principle plus the evidence for it."""

    library_id: str
    name: str
    title: str
    description: str = ""
    statement_type: StatementType = StatementType.BEHAVIORAL
    why_it_matters: str = ""
    sources: list[str] = Field(default_factory=list, min_length=1)
    guidelines: list[str] = Field(default_factory=list)
    required_behaviors: list[str] = Field(default_factory=list)
    prohibited_behaviors: list[str] = Field(default_factory=list)
    rules: list[LibraryRule] = Field(default_factory=list)

    @property
    def short(self) -> str:
        first = self.description.strip().split("\n")[0]
        return first or self.title


@functools.lru_cache(maxsize=1)
def load_library() -> list[LibraryEntry]:
    """Load every ``*.yaml`` under ``principles/library``."""
    entries: list[LibraryEntry] = []
    for path in sorted(_LIB_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for raw in data.get("principles", []):
            entries.append(LibraryEntry.model_validate(raw))
    return entries


def library_entries() -> list[LibraryEntry]:
    return load_library()


def find_entry(library_id: str) -> LibraryEntry | None:
    return next((e for e in load_library() if e.library_id == library_id), None)


def to_principle(entry: LibraryEntry, used_ids: set[str]) -> tuple[DesignPrinciple, list[EvaluationCriterion]]:
    """Instantiate a library entry as a project principle with fresh IDs.

    ``used_ids`` is mutated so several entries can be added in one pass without
    colliding. Returned principles are **unconfirmed** on purpose.
    """
    pid = next_id(used_ids, IdPrefix.PRINCIPLE)
    used_ids.add(pid)

    guidelines: list[DesignGuideline] = []
    for text in entry.guidelines:
        gid = next_id(used_ids, IdPrefix.GUIDELINE)
        used_ids.add(gid)
        guidelines.append(DesignGuideline(id=gid, text=text))

    rules: list[BehaviorRule] = []
    criteria: list[EvaluationCriterion] = []
    for lib_rule in entry.rules:
        bid = next_id(used_ids, IdPrefix.BEHAVIOR)
        used_ids.add(bid)

        rule_criteria: list[str] = []
        for lib_crit in lib_rule.criteria:
            eid = next_id(used_ids, IdPrefix.CRITERION)
            used_ids.add(eid)
            criteria.append(
                EvaluationCriterion(
                    id=eid,
                    statement=lib_crit.statement,
                    check=lib_crit.check,  # type: ignore[arg-type]
                    metric=lib_crit.metric or lib_crit.dimension,
                    principle_ids=[pid],
                    behavior_ids=[bid],
                )
            )
            rule_criteria.append(eid)

        rules.append(
            BehaviorRule(
                id=bid,
                name=lib_rule.name,
                triggers=lib_rule.triggers,  # type: ignore[arg-type]
                ladder=lib_rule.ladder,  # type: ignore[arg-type]
                actions=lib_rule.actions,  # type: ignore[arg-type]
                constraints=[Constraint.model_validate(c) for c in lib_rule.constraints],
                evaluation=rule_criteria,
                guideline_ids=[g.id for g in guidelines],
            )
        )

    principle = DesignPrinciple(
        id=pid,
        name=entry.name,
        title=entry.title,
        description=entry.description.strip(),
        statement_type=entry.statement_type,
        basis=list(entry.sources),
        library_id=entry.library_id,
        guidelines=guidelines,
        required_behaviors=list(entry.required_behaviors),
        prohibited_behaviors=list(entry.prohibited_behaviors),
        rules=rules,
        confirmed=False,
    )
    return principle, criteria


def criterion_dimension(entry_metric: str) -> Dimension:
    """Map a library metric name to an evaluation dimension."""
    from edu_agent.evaluator.registry import dimension_for_metric

    return dimension_for_metric(entry_metric)


__all__ = [
    "LibraryEntry",
    "LibraryRule",
    "find_entry",
    "library_entries",
    "load_library",
    "make_id",
    "to_principle",
]
