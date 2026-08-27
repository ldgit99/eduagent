"""Patches: typed, reversible edits to the agent spec.

Every change is a data object, not a free-form rewrite. That buys three things:

* the student sees a readable diff before anything is applied;
* the same patch can be reverted exactly;
* an LLM proposing a change can only choose *from these shapes*, so it cannot
  quietly rewrite the pedagogy while claiming to tune a threshold.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from edu_agent.optimizer.diagnose import EditLayer
from edu_agent.schemas.agent import AgentSpec
from edu_agent.schemas.principles import (
    ConstraintKind,
    LadderStep,
    validate_condition,
)
from edu_agent.utils.hashing import hash_text


class PatchKind(StrEnum):
    APPEND_PROMPT_SECTION = "append_prompt_section"
    REPLACE_PROMPT_SECTION = "replace_prompt_section"
    SET_ANSWER_CONDITION = "set_answer_condition"
    SET_GATE_PARAM = "set_gate_param"
    SET_LADDER_CONDITION = "set_ladder_condition"
    INSERT_LADDER_STEP = "insert_ladder_step"
    SET_POLICY_TEXT = "set_policy_text"


@dataclass(slots=True)
class Patch:
    """One reversible edit."""

    kind: PatchKind
    layer: EditLayer
    target: str  # gate id, behavior id, section name…
    value: Any
    reason: str = ""
    diagnosis_code: str = ""
    before: Any = None  # filled in on apply, used for revert

    def describe(self) -> str:
        return f"[{self.layer.label_ko}] {_DESCRIBE[self.kind](self)}"

    def diff(self) -> str:
        before = _fmt(self.before)
        after = _fmt(self.value)
        if before == after:
            return f"  {after}"
        return f"- {before}\n+ {after}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "layer": self.layer.value,
            "target": self.target,
            "value": self.value,
            "before": self.before,
            "reason": self.reason,
            "diagnosis_code": self.diagnosis_code,
        }


def _fmt(value: Any) -> str:
    if value is None:
        return "(없음)"
    if isinstance(value, str):
        return value if len(value) <= 200 else value[:199] + "…"
    return json.dumps(value, ensure_ascii=False)


_DESCRIBE = {
    PatchKind.APPEND_PROMPT_SECTION: lambda p: f"안내문에 '{p.target}' 내용을 추가",
    PatchKind.REPLACE_PROMPT_SECTION: lambda p: f"안내문의 '{p.target}' 내용을 교체",
    PatchKind.SET_ANSWER_CONDITION: lambda p: f"정답 제공 조건을 '{p.value}' 로 변경",
    PatchKind.SET_GATE_PARAM: lambda p: f"{p.target} 규칙의 조건을 변경",
    PatchKind.SET_LADDER_CONDITION: lambda p: f"{p.target} 사다리 단계 조건을 변경",
    PatchKind.INSERT_LADDER_STEP: lambda p: f"{p.target} 사다리에 단계를 추가",
    PatchKind.SET_POLICY_TEXT: lambda p: f"{p.target} 방침 문장을 수정",
}


class PatchError(Exception):
    pass


def apply_patch(spec: AgentSpec, patch: Patch) -> AgentSpec:
    """Apply one patch in place, recording ``before`` for revert."""
    match patch.kind:
        case PatchKind.APPEND_PROMPT_SECTION:
            patch.before = spec.system_prompt
            # Duplicate detection is by *section*, not substring: the compiled
            # prompt already contains ordinary phrases like "짧게 말합니다", and a
            # substring test would reject unrelated additions that happen to reuse
            # a common sentence.
            if f"## {patch.target}" in spec.system_prompt:
                raise PatchError(f"'{patch.target}' 절이 이미 안내문에 있습니다.")
            if _section_bodies(spec.system_prompt) and str(patch.value).strip() in _section_bodies(
                spec.system_prompt
            ):
                raise PatchError("이미 같은 내용이 안내문에 있습니다.")
            spec.system_prompt = spec.system_prompt.rstrip() + f"\n\n## {patch.target}\n{patch.value}"

        case PatchKind.REPLACE_PROMPT_SECTION:
            patch.before = spec.system_prompt
            spec.system_prompt = _replace_section(spec.system_prompt, patch.target, str(patch.value))

        case PatchKind.SET_ANSWER_CONDITION:
            condition = validate_condition(str(patch.value))
            patch.before = spec.answer_condition
            spec.answer_condition = condition
            for gate in spec.gates:
                if gate.constraint.kind is ConstraintKind.NO_ANSWER_LEAKAGE_UNLESS:
                    gate.constraint.params = {**gate.constraint.params, "when": condition}
                    gate.constraint.text = f"정답은 다음 조건에서만 제공합니다: {condition}"
                    gate.message = f"아직 정답을 제공할 조건이 아닙니다 ({condition})."

        case PatchKind.SET_GATE_PARAM:
            gate = spec.gate(patch.target)
            if gate is None:
                raise PatchError(f"{patch.target} 규칙을 찾을 수 없습니다.")
            if not isinstance(patch.value, dict):
                raise PatchError("규칙 조건은 딕셔너리여야 합니다.")
            if "when" in patch.value:
                validate_condition(str(patch.value["when"]))
            patch.before = dict(gate.constraint.params)
            gate.constraint.params = {**gate.constraint.params, **patch.value}

        case PatchKind.SET_LADDER_CONDITION:
            behavior_id, level = _split_target(patch.target)
            behavior = spec.behavior(behavior_id)
            if behavior is None:
                raise PatchError(f"{behavior_id} 규칙을 찾을 수 없습니다.")
            step = next((s for s in behavior.ladder if s.level == level), None)
            if step is None:
                raise PatchError(f"{behavior_id} 에 {level}단계가 없습니다.")
            condition = validate_condition(str(patch.value))
            patch.before = step.when
            ladder = list(behavior.ladder)
            ladder[ladder.index(step)] = step.model_copy(update={"when": condition})
            behavior.ladder = ladder

        case PatchKind.INSERT_LADDER_STEP:
            behavior = spec.behavior(patch.target)
            if behavior is None:
                raise PatchError(f"{patch.target} 규칙을 찾을 수 없습니다.")
            if not isinstance(patch.value, dict):
                raise PatchError("사다리 단계는 딕셔너리여야 합니다.")
            step = LadderStep.model_validate(patch.value)
            patch.before = [s.model_dump(mode="json") for s in behavior.ladder]
            ladder = [s for s in behavior.ladder if s.level != step.level]
            ladder.append(step)
            behavior.ladder = sorted(ladder, key=lambda s: s.level)

        case PatchKind.SET_POLICY_TEXT:
            field_name = {
                "scaffolding": "scaffolding_policy",
                "feedback": "feedback_policy",
                "agency": "agency_policy",
            }.get(patch.target)
            if field_name is None:
                raise PatchError(f"알 수 없는 방침: {patch.target}")
            patch.before = getattr(spec, field_name)
            setattr(spec, field_name, str(patch.value))

    return spec


def apply_patches(spec: AgentSpec, patches: list[Patch]) -> tuple[AgentSpec, list[Patch], list[str]]:
    """Apply as many patches as possible; return what worked and what did not."""
    applied: list[Patch] = []
    errors: list[str] = []
    for patch in patches:
        try:
            apply_patch(spec, patch)
            applied.append(patch)
        except (PatchError, ValueError) as exc:
            errors.append(f"{patch.describe()}: {exc}")
    return spec, applied, errors


def revert_patch(spec: AgentSpec, patch: Patch) -> AgentSpec:
    """Undo a single patch using its recorded ``before``."""
    inverse = Patch(
        kind=patch.kind,
        layer=patch.layer,
        target=patch.target,
        value=patch.before,
        reason="revert",
    )
    if patch.kind is PatchKind.INSERT_LADDER_STEP:
        behavior = spec.behavior(patch.target)
        if behavior is not None and isinstance(patch.before, list):
            behavior.ladder = [LadderStep.model_validate(s) for s in patch.before]
        return spec
    if patch.kind in {PatchKind.APPEND_PROMPT_SECTION, PatchKind.REPLACE_PROMPT_SECTION}:
        spec.system_prompt = str(patch.before)
        return spec
    return apply_patch(spec, inverse)


def _section_bodies(prompt: str) -> set[str]:
    """Body text of every ``## heading`` section, for duplicate detection."""
    bodies: set[str] = set()
    current: list[str] = []
    for line in prompt.splitlines():
        if line.startswith("## "):
            if current:
                bodies.add("\n".join(current).strip())
            current = []
        else:
            current.append(line)
    if current:
        bodies.add("\n".join(current).strip())
    return {b for b in bodies if b}


def _replace_section(prompt: str, heading: str, body: str) -> str:
    marker = f"## {heading}"
    if marker not in prompt:
        return prompt.rstrip() + f"\n\n{marker}\n{body}"
    head, _, tail = prompt.partition(marker)
    rest = tail.split("\n## ", 1)
    remainder = f"\n## {rest[1]}" if len(rest) > 1 else ""
    return f"{head}{marker}\n{body}{remainder}"


def _split_target(target: str) -> tuple[str, int]:
    if ":" not in target:
        raise PatchError(f"대상 형식이 잘못되었습니다: {target} (예: B05:2)")
    bid, _, level = target.partition(":")
    try:
        return bid, int(level)
    except ValueError as exc:
        raise PatchError(f"단계 번호를 읽을 수 없습니다: {target}") from exc


# --- snapshots (rollback is a pointer move) -------------------------------
@dataclass(slots=True)
class Snapshot:
    version: int
    path: Path
    created_at: datetime
    note: str = ""
    spec_hash: str = ""
    overall: float | None = None
    patches: list[dict[str, Any]] = field(default_factory=list)


def snapshot_spec(dir_: Path, spec: AgentSpec, *, note: str = "", overall: float | None = None,
                  patches: list[Patch] | None = None) -> Snapshot:
    """Save a versioned copy of the spec so any change can be undone."""
    dir_.mkdir(parents=True, exist_ok=True)
    version = _next_version(dir_)
    path = dir_ / f"v{version:03d}.json"
    payload = spec.model_dump(mode="json")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    snap = Snapshot(
        version=version,
        path=path,
        created_at=datetime.now(UTC),
        note=note,
        spec_hash=hash_text(json.dumps(payload, ensure_ascii=False, sort_keys=True)),
        overall=overall,
        patches=[p.to_dict() for p in (patches or [])],
    )
    _write_index(dir_, snap)
    return snap


def _next_version(dir_: Path) -> int:
    versions = [int(p.stem[1:]) for p in dir_.glob("v*.json") if p.stem[1:].isdigit()]
    return max(versions, default=0) + 1


def _write_index(dir_: Path, snap: Snapshot) -> None:
    index = dir_ / "index.jsonl"
    with index.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(
            json.dumps(
                {
                    "version": snap.version,
                    "created_at": snap.created_at.isoformat(),
                    "note": snap.note,
                    "spec_hash": snap.spec_hash,
                    "overall": snap.overall,
                    "patches": snap.patches,
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def list_snapshots(dir_: Path) -> list[dict[str, Any]]:
    index = dir_ / "index.jsonl"
    if not index.exists():
        return []
    return [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines() if line.strip()]


def revert_to(dir_: Path, version: int) -> AgentSpec:
    """Load a snapshot — the rollback operation."""
    path = dir_ / f"v{version:03d}.json"
    if not path.exists():
        raise PatchError(f"버전 {version} 스냅샷이 없습니다.")
    return AgentSpec.model_validate(json.loads(path.read_text(encoding="utf-8")))
