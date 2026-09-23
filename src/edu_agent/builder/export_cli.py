"""Exporting a runnable Python CLI project.

The generated project *depends on* ``edu_agent.runtime`` rather than vendoring a
copy of it (ADR-13). Two reasons: the generated code stays short enough that a
student can read it, and the policy-gate logic exists in one place — a vendored
copy would drift the moment the harness fixed a bug.

The files themselves live in ``templates/export/cli/``. They used to be Python
strings inside this module, which meant every brace in the generated code had to
be doubled to survive ``str.format`` — Python inside Python, unreadable and
un-lintable. As templates they are just the files they produce.
"""

from __future__ import annotations

from pathlib import Path

from edu_agent.builder.common import HARNESS_REQUIREMENT, gate_summary, render, write_common
from edu_agent.schemas.agent import AgentSpec


def export_cli(project, spec: AgentSpec, destination: Path) -> Path:
    """Write a standalone CLI project to ``destination``."""
    write_common(project, spec, destination)

    context = {
        "name": project.config.name,
        "slug": project.config.name.replace("-", "_"),
        "role": spec.agent_role or "교육용 AI 에이전트",
        "gates": gate_summary(spec),
        "harness": HARNESS_REQUIREMENT,
    }
    for template, target in (
        ("agent.py.j2", Path("app") / "agent.py"),
        ("README.md.j2", Path("README.md")),
        ("pyproject.toml.j2", Path("pyproject.toml")),
    ):
        (destination / target).write_text(
            render(f"cli/{template}", **context), encoding="utf-8", newline="\n"
        )
    return destination
