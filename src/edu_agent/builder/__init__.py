"""Exporting a standalone project (plan v2 §12).

Two targets share one tree: ``cli`` (a terminal chat) and ``fastapi`` (a local
service with the same browser page ``edu-agent run --web`` serves). Both read the
spec at runtime rather than compiling it into code, so the documents stay the
source of truth after export.
"""

from pathlib import Path

from edu_agent.builder.common import write_common
from edu_agent.builder.export_cli import export_cli
from edu_agent.builder.export_fastapi import export_fastapi
from edu_agent.schemas.agent import AgentSpec

#: Target name → writer. ``edu-agent build --target`` validates against this.
TARGETS = {"cli": export_cli, "fastapi": export_fastapi}


def export(target: str, project, spec: AgentSpec, destination: Path) -> Path:
    """Export ``spec`` as a standalone project of the requested shape."""
    try:
        writer = TARGETS[target]
    except KeyError:
        raise ValueError(f"알 수 없는 내보내기 대상: {target}") from None
    return writer(project, spec, destination)


__all__ = ["TARGETS", "export", "export_cli", "export_fastapi", "write_common"]
