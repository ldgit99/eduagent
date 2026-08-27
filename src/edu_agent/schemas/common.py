"""Shared building blocks for all document schemas.

Design notes (plan v2 §5, §7)
-----------------------------
* **Stable identifiers.** Every traceable artefact gets a short ID (``P02``, ``E07``).
  IDs are assigned once and never renumbered so the traceability chain
  ``P → G → B → R → E → T`` survives edits.
* **Document metadata** lives in the YAML frontmatter. ``content_hash`` lets
  ``edu-agent review`` detect that a human edited the rendered body by hand (drift).
* **Lenient extras.** Models ignore unknown keys so a newer harness can read older
  files and vice-versa.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from edu_agent._version import SCHEMA_VERSION, __version__


class IdPrefix(StrEnum):
    """Prefix vocabulary for traceable IDs."""

    PRINCIPLE = "P"
    GUIDELINE = "G"
    BEHAVIOR = "B"
    RULE = "R"  # runtime policy gate / interaction rule
    CRITERION = "E"
    SCENARIO = "T"
    OBJECTIVE = "O"
    ACTIVITY = "A"
    PERSONA = "S"


_ID_RE = re.compile(r"^(?P<prefix>[A-Z])(?P<num>\d{2,3})$")


def make_id(prefix: IdPrefix | str, number: int) -> str:
    """Build an ID such as ``P01``; three digits are used from 100 upwards."""
    if number < 1:
        raise ValueError("ID numbers start at 1")
    p = prefix.value if isinstance(prefix, IdPrefix) else prefix
    return f"{p}{number:02d}"


def parse_id(value: str) -> tuple[str, int]:
    match = _ID_RE.match(value)
    if not match:
        raise ValueError(f"invalid id {value!r}: expected e.g. 'P01'")
    return match.group("prefix"), int(match.group("num"))


def validate_id(value: str, prefix: IdPrefix | None = None) -> str:
    """Validate an ID string, optionally checking the expected prefix."""
    got, _ = parse_id(value)
    if prefix is not None and got != prefix.value:
        raise ValueError(f"id {value!r} must start with {prefix.value!r}")
    return value


def next_id(existing: list[str] | set[str], prefix: IdPrefix) -> str:
    """Return the next free ID for ``prefix`` given the IDs already in use."""
    used = {parse_id(i)[1] for i in existing if i and parse_id(i)[0] == prefix.value}
    n = 1
    while n in used:
        n += 1
    return make_id(prefix, n)


def _checker(prefix: IdPrefix):
    def _check(value: str) -> str:
        return validate_id(value, prefix)

    return _check


# Concrete annotated aliases (preferred over a factory call in annotation position:
# they type-check cleanly and work with `from __future__ import annotations`).
PrincipleId = Annotated[str, AfterValidator(_checker(IdPrefix.PRINCIPLE))]
GuidelineId = Annotated[str, AfterValidator(_checker(IdPrefix.GUIDELINE))]
BehaviorId = Annotated[str, AfterValidator(_checker(IdPrefix.BEHAVIOR))]
RuleId = Annotated[str, AfterValidator(_checker(IdPrefix.RULE))]
CriterionId = Annotated[str, AfterValidator(_checker(IdPrefix.CRITERION))]
ScenarioId = Annotated[str, AfterValidator(_checker(IdPrefix.SCENARIO))]
ObjectiveId = Annotated[str, AfterValidator(_checker(IdPrefix.OBJECTIVE))]
ActivityId = Annotated[str, AfterValidator(_checker(IdPrefix.ACTIVITY))]
PersonaId = Annotated[str, AfterValidator(_checker(IdPrefix.PERSONA))]


class DocumentStatus(StrEnum):
    """Lifecycle of a project document (plan v2 §5.2)."""

    DRAFT = "draft"
    CONFIRMED = "confirmed"
    NEEDS_SYNC = "needs_sync"  # body edited by hand; structured data may be stale
    COMPILED = "compiled"  # 04 only
    STALE = "stale"  # 04 only: an input document changed after compiling


class CheckType(StrEnum):
    """How an evaluation criterion is verified (plan v2 §14)."""

    DETERMINISTIC = "deterministic"
    LLM_JUDGE = "llm_judge"
    HUMAN = "human"


class Strength(StrEnum):
    """Pedagogical instruction following: hard constraints vs soft guidance (§4.2)."""

    HARD = "hard"  # enforced by a runtime policy gate, deterministically checked
    SOFT = "soft"  # goes into the system prompt, judged by an LLM


class DocumentMeta(BaseModel):
    """Frontmatter metadata shared by all four documents."""

    model_config = ConfigDict(extra="ignore")

    schema_name: str = Field(description="educational_design|design_principles|technical_spec|agent_spec")
    schema_version: int = SCHEMA_VERSION
    harness_version: str = __version__
    status: DocumentStatus = DocumentStatus.DRAFT
    language: str = Field(default="ko")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str | None = Field(
        default=None, description="SHA-256 of the rendered body at save time (drift detection)"
    )
    #: 04 only: hashes of the three input documents at compile time.
    input_hashes: dict[str, str] = Field(default_factory=dict)

    @field_validator("language")
    @classmethod
    def _lang(cls, v: str) -> str:
        v = v.lower()
        if v not in {"ko", "en"}:
            raise ValueError("language must be 'ko' or 'en'")
        return v

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC)


class HarnessModel(BaseModel):
    """Base for nested models: tolerant of unknown keys, validates on assignment."""

    model_config = ConfigDict(extra="ignore", validate_assignment=True, str_strip_whitespace=True)


class DocumentModel(HarnessModel):
    """Base for the four root document models."""

    #: ClassVar, not a field: subclasses set this to the schema name they represent.
    SCHEMA_NAME: ClassVar[str] = ""

    meta: DocumentMeta

    @classmethod
    def new(cls, language: str = "ko", **data: Any) -> Self:
        meta = DocumentMeta(schema_name=cls.SCHEMA_NAME, language=language)
        return cls(meta=meta, **data)

    def missing_required(self) -> list[str]:
        """Dotted paths of compile-blocking fields that are still empty."""
        return []


class Note(HarnessModel):
    """Free-form annotation attached to a structured item."""

    text: str
    source: str | None = None
