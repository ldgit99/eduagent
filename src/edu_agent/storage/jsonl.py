"""JSONL persistence.

A *run* is one invocation of ``run`` or ``test``. Its directory holds one JSONL
file per conversation plus a ``run.json`` manifest::

    .edu-agent/runs/<run_id>/
        run.json
        s_ab12….jsonl

Storing the raw sessions — not just the scores — is what makes τ²-bench's
``--regrade`` possible: ``edu-agent test --regrade <run_id>`` re-scores stored
transcripts without spending a single token on the tutor again. That matters for a
class where the model budget is the real constraint.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from edu_agent.schemas.trace import SessionTrace, Span


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return path


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def append_span(path: Path, span: Span) -> None:
    append_jsonl(path, span.model_dump(mode="json"))


@dataclass(slots=True)
class RunPaths:
    """Where one run's artefacts live."""

    root: Path
    run_id: str

    @property
    def dir(self) -> Path:
        return self.root / self.run_id

    @property
    def manifest(self) -> Path:
        return self.dir / "run.json"

    def session(self, session_id: str) -> Path:
        return self.dir / f"{session_id}.jsonl"

    @property
    def report(self) -> Path:
        return self.dir / "evaluation.json"

    def ensure(self) -> RunPaths:
        self.dir.mkdir(parents=True, exist_ok=True)
        return self


def new_run_id(prefix: str = "run") -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"


def save_session(paths: RunPaths, trace: SessionTrace) -> Path:
    """Write one conversation as JSONL: a session span then one span per turn."""
    paths.ensure()
    trace.ended_at = trace.ended_at or datetime.now(UTC)
    rows: list[dict[str, Any]] = []

    session_span = Span(
        trace_id=trace.session_id,
        span_id=trace.session_id,
        name="invoke_agent",  # type: ignore[arg-type]
        started_at=trace.started_at,
        ended_at=trace.ended_at,
        attributes={
            **Span.gen_ai_attrs("edu-agent", trace.model),
            "edu_agent.session_id": trace.session_id,
            "edu_agent.run_id": trace.run_id,
            "edu_agent.scenario_id": trace.scenario_id,
            "edu_agent.persona_id": trace.persona_id,
            "edu_agent.task_id": trace.task_id,
            "edu_agent.seed": trace.seed,
            "edu_agent.spec_hash": trace.spec_hash,
            "edu_agent.student_model": trace.student_model,
            "edu_agent.errors": trace.errors,
            "edu_agent.simulator_violations": trace.simulator_violations,
        },
    )
    rows.append(session_span.model_dump(mode="json"))

    for record in trace.turns:
        rows.append(
            Span(
                trace_id=trace.session_id,
                parent_id=trace.session_id,
                name="turn",  # type: ignore[arg-type]
                attributes=Span.gen_ai_attrs("edu-agent", trace.model, record.usage),
                turn=record,
            ).model_dump(mode="json")
        )
    return write_jsonl(paths.session(trace.session_id), rows)


def load_session(path: Path) -> SessionTrace:
    """Rebuild a :class:`SessionTrace` from a JSONL file."""
    trace = SessionTrace(session_id=path.stem)
    for row in read_jsonl(path):
        span = Span.model_validate(row)
        if span.name == "invoke_agent":
            attrs = span.attributes
            trace.session_id = str(attrs.get("edu_agent.session_id", trace.session_id))
            trace.run_id = str(attrs.get("edu_agent.run_id", ""))
            trace.scenario_id = str(attrs.get("edu_agent.scenario_id", ""))
            trace.persona_id = str(attrs.get("edu_agent.persona_id", ""))
            trace.task_id = str(attrs.get("edu_agent.task_id", ""))
            trace.seed = int(attrs.get("edu_agent.seed", 0) or 0)
            trace.spec_hash = str(attrs.get("edu_agent.spec_hash", ""))
            trace.model = str(attrs.get("gen_ai.request.model", ""))
            trace.student_model = str(attrs.get("edu_agent.student_model", ""))
            trace.errors = list(attrs.get("edu_agent.errors", []) or [])
            trace.simulator_violations = list(attrs.get("edu_agent.simulator_violations", []) or [])
            trace.started_at = span.started_at
            trace.ended_at = span.ended_at
        elif span.turn is not None:
            trace.turns.append(span.turn)
    trace.turns.sort(key=lambda t: t.turn_index)
    return trace


def load_run(paths: RunPaths) -> list[SessionTrace]:
    """Load every session in a run, for ``--regrade``."""
    if not paths.dir.exists():
        return []
    return [load_session(p) for p in sorted(paths.dir.glob("*.jsonl"))]


def save_manifest(paths: RunPaths, data: dict[str, Any]) -> Path:
    paths.ensure()
    paths.manifest.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8", newline="\n"
    )
    return paths.manifest


def load_manifest(paths: RunPaths) -> dict[str, Any]:
    if not paths.manifest.exists():
        return {}
    return json.loads(paths.manifest.read_text(encoding="utf-8"))


def list_runs(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted((p.name for p in root.iterdir() if p.is_dir()), reverse=True)


def latest_run(root: Path) -> str | None:
    runs = list_runs(root)
    return runs[0] if runs else None
