"""What every command needs before it can do anything.

Loading the project, resolving a provider, reading and writing the four documents.
Separated from the commands so a workflow can be exercised without going through
argument parsing — and so the rule about which steps may run without an API key
lives in one place instead of in each command.
"""

from __future__ import annotations

from pathlib import Path

from edu_agent import ui
from edu_agent.i18n import set_language, t
from edu_agent.project import Project, ProjectNotFound, find_project
from edu_agent.project.layout import DOC_FILES, INPUT_DOCS, SPEC_DOC, DocSlot


def load_project() -> Project:
    try:
        project = find_project()
    except ProjectNotFound as exc:
        ui.die(t("errors.no_project"), hint=f"현재 위치: {exc}", command="edu-agent init")
    set_language(project.config.language)
    return project


def load_dotenv(project: Project | None = None) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    if project is not None:
        load_dotenv(project.root / ".env", override=False)
    load_dotenv(override=False)


def provider(
    project: Project,
    *,
    role: str = "tutor",
    no_llm: bool = False,
    mock: bool = False,
    optional: bool = False,
):
    """Build a provider, or ``None`` when there is a sensible way to go on without one.

    ``optional`` marks the steps that are genuinely usable before a key arrives —
    writing the documents and compiling them. Those degrade with a notice instead
    of stopping, because a key often arrives long after the document work starts —
    handed out midway through a course, approved by a school weeks later — and a
    hard stop at step one would strand someone who has real work to do.

    Running and evaluating an agent are *not* optional in that sense. Quietly
    substituting a fake model there would produce a report a teacher could mistake
    for a real one, so those still stop — and say which flag to use.
    """
    if no_llm:
        return None
    from edu_agent.providers import ProviderError, get_provider

    try:
        return get_provider(project.config.provider, role=role, mock=mock)
    except ProviderError as exc:
        if optional:
            ui.warn(str(exc))
            ui.note(t("errors.continuing_without_model"))
            return None
        ui.die(
            str(exc),
            hint=f"{getattr(exc, 'hint', '')}\n{t('errors.no_key_yet')}".strip(),
            command="edu-agent doctor",
        )


def read_doc(project: Project, slot: DocSlot):
    from edu_agent.documents.io import DocumentError, load_document

    try:
        return load_document(project.doc_path(slot), slot.model)
    except DocumentError as exc:
        ui.die(str(exc), hint=exc.detail, command=f"edu-agent review {slot.index:02d}")


def write_doc(project: Project, slot: DocSlot, model, context_key: str = "d") -> Path:
    from edu_agent.documents import render_document, save_document

    body = render_document(slot.template, **{context_key: model})
    return save_document(project.doc_path(slot), model, body)


def spec_hashes(project: Project) -> dict[str, str]:
    from edu_agent.utils.hashing import hash_text

    out: dict[str, str] = {}
    for slot in INPUT_DOCS:
        path = project.doc_path(slot)
        if path.exists():
            out[slot.filename] = hash_text(path.read_text(encoding="utf-8"))
    return out


def load_spec(project: Project, *, warn_stale: bool = True):
    from edu_agent.schemas.agent import AgentSpec

    path = project.doc_path(SPEC_DOC)
    if not path.exists():
        ui.die(t("errors.spec_missing"), command="edu-agent compile")
    spec, _ = read_doc(project, SPEC_DOC)
    assert isinstance(spec, AgentSpec)
    if warn_stale:
        current = spec_hashes(project)
        recorded = spec.meta.input_hashes
        changed = [k for k, v in current.items() if recorded.get(k) and recorded[k] != v]
        if changed:
            ui.warn(f"입력 문서가 바뀌었습니다: {', '.join(changed)}")
            ui.note("'edu-agent compile' 을 다시 실행하면 최신 설계가 반영됩니다.")
    return spec


def tool_runtime(project: Project, spec, task):
    """Tools are only built when the spec declares one the harness can run."""
    from edu_agent.runtime.tools import ToolRuntime

    if not spec.tools:
        return None
    return ToolRuntime(spec.tools, sandbox_policy=project.config.sandbox, task=task)


def tool_line(call) -> str:
    """One line per tool call, including the refused ones."""
    if not call.allowed:
        return f"[yellow]도구 차단 · {call.name}: {call.blocked_reason}[/yellow]"
    mark = "실행" if call.ok else "실패"
    where = f" · {call.backend}" if call.backend else ""
    detail = f": {call.error}" if call.error else ""
    return f"[dim]도구 {mark} · {call.name}{where}{detail}[/dim]"


def first_task(project: Project):
    from edu_agent.schemas.educational import EducationalDesign

    path = project.doc_path(DOC_FILES[0])
    if not path.exists():
        return None
    try:
        doc, _ = read_doc(project, DOC_FILES[0])
    except ui.Abort:
        # A task is a nicety; a broken 01 is the review command's problem to report.
        return None
    assert isinstance(doc, EducationalDesign)
    return doc.tasks[0] if doc.tasks else None

