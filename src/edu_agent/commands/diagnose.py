"""What ``doctor`` reports beyond Python and the API key.

Only the parts that depend on the project's own design: today that is whether the
code-execution tool it declares can actually be isolated on this machine.
"""

from __future__ import annotations

from edu_agent import ui
from edu_agent.i18n import t
from edu_agent.project import Project
from edu_agent.project.layout import SPEC_DOC


def report_sandbox(project: Project | None) -> None:
    """Only shown when the project actually declares a code-execution tool."""
    from edu_agent.security.sandbox import describe_backends, get_sandbox

    if project is None:
        return
    spec_path = project.doc_path(SPEC_DOC)
    if not spec_path.exists():
        return
    from edu_agent.documents.io import load_document
    from edu_agent.schemas.agent import AgentSpec

    try:
        spec, _ = load_document(spec_path, AgentSpec)
    except Exception:
        return
    assert isinstance(spec, AgentSpec)
    if not any(tool.name == "code_execution" for tool in spec.tools):
        return

    policy = project.config.sandbox
    ui.say()
    active = get_sandbox(policy)
    ui.info(t("doctor.sandbox_title"))
    if active.name == "subprocess":
        ui.warn(t("doctor.sandbox_partial"))
    elif active.name == "docker":
        ui.ok(t("doctor.sandbox_container"))
    else:
        ui.info(t("doctor.sandbox_off"))
    for name, ok_, why in describe_backends(policy):
        (ui.ok if ok_ else ui.note)(f"{name}{'' if ok_ else f' — {why}'}")

