"""Choosing which standalone project to write.

Small on purpose. The decision belongs to ``03_technical_spec.md``, so this reads
it rather than asking again.
"""

from __future__ import annotations

from edu_agent.project import Project
from edu_agent.project.layout import DOC_FILES


def target_from_technical(project: Project) -> str:
    """``03_technical_spec.md`` already recorded how this agent should run."""
    from edu_agent.schemas.technical import ExecutionPath, TechnicalSpec

    path = project.doc_path(DOC_FILES[2])
    if not path.exists():
        return "cli"
    try:
        from edu_agent.documents.io import load_document

        tech, _ = load_document(path, TechnicalSpec)
    except Exception:
        return "cli"
    assert isinstance(tech, TechnicalSpec)
    return "fastapi" if tech.execution_path is ExecutionPath.EXPORT_FASTAPI else "cli"

