"""Exporting a FastAPI service.

Same tree and the same policy files as the CLI export — only the entry point
differs (:mod:`edu_agent.builder.common` writes the rest). The generated service
keeps one :class:`AgentRuntime` per browser session and saves the conversation as
JSONL, so a deployed agent produces the same traces ``edu-agent test --regrade``
already knows how to read.

What this target deliberately does *not* do: authentication, a database, or user
accounts. Plan v2 §21 keeps those out of scope, and an exported class project that
pretends to have them would be worse than one that says it does not.

The files live in ``templates/export/fastapi/``.
"""

from __future__ import annotations

from pathlib import Path

from edu_agent.builder.common import HARNESS_REQUIREMENT, gate_summary, render, write_common
from edu_agent.schemas.agent import AgentSpec


def export_fastapi(project, spec: AgentSpec, destination: Path) -> Path:
    """Write a standalone FastAPI project to ``destination``."""
    write_common(project, spec, destination)

    context = {
        "name": project.config.name,
        "slug": project.config.name.replace("-", "_"),
        "role": spec.agent_role or "교육용 AI 에이전트",
        "gates": gate_summary(spec),
        "harness": HARNESS_REQUIREMENT,
        "lang": project.config.language,
    }
    for template, target in (
        ("main.py.j2", Path("app") / "main.py"),
        ("README.md.j2", Path("README.md")),
        ("pyproject.toml.j2", Path("pyproject.toml")),
        ("Dockerfile.j2", Path("Dockerfile")),
    ):
        (destination / target).write_text(
            render(f"fastapi/{template}", **context), encoding="utf-8", newline="\n"
        )
    (destination / "app" / "__init__.py").write_text("", encoding="utf-8", newline="\n")
    return destination
