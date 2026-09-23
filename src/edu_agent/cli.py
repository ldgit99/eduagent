"""``edu-agent`` command line interface.

Command set (plan v2 §2)::

    doctor init status review compile run test calibrate improve report build view

Design rules that apply to every command:

* Never show a traceback to a student. Failures raise :class:`ui.Abort` with a
  message, a hint and the command to run next.
* Every command that needs a model accepts ``--no-llm``/``--mock`` so document work
  and the whole test pipeline stay usable before an API key arrives.
* Stopping is always safe: ``S`` or Ctrl+C saves what has been entered.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated

import typer

from edu_agent import ui
from edu_agent._version import __version__
from edu_agent.i18n import set_language, t
from edu_agent.project import Project, ProjectNotFound, create_project, find_project
from edu_agent.project.layout import DOC_FILES, INPUT_DOCS, SPEC_DOC, DocSlot, slot_for

app = typer.Typer(
    name="edu-agent",
    help="교육용 AI 에이전트를 설계·실행·검증하는 하네스",
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)

_VERBOSE = False


# --- shared helpers -------------------------------------------------------
def _load_project() -> Project:
    try:
        project = find_project()
    except ProjectNotFound as exc:
        ui.die(t("errors.no_project"), hint=f"현재 위치: {exc}", command="edu-agent init")
    set_language(project.config.language)
    return project


def _load_dotenv(project: Project | None = None) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    if project is not None:
        load_dotenv(project.root / ".env", override=False)
    load_dotenv(override=False)


def _provider(project: Project, *, role: str = "tutor", no_llm: bool = False, mock: bool = False):
    """Build a provider, or None when the caller opted out of model calls."""
    if no_llm:
        return None
    from edu_agent.providers import ProviderError, get_provider

    try:
        return get_provider(project.config.provider, role=role, mock=mock)
    except ProviderError as exc:
        ui.die(str(exc), hint=getattr(exc, "hint", ""), command="edu-agent doctor")


def _read_doc(project: Project, slot: DocSlot):
    from edu_agent.documents.io import DocumentError, load_document

    try:
        return load_document(project.doc_path(slot), slot.model)
    except DocumentError as exc:
        ui.die(str(exc), hint=exc.detail, command=f"edu-agent review {slot.index:02d}")


def _write_doc(project: Project, slot: DocSlot, model, context_key: str = "d") -> Path:
    from edu_agent.documents import render_document, save_document

    body = render_document(slot.template, **{context_key: model})
    return save_document(project.doc_path(slot), model, body)


def _spec_hashes(project: Project) -> dict[str, str]:
    from edu_agent.utils.hashing import hash_text

    out: dict[str, str] = {}
    for slot in INPUT_DOCS:
        path = project.doc_path(slot)
        if path.exists():
            out[slot.filename] = hash_text(path.read_text(encoding="utf-8"))
    return out


def _load_spec(project: Project, *, warn_stale: bool = True):
    from edu_agent.schemas.agent import AgentSpec

    path = project.doc_path(SPEC_DOC)
    if not path.exists():
        ui.die(t("errors.spec_missing"), command="edu-agent compile")
    spec, _ = _read_doc(project, SPEC_DOC)
    assert isinstance(spec, AgentSpec)
    if warn_stale:
        current = _spec_hashes(project)
        recorded = spec.meta.input_hashes
        changed = [k for k, v in current.items() if recorded.get(k) and recorded[k] != v]
        if changed:
            ui.warn(f"입력 문서가 바뀌었습니다: {', '.join(changed)}")
            ui.note("'edu-agent compile' 을 다시 실행하면 최신 설계가 반영됩니다.")
    return spec


def _tool_runtime(project: Project, spec, task):
    """Tools are only built when the spec declares one the harness can run."""
    from edu_agent.runtime.tools import ToolRuntime

    if not spec.tools:
        return None
    return ToolRuntime(spec.tools, sandbox_policy=project.config.sandbox, task=task)


def _tool_line(call) -> str:
    """One line per tool call, including the refused ones."""
    if not call.allowed:
        return f"[yellow]도구 차단 · {call.name}: {call.blocked_reason}[/yellow]"
    mark = "실행" if call.ok else "실패"
    where = f" · {call.backend}" if call.backend else ""
    detail = f": {call.error}" if call.error else ""
    return f"[dim]도구 {mark} · {call.name}{where}{detail}[/dim]"


def _first_task(project: Project):
    from edu_agent.schemas.educational import EducationalDesign

    path = project.doc_path(DOC_FILES[0])
    if not path.exists():
        return None
    try:
        doc, _ = _read_doc(project, DOC_FILES[0])
    except SystemExit:
        return None
    assert isinstance(doc, EducationalDesign)
    return doc.tasks[0] if doc.tasks else None


# --- callback -------------------------------------------------------------
@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="자세한 오류를 표시합니다")] = False,
    lang: Annotated[str, typer.Option("--lang", help="ko | en")] = "",
    version: Annotated[bool, typer.Option("--version", help="버전을 표시하고 종료합니다")] = False,
) -> None:
    # invoke_without_command lets `--version` work on its own; without it Click
    # rejects the call as "missing command" before the callback ever runs.
    global _VERBOSE
    _VERBOSE = verbose
    if lang:
        set_language(lang)
    if version:
        ui.say(f"edu-agent-harness {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        ui.say(ctx.get_help())
        raise typer.Exit()


# --- doctor ---------------------------------------------------------------
@app.command()
def doctor(
    check_model: Annotated[bool, typer.Option("--check-model/--no-check-model",
                                              help="모델에 실제로 요청을 보내 확인합니다")] = True,
) -> None:
    """환경을 점검합니다. 무언가 안 될 때 가장 먼저 실행하세요."""
    from edu_agent.project.config import ENV_API_KEY, ENV_BASE_URL, ENV_MODEL

    ui.header(t("doctor.title"))

    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    # If the package imported at all, Python is new enough — but showing the
    # version is still the first thing a student needs when asking for help.
    ui.ok(t("doctor.python_ok", version=version))

    project: Project | None = None
    try:
        project = find_project()
        ui.ok(t("doctor.project_found", name=project.config.name))
        ui.note(str(project.root))
    except ProjectNotFound:
        ui.warn(t("doctor.project_missing"))

    _load_dotenv(project)

    env_path = (project.root / ".env") if project else Path(".env")
    if env_path.exists():
        ui.ok(f"{t('doctor.env_file')}: {env_path}")
    else:
        ui.warn(f"{t('doctor.env_file')} 없음")

    key = os.getenv(ENV_API_KEY)
    if key:
        ui.ok(t("doctor.key_ok", tail=key[-4:]))
    else:
        ui.warn(t("doctor.key_missing"))
        ui.say(t("doctor.no_key_hint"))

    base_url = os.getenv(ENV_BASE_URL) or (project.config.provider.base_url if project else "")
    model = os.getenv(ENV_MODEL) or (project.config.provider.model if project else "")
    if base_url:
        ui.info(t("doctor.base_url", url=base_url))
    if model:
        ui.info(t("doctor.model", model=model))
    else:
        ui.warn("사용할 모델이 지정되지 않았습니다 (EDU_AGENT_MODEL).")

    from edu_agent.providers import available_providers

    installed = [name for name, ok_ in available_providers().items() if ok_ and name != "mock"]
    ui.info(f"설치된 연결 방식: {', '.join(installed) or '없음 (mock만 가능)'}")

    if check_model and project and key and model:
        from edu_agent.providers import ProviderError, get_provider

        try:
            provider = get_provider(project.config.provider)
            ms = provider.ping()
            ui.ok(t("doctor.reach_ok", ms=int(ms)))
        except ProviderError as exc:
            ui.fail(t("doctor.reach_fail", error=str(exc)))
            if getattr(exc, "hint", ""):
                ui.note(exc.hint)

    _report_sandbox(project)

    ui.say()
    ui.info(t("doctor.all_ok"))


def _report_sandbox(project: Project | None) -> None:
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


# --- init -----------------------------------------------------------------
@app.command()
def init(
    name: Annotated[str, typer.Argument(help="프로젝트 이름 (비우면 물어봅니다)")] = "",
    here: Annotated[bool, typer.Option("--here", help="현재 폴더에 만듭니다")] = False,
    lang: Annotated[str, typer.Option("--lang", help="ko | en")] = "ko",
) -> None:
    """새 프로젝트를 만듭니다."""
    ui.header(t("init.welcome"))

    if not name:
        name = ui.ask_text(
            t("init.ask_name"),
            default="my-agent",
            hint="폴더 이름으로 쓰입니다. 영문 소문자와 하이픈을 권합니다.",
        )
    name = name.strip().replace(" ", "-")
    root = Path.cwd() if here else Path.cwd() / name

    if (root / "edu-agent.yaml").exists():
        ui.die(t("init.exists", path=root), command="edu-agent status")

    title = ui.ask_text(
        t("init.ask_title"),
        hint="한 문장이면 충분합니다. 나중에 얼마든지 바꿀 수 있습니다.",
    )

    project = create_project(root, name=name, title=title, language=lang)
    set_language(lang)
    ui.ok(t("init.created", path=project.root))
    ui.say()
    ui.note("만들어진 것:")
    ui.key_value(
        [
            ("edu-agent.yaml", "프로젝트 설정"),
            (".env.example", "API 키를 넣을 자리 (.env 로 복사해서 쓰세요)"),
            ("tasks/", "과제와 정답 기준"),
            (".gitignore", "대화 기록과 키가 GitHub에 올라가지 않게 합니다"),
        ]
    )
    ui.say()

    start = ui.ask_yes_no("지금 바로 교육 설계를 시작할까요?", default=True)
    if start:
        _run_review(project, DOC_FILES[0], no_llm=True, mock=False)
    else:
        ui.info(t("init.next"))


# --- status ---------------------------------------------------------------
@app.command()
def status() -> None:
    """4개 문서의 진행 상태와 다음에 할 일을 보여줍니다."""
    from edu_agent.documents.io import detect_drift, load_document
    from edu_agent.schemas.common import DocumentStatus

    project = _load_project()
    ui.header(f"{t('status.title')} · {project.config.name}", project.config.title)

    next_action = ""
    for slot in DOC_FILES:
        path = project.doc_path(slot)
        if not path.exists():
            ui.say(f"  {slot.label.ljust(18)} [dim]○ {t('status.doc_missing')}[/dim]")
            if not next_action:
                next_action = (
                    t("status.hint_compile")
                    if slot is SPEC_DOC
                    else t("status.hint_review", doc=f"{slot.index:02d}")
                )
            continue
        try:
            model, body = load_document(path, slot.model)
        except Exception:
            ui.say(f"  {slot.label.ljust(18)} [red]✘ 파일을 읽을 수 없습니다[/red]")
            if not next_action:
                next_action = t("status.hint_review", doc=f"{slot.index:02d}")
            continue

        drifted = detect_drift(model, body)
        state = model.meta.status
        if drifted:
            ui.say(f"  {slot.label.ljust(18)} [yellow]◐ {t('status.needs_sync')}[/yellow]")
            if not next_action:
                next_action = t("status.hint_review", doc=f"{slot.index:02d}")
        elif state in {DocumentStatus.CONFIRMED, DocumentStatus.COMPILED}:
            date = model.meta.updated_at.date().isoformat()
            label = t("status.compiled") if slot is SPEC_DOC else t("status.confirmed")
            ui.say(f"  {slot.label.ljust(18)} [green]✔ {label}[/green]  [dim]({date})[/dim]")
        else:
            missing = model.missing_required()
            detail = f" — 비어 있는 항목 {len(missing)}개" if missing else ""
            ui.say(f"  {slot.label.ljust(18)} [yellow]◐ {t('status.draft')}{detail}[/yellow]")
            if not next_action:
                next_action = t("status.hint_review", doc=f"{slot.index:02d}")

    if not next_action:
        current = _spec_hashes(project)
        spec_path = project.doc_path(SPEC_DOC)
        if spec_path.exists():
            spec, _ = load_document(spec_path, SPEC_DOC.model)
            recorded = spec.meta.input_hashes
            if any(recorded.get(k) and recorded[k] != v for k, v in current.items()):
                ui.say()
                ui.warn(t("status.stale"))
                next_action = t("status.hint_compile")

    runs = project.runs_dir
    n_runs = len([p for p in runs.iterdir() if p.is_dir()]) if runs.exists() else 0
    if n_runs:
        ui.say()
        ui.info(f"실행 기록 {n_runs}개  [dim](edu-agent view)[/dim]")

    ui.say()
    ui.info(f"[bold]{t('common.next_step')}[/bold]: {next_action or t('status.hint_test')}")


# --- review ---------------------------------------------------------------
@app.command()
def review(
    which: Annotated[str, typer.Argument(help="01 | 02 | 03 (비우면 다음 할 것)")] = "",
    no_llm: Annotated[bool, typer.Option("--no-llm", help="AI 도움 없이 진행합니다")] = False,
    mock: Annotated[bool, typer.Option("--mock", help="가짜 모델로 시험 실행합니다")] = False,
) -> None:
    """문서를 작성하거나 검토합니다. 질문 → 확인 → 저장."""
    project = _load_project()
    _load_dotenv(project)

    if which:
        slot = slot_for(which)
    else:
        slot = next((s for s in INPUT_DOCS if not project.exists(s)), INPUT_DOCS[0])
    if slot is SPEC_DOC:
        ui.die("04 는 직접 작성하지 않습니다.", command="edu-agent compile")

    _run_review(project, slot, no_llm=no_llm, mock=mock)


def _run_review(project: Project, slot: DocSlot, *, no_llm: bool, mock: bool) -> None:
    from edu_agent.documents.io import detect_drift, load_document
    from edu_agent.questionnaire import educational as q_edu
    from edu_agent.questionnaire import principles as q_pri
    from edu_agent.questionnaire import technical as q_tec
    from edu_agent.schemas.common import DocumentStatus

    path = project.doc_path(slot)
    if path.exists():
        model, body = load_document(path, slot.model)
        if detect_drift(model, body):
            ui.warn(t("review.drift_detected"))
            keep = ui.ask_choice(
                "어떻게 할까요?",
                [
                    ui.Choice("1", "질문에 다시 답해서 구조를 갱신하겠습니다", "redo"),
                    ui.Choice("2", "본문 수정만 인정하고 그대로 두겠습니다", "keep"),
                ],
                default="1",
                allow_later=False,
            )
            if keep == "keep":
                from edu_agent.documents.io import save_document

                model.meta.status = DocumentStatus.CONFIRMED
                save_document(path, model, body)
                ui.ok(t("common.saved", path=path.name))
                return
    else:
        model = slot.model.new(language=project.config.language)

    provider = None
    if slot.key == "principles":
        provider = _provider(project, no_llm=no_llm, mock=mock)
        if provider is None:
            ui.warn(t("review.no_llm"))

    try:
        if slot.key == "educational":
            model = q_edu.run_educational(model, tasks_dir=project.tasks_dir)  # type: ignore[arg-type]
            summary = q_edu.summarize(model)  # type: ignore[arg-type]
        elif slot.key == "principles":
            model = q_pri.run_principles(model, provider=provider)  # type: ignore[arg-type]
            summary = q_pri.summarize(model)  # type: ignore[arg-type]
        else:
            users = None
            if project.exists(DOC_FILES[0]):
                ed, _ = load_document(project.doc_path(DOC_FILES[0]), DOC_FILES[0].model)
                users = ed.context.expected_users  # type: ignore[attr-defined]
            model = q_tec.run_technical(model, expected_users=users)  # type: ignore[arg-type]
            summary = q_tec.summarize(model)  # type: ignore[arg-type]
    except ui.UserAbort:
        _write_doc(project, slot, model)
        ui.say()
        ui.info(t("common.cancelled"))
        ui.note(f"이어서 하려면: edu-agent review {slot.index:02d}")
        return

    action = ui.confirm_summary(t("review.summary_title"), summary)
    if action == "confirm":
        model.meta.status = DocumentStatus.CONFIRMED
    elif action in {"edit", "add"}:
        ui.note(
            f"{slot.filename} 파일을 직접 열어 수정한 뒤 "
            f"'edu-agent review {slot.index:02d}' 를 다시 실행하세요."
        )

    missing = model.missing_required()
    saved = _write_doc(project, slot, model)
    ui.say()
    ui.ok(t("common.saved", path=saved.name))

    if missing:
        ui.warn(f"{t('review.missing_title')}: {', '.join(missing)}")

    nxt = next((s for s in INPUT_DOCS if s.index > slot.index), None)
    ui.say()
    if nxt is not None:
        ui.info(f"{t('common.next_step')}: edu-agent review {nxt.index:02d}")
    else:
        ui.info(f"{t('common.next_step')}: edu-agent compile")


# --- compile --------------------------------------------------------------
@app.command()
def compile(
    no_llm: Annotated[bool, typer.Option("--no-llm", help="AI 도움 없이 컴파일합니다")] = False,
    mock: Annotated[bool, typer.Option("--mock", help="가짜 모델로 시험 실행합니다")] = False,
    force: Annotated[bool, typer.Option("--force", help="경고를 무시하고 진행합니다")] = False,
) -> None:
    """01·02·03 을 종합해 04_agent_spec.md 를 만듭니다."""
    from edu_agent.compiler import compile_spec
    from edu_agent.compiler.checks import Severity
    from edu_agent.schemas.common import DocumentStatus

    project = _load_project()
    _load_dotenv(project)

    for slot in INPUT_DOCS:
        if not project.exists(slot):
            ui.die(
                t("errors.doc_missing", doc=slot.filename, n=f"{slot.index:02d}"),
                command=f"edu-agent review {slot.index:02d}",
            )

    educational, _ = _read_doc(project, DOC_FILES[0])
    principles, _ = _read_doc(project, DOC_FILES[1])
    technical, _ = _read_doc(project, DOC_FILES[2])

    ui.header(t("compile.running"))
    provider = _provider(project, no_llm=no_llm, mock=mock)

    result = compile_spec(
        educational,  # type: ignore[arg-type]
        principles,  # type: ignore[arg-type]
        technical,  # type: ignore[arg-type]
        provider=provider,
        input_hashes=_spec_hashes(project),
        language=project.config.language,
    )

    for issue in result.issues:
        if issue.severity is Severity.ERROR:
            ui.fail(str(issue))
        elif issue.severity is Severity.WARNING:
            ui.warn(str(issue))
        else:
            ui.info(str(issue))
        if issue.fix:
            ui.note(f"→ {issue.fix}")

    if not result.ok:
        ui.say()
        ui.die(
            t("compile.blocked"),
            hint=f"해결해야 할 문제 {len(result.errors)}개가 위에 있습니다.",
        )

    spec = result.spec
    assert spec is not None
    if result.warnings and not force:
        ui.say()
        go = ui.ask_yes_no("경고가 있습니다. 그대로 진행할까요?", default=True)
        if not go:
            ui.info("문서를 고친 뒤 다시 실행하세요.")
            return

    spec.meta.status = DocumentStatus.COMPILED
    saved = _write_doc(project, SPEC_DOC, spec)

    ui.say()
    ui.ok(t("compile.done"))
    ui.note(str(saved.name))
    ui.say()
    ui.key_value(
        [
            ("행동 규칙", f"{len(spec.behaviors)}개"),
            ("정책 게이트", f"{len(spec.gates)}개 (실행 중 강제)"),
            ("평가 기준", f"{len(spec.criteria)}개"),
            ("테스트 시나리오", f"{len(spec.scenarios)}개"),
        ]
    )

    untraced = spec.untraced_principles()
    if untraced:
        ui.say()
        ui.warn(f"테스트까지 이어지지 않은 설계원리: {', '.join(untraced)}")
        ui.note("이 원리들은 실행되더라도 검증되지 않습니다.")

    ui.say()
    ui.info(f"{t('common.next_step')}: edu-agent run  (또는 edu-agent test)")


# --- run ------------------------------------------------------------------
@app.command()
def run(
    persona: Annotated[str, typer.Option("--persona", help="시뮬레이션 학생과 대화합니다 (예: S04)")] = "",
    mock: Annotated[bool, typer.Option("--mock", help="가짜 모델로 시험 실행합니다")] = False,
    show_prompt: Annotated[bool, typer.Option("--show-prompt", help="시스템 프롬프트를 보여줍니다")] = False,
    turns: Annotated[int, typer.Option("--turns", help="페르소나 대화의 최대 턴 수")] = 8,
    web: Annotated[bool, typer.Option("--web", help="브라우저에서 대화합니다")] = False,
    port: Annotated[int, typer.Option("--port", help="--web 이 쓸 포트 (0 = 자동)")] = 7860,
    open_browser: Annotated[bool, typer.Option("--open/--no-open",
                                               help="--web 실행 시 브라우저를 엽니다")] = True,
) -> None:
    """에이전트와 직접 대화합니다. 04 문서를 그대로 실행합니다."""
    from edu_agent.runtime.loop import AgentRuntime
    from edu_agent.storage.jsonl import RunPaths, new_run_id, save_session

    project = _load_project()
    _load_dotenv(project)
    spec = _load_spec(project)

    if show_prompt:
        from edu_agent.runtime.prompt import build_system_prompt

        ui.panel(build_system_prompt(spec), title="시스템 프롬프트", style="blue")
        if not persona:
            return

    provider = _provider(project, mock=mock)
    assert provider is not None
    task = _first_task(project)

    if persona:
        _run_with_persona(project, spec, provider, persona, task, turns, mock)
        return

    if web:
        _run_web(project, spec, provider, task, port=port, open_browser=open_browser)
        return

    ui.header(t("run.banner", name=project.config.name))
    ui.note(t("run.privacy"))
    ui.say()

    runtime = AgentRuntime(
        spec=spec, provider=provider, task=task, tools=_tool_runtime(project, spec, task)
    )
    runtime.trace.run_id = new_run_id("chat")

    while True:
        try:
            message = ui.ask_text("나", allow_empty=False)
        except ui.UserAbort:
            break
        if message.strip() in {"/quit", "/q", "/exit"}:
            break

        result = runtime.turn(message)
        ui.say()
        for call in result.tool_calls:
            ui.note(_tool_line(call))
        ui.say(f"[bold cyan]튜터[/bold cyan]  {result.message}")
        if result.gate_outcome.blocked:
            reasons = "; ".join(d.reason for d in result.gate_outcome.blocked[:2])
            ui.note(t("run.gate_blocked", reason=reasons))
        if result.fallback_used:
            ui.note(t("run.fallback"))
        ui.say()

    paths = RunPaths(project.runs_dir, runtime.trace.run_id)
    saved = save_session(paths, runtime.trace)
    ui.say()
    ui.ok(t("run.ended", path=saved))


def _run_web(project, spec, provider, task, *, port: int, open_browser: bool) -> None:
    """Serve the chat in a browser until Ctrl+C, then save what was said."""
    import webbrowser

    from edu_agent.runtime.loop import AgentRuntime
    from edu_agent.storage.jsonl import RunPaths, new_run_id, save_session
    from edu_agent.web import ChatServer, ChatSession

    run_id = new_run_id("web")

    def build_runtime() -> AgentRuntime:
        runtime = AgentRuntime(
            spec=spec, provider=provider, task=task, tools=_tool_runtime(project, spec, task)
        )
        runtime.trace.run_id = run_id
        return runtime

    session = ChatSession(
        build_runtime=build_runtime,
        title=project.config.title or project.config.name,
        role=spec.agent_role or "",
        lang=project.config.language,
    )
    try:
        server = ChatServer(session, port=port)
    except OSError as exc:
        ui.die(
            t("run.web_port_busy", port=port),
            hint=str(exc),
            command="edu-agent run --web --port 0",
        )

    ui.header(t("run.banner", name=project.config.name))
    ui.ok(t("run.web_ready", url=server.url))
    ui.note(t("run.privacy"))
    ui.note(t("run.web_stop"))
    if open_browser:
        webbrowser.open(server.url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()

    paths = RunPaths(project.runs_dir, run_id)
    saved = [save_session(paths, trace) for trace in session.finished_traces()]
    ui.say()
    if saved:
        ui.ok(t("run.ended", path=paths.dir))
    else:
        ui.info(t("run.web_nothing"))


def _run_with_persona(project, spec, provider, persona_id, task, turns, mock) -> None:
    from edu_agent.simulator.loop import run_simulation
    from edu_agent.simulator.personas import load_personas
    from edu_agent.storage.jsonl import RunPaths, new_run_id, save_session

    personas = load_personas(project.root / "personas.yaml")
    target = personas.get(persona_id.upper())
    if target is None:
        ui.die(
            f"'{persona_id}' 학생을 찾을 수 없습니다.",
            hint=f"사용 가능: {', '.join(personas.ids())}",
        )

    scenario = spec.scenario(spec.scenarios[0].id) if spec.scenarios else None
    if scenario is None:
        from edu_agent.schemas.agent import TestScenario

        scenario = TestScenario(id="T01", name="즉석 시나리오", persona_id=target.id, max_turns=turns)

    ui.header(f"시뮬레이션 학생과 대화 · {target.id} {target.name}", target.summary)
    student_provider = _provider(project, role="student", mock=mock) if mock else None

    run_id = new_run_id("persona")
    result = run_simulation(
        spec, scenario, target, provider,
        student_provider=student_provider, task=task, run_id=run_id, max_turns=turns,
        tools=_tool_runtime(project, spec, task),
    )
    for turn in result.trace.turns:
        ui.say(f"[bold]학생[/bold]  {turn.learner_message}")
        ui.say(f"[bold cyan]튜터[/bold cyan]  {turn.tutor_message}")
        marks = []
        if turn.declared_action:
            marks.append(f"행동: {turn.declared_action.value}")
        if turn.leaked_answer:
            marks.append("[red]정답 노출[/red]")
        if turn.blocked_gates:
            marks.append(f"[yellow]게이트 차단 {len(turn.blocked_gates)}건[/yellow]")
        for call in turn.tool_calls:
            marks.append(_tool_line(call))
        if marks:
            ui.note(" · ".join(marks))
        ui.say()

    paths = RunPaths(project.runs_dir, run_id)
    save_session(paths, result.trace)
    ui.ok(f"기록: {paths.dir}")


# --- test -----------------------------------------------------------------
@app.command()
def test(
    seeds: Annotated[int, typer.Option("--seeds", help="시나리오당 반복 횟수")] = 0,
    no_llm: Annotated[bool, typer.Option("--no-llm", help="AI 판정 없이 자동 검사만 합니다")] = False,
    mock: Annotated[bool, typer.Option("--mock", help="가짜 모델로 시험 실행합니다")] = False,
    scenario: Annotated[str, typer.Option("--scenario", help="특정 시나리오만 실행합니다")] = "",
    regrade: Annotated[str, typer.Option("--regrade", help="저장된 실행을 다시 채점합니다")] = "",
    llm_student: Annotated[bool, typer.Option("--llm-student", help="학생 발화를 모델로 생성합니다")] = False,
) -> None:
    """시뮬레이션 학생과 대화시키고 교육적 실행 충실도를 평가합니다."""
    from edu_agent.report.console import render_report
    from edu_agent.storage.jsonl import (
        RunPaths,
        latest_run,
        new_run_id,
        save_manifest,
        save_session,
    )

    project = _load_project()
    _load_dotenv(project)
    spec = _load_spec(project)

    if regrade:
        _regrade(project, spec, regrade if regrade != "latest" else (latest_run(project.runs_dir) or ""),
                 no_llm=no_llm, mock=mock)
        return

    from edu_agent.evaluator.judge import Judge
    from edu_agent.evaluator.runner import EvaluationInput, evaluate
    from edu_agent.simulator.loop import run_simulation
    from edu_agent.simulator.personas import load_personas

    provider = _provider(project, mock=mock)
    assert provider is not None
    student_provider = (
        _provider(project, role="student", mock=mock) if llm_student else None
    )
    judge_provider = _provider(project, role="judge", no_llm=no_llm, mock=mock)

    personas = load_personas(project.root / "personas.yaml")
    task = _first_task(project)
    seeds = seeds or project.config.evaluation.seeds

    scenarios = [s for s in spec.scenarios if not scenario or s.id == scenario.upper()]
    if not scenarios:
        ui.die("실행할 시나리오가 없습니다.", command="edu-agent compile")

    run_id = new_run_id("test")
    paths = RunPaths(project.runs_dir, run_id).ensure()

    total = sum(max(s.seeds, seeds) for s in scenarios)
    done = 0
    traces = []
    results = []

    ui.header(t("test.title"), f"{len(scenarios)}개 시나리오 × {seeds}회")
    for sc in scenarios:
        persona = personas.get(sc.persona_id)
        if persona is None:
            ui.warn(f"{sc.id}: '{sc.persona_id}' 학생을 찾을 수 없어 건너뜁니다.")
            continue
        for seed in range(max(sc.seeds, seeds)):
            done += 1
            ui.say(f"  [dim]({done}/{total})[/dim] {sc.id} · {persona.name} · seed {seed}")
            result = run_simulation(
                spec, sc, persona, provider,
                student_provider=student_provider, task=task, seed=seed,
                run_id=run_id, spec_hash=spec.meta.content_hash or "",
                tools=_tool_runtime(project, spec, task),
            )
            save_session(paths, result.trace)
            traces.append(result.trace)
            results.append(result)

    ui.say()
    ui.info(t("test.evaluating"))
    judge = (
        Judge(
            judge_provider,
            order_swap=project.config.evaluation.order_swap,
            overlay=_judge_overlay(project),
        )
        if judge_provider
        else None
    )
    report = evaluate(
        EvaluationInput(
            spec=spec, traces=traces, results=results, judge=judge, run_id=run_id,
            project=project.config.name, seeds=seeds,
            calibration_threshold=project.config.evaluation.calibration_threshold,
        )
    )
    _attach_calibration(project, report)

    paths.report.write_text(report.model_dump_json(indent=2), encoding="utf-8", newline="\n")
    save_manifest(paths, {"run_id": run_id, "scenarios": [s.id for s in scenarios], "seeds": seeds})

    ui.say()
    render_report(report)
    ui.say()
    ui.info(f"기록: {paths.dir}")
    ui.info(f"{t('common.next_step')}: edu-agent improve  (또는 edu-agent calibrate)")


def _regrade(project: Project, spec, run_id: str, *, no_llm: bool, mock: bool) -> None:
    """Re-score a stored run without calling the tutor again (τ²-bench pattern)."""
    from edu_agent.evaluator.judge import Judge
    from edu_agent.evaluator.runner import EvaluationInput, evaluate
    from edu_agent.report.console import render_report
    from edu_agent.storage.jsonl import RunPaths, load_run

    if not run_id:
        ui.die("다시 채점할 실행 기록이 없습니다.", command="edu-agent test")
    paths = RunPaths(project.runs_dir, run_id)
    traces = load_run(paths)
    if not traces:
        ui.die(f"'{run_id}' 기록을 찾을 수 없습니다.")

    ui.header("저장된 대화를 다시 채점합니다", f"{run_id} · 대화 {len(traces)}개")
    ui.note("튜터 모델을 다시 호출하지 않으므로 비용이 들지 않습니다.")

    judge_provider = _provider(project, role="judge", no_llm=no_llm, mock=mock)
    judge = Judge(judge_provider, overlay=_judge_overlay(project)) if judge_provider else None
    report = evaluate(
        EvaluationInput(spec=spec, traces=traces, judge=judge, run_id=run_id,
                        project=project.config.name)
    )
    _attach_calibration(project, report)
    ui.say()
    render_report(report)


def _judge_overlay(project: Project):
    """The rubric layer this project's own human ratings produced, if any."""
    from edu_agent.evaluator.judge_tuning import OVERLAY_NAME, load_overlay

    return load_overlay(project.evals_dir / OVERLAY_NAME)


def _attach_calibration(project: Project, report) -> None:
    from edu_agent.evaluator.calibration import compute_calibration, load_ratings

    ratings = load_ratings(project.evals_dir / "human_ratings.json")
    if not ratings:
        return
    judge_labels = {
        (e.session_id, e.turn_index, c.metric): c.label
        for c in report.checks
        for e in c.evidence
    }
    stored = _stored_judge_labels(project)
    report.calibration = compute_calibration(
        ratings, stored or judge_labels, threshold=project.config.evaluation.calibration_threshold
    )
    overlay = _judge_overlay(project)
    report.calibration.overlay_version = overlay.version if overlay else 0


def _stored_judge_labels(project: Project) -> dict:
    """Labels ``calibrate --submit`` collected on exactly the rated turns."""
    import json

    from edu_agent.schemas.evaluation import Label

    path = project.evals_dir / "judge_labels.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    labels = {}
    for key, value in raw.items():
        session, turn, metric = key.rsplit("|", 2)
        try:
            labels[(session, int(turn), metric)] = Label(value)
        except ValueError:
            continue
    return labels


# --- calibrate ------------------------------------------------------------
@app.command()
def calibrate(
    submit: Annotated[bool, typer.Option("--submit", help="채점지를 읽어 일치도를 계산합니다")] = False,
    tune: Annotated[bool, typer.Option("--tune", help="사람 채점으로 judge 루브릭을 다듬습니다")] = False,
    n: Annotated[int, typer.Option("--n", help="채점할 표본 수")] = 20,
    run: Annotated[str, typer.Option("--run", help="대상 실행 (기본: 가장 최근)")] = "",
    no_llm: Annotated[bool, typer.Option("--no-llm", help="AI 판정을 다시 부르지 않습니다")] = False,
    mock: Annotated[bool, typer.Option("--mock", help="가짜 모델로 시험 실행합니다")] = False,
) -> None:
    """AI 판정이 믿을 만한지 사람 채점과 비교하고, 필요하면 루브릭을 다듬습니다."""
    from edu_agent.evaluator.calibration import (
        draw_samples,
        read_worksheet,
        save_ratings,
        write_worksheet,
    )
    from edu_agent.evaluator.judge import default_judge_metrics
    from edu_agent.storage.jsonl import RunPaths, latest_run, load_run

    project = _load_project()
    _load_dotenv(project)
    worksheet = project.evals_dir / "calibration.md"

    if tune:
        _tune_judge(project, run=run, no_llm=no_llm, mock=mock)
        return

    if submit:
        ratings = read_worksheet(worksheet)
        if not ratings:
            ui.die(
                "채점 결과를 읽지 못했습니다.",
                hint=f"{worksheet} 의 label: 줄에 yes / partial / no 를 적었는지 확인하세요.",
            )
        save_ratings(project.evals_dir / "human_ratings.json", ratings)
        ui.ok(f"{len(ratings)}개의 사람 채점을 저장했습니다.")
        _submit_calibration(project, ratings, run=run, no_llm=no_llm, mock=mock)
        return

    run_id = run or latest_run(project.runs_dir)
    if not run_id:
        ui.die("채점할 대화가 없습니다.", command="edu-agent test")
    traces = load_run(RunPaths(project.runs_dir, run_id))
    if not traces:
        ui.die(f"'{run_id}' 기록을 찾을 수 없습니다.")

    spec = _load_spec(project, warn_stale=False)
    metrics = default_judge_metrics([c.metric for c in spec.judge_criteria() if c.metric])[:5]
    cset = draw_samples(traces, metrics, n=n)
    path = write_worksheet(worksheet, cset)

    ui.header("judge 보정", "AI 판정을 믿기 전에 사람이 먼저 채점합니다.")
    ui.say()
    ui.note(
        "AI 판정은 교육학적 차원에서 사람과 어긋나는 경우가 많다는 것이 반복적으로 보고되었습니다. "
        "그래서 이 하네스는 사람이 채점한 결과와 비교되기 전까지 AI 점수를 '참고용'으로 표시합니다."
    )
    ui.say()
    ui.ok(f"채점지를 만들었습니다: {path}")
    ui.info("이 파일을 열어 각 항목을 채점한 뒤 'edu-agent calibrate --submit' 을 실행하세요.")


def _load_traces(project: Project, run: str):
    from edu_agent.storage.jsonl import RunPaths, latest_run, load_run

    run_id = run or latest_run(project.runs_dir) or ""
    if not run_id:
        return "", []
    return run_id, load_run(RunPaths(project.runs_dir, run_id))


def _submit_calibration(project: Project, ratings, *, run: str, no_llm: bool, mock: bool) -> None:
    """Compare human labels with judge labels on *the same* items.

    Reading the labels off the last report only works when the report happened to
    cite the turns the human rated. Asking the judge about those exact turns is
    what makes κ mean what it says.
    """
    import json

    from edu_agent.evaluator.calibration import compute_calibration
    from edu_agent.evaluator.judge import Judge
    from edu_agent.evaluator.judge_tuning import OVERLAY_NAME, judge_labels_for, load_overlay

    run_id, traces = _load_traces(project, run)
    if not traces:
        ui.info("비교할 실행 기록이 없습니다. edu-agent test 를 먼저 실행하세요.")
        return

    overlay = load_overlay(project.evals_dir / OVERLAY_NAME)
    judge_provider = _provider(project, role="judge", no_llm=no_llm, mock=mock)
    if judge_provider is not None:
        ui.info(f"같은 턴에 대해 AI 판정을 받는 중… ({len(ratings)}건)")
        judge = Judge(judge_provider, order_swap=False, overlay=overlay)
        labels = judge_labels_for(judge, traces, ratings)
        (project.evals_dir / "judge_labels.json").write_text(
            json.dumps(
                {"|".join(map(str, key)): value.value for key, value in labels.items()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
            newline="\n",
        )
    else:
        labels = _labels_from_report(project, run_id)
        if not labels:
            ui.info("저장된 AI 판정이 없어 일치도를 계산하지 못했습니다.")
            return

    calib = compute_calibration(
        ratings, labels, threshold=project.config.evaluation.calibration_threshold
    )
    calib.overlay_version = overlay.version if overlay else 0
    ui.say()
    if calib.n == 0:
        ui.warn("사람 채점과 AI 판정이 같은 항목에 대해 겹치지 않습니다.")
        ui.note("표본을 다시 뽑아 채점해 보세요: edu-agent calibrate")
        return
    ui.info(f"일치도: {calib.status_text}")
    for metric, kappa in sorted(calib.per_dimension.items(), key=lambda kv: kv[1]):
        ui.note(f"{metric}: κ = {kappa:.2f}")
    if not calib.trustworthy:
        ui.note("AI 판정 점수는 계속 참고용으로 표시됩니다. 자동 검사 결과를 우선 보세요.")
        ui.info(f"{t('common.next_step')}: edu-agent calibrate --tune")


def _labels_from_report(project: Project, run_id: str) -> dict:
    """``--no-llm`` fallback: reuse whatever the last report already decided."""
    from edu_agent.schemas.evaluation import EvaluationReport
    from edu_agent.storage.jsonl import RunPaths

    report_path = RunPaths(project.runs_dir, run_id).report
    if not report_path.exists():
        return {}
    report = EvaluationReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    return {
        (e.session_id, e.turn_index, c.metric): c.label
        for c in report.checks
        for e in c.evidence
    }


def _tune_judge(project: Project, *, run: str, no_llm: bool, mock: bool) -> None:
    """Use the human ratings to improve the judge prompt — and verify it helped."""
    from edu_agent.evaluator.calibration import load_ratings
    from edu_agent.evaluator.judge import Judge
    from edu_agent.evaluator.judge_tuning import (
        HISTORY_NAME,
        OVERLAY_NAME,
        append_history,
        load_overlay,
        save_overlay,
        tune_judge,
    )

    ratings = load_ratings(project.evals_dir / "human_ratings.json")
    if not ratings:
        ui.die(
            "사람 채점 결과가 없습니다.",
            hint="먼저 채점지를 채우고 'edu-agent calibrate --submit' 을 실행하세요.",
            command="edu-agent calibrate",
        )
    _, traces = _load_traces(project, run)
    if not traces:
        ui.die("채점의 근거가 된 대화 기록을 찾을 수 없습니다.", command="edu-agent test")

    judge_provider = _provider(project, role="judge", no_llm=no_llm, mock=mock)
    if judge_provider is None:
        ui.die("루브릭을 다듬으려면 AI 판정이 필요합니다.", hint="--no-llm 없이 실행하세요.")

    ui.header("judge 루브릭 다듬기", "사람 채점을 근거로 판정 프롬프트를 고칩니다.")
    ui.note(
        "채점의 절반으로 예시를 만들고, 나머지 절반으로 일치도가 실제로 올랐는지 확인합니다. "
        "오르지 않으면 되돌립니다."
    )
    ui.say()

    overlay_path = project.evals_dir / OVERLAY_NAME
    previous = load_overlay(overlay_path)
    judge = Judge(judge_provider, order_swap=False, overlay=previous)
    result = tune_judge(judge, ratings, traces, previous=previous)

    if result.kappa_before is not None:
        ui.info(f"다듬기 전 일치도: κ = {result.kappa_before:.2f} (검증 {result.n_holdout}건)")
    for item in result.disagreements[:3]:
        ui.say()
        ui.say(f"  [dim]{item.metric} · 턴 {item.key[1]}[/dim]")
        ui.say(f"  사람 [bold]{item.human.value}[/bold] ↔ AI [bold]{item.judge.value}[/bold]")
        if item.tutor_message:
            ui.note(f"튜터: {item.tutor_message}")

    ui.say()
    if result.accepted and result.overlay is not None:
        save_overlay(overlay_path, result.overlay)
        ui.ok(f"루브릭 v{result.overlay.version} 을 적용했습니다. {result.reason}")
        ui.note(f"무엇이 바뀌었는지: {overlay_path}")
    else:
        ui.warn(f"↩ 적용하지 않았습니다: {result.reason}")
        ui.note(
            "루브릭 문구를 고쳐도 일치도가 오르지 않는다면, 판정 기준이 이 수업의 교육적 의도와 "
            "맞는지를 사람이 다시 볼 때입니다."
        )
    append_history(project.evals_dir / HISTORY_NAME, result)


# --- improve --------------------------------------------------------------
@app.command()
def improve(
    auto: Annotated[str, typer.Option("--auto", help="off | prompt | params")] = "",
    rounds: Annotated[int, typer.Option("--rounds", help="최대 반복 횟수")] = 0,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="적용하지 않고 제안만 봅니다")] = False,
    rollback: Annotated[int, typer.Option("--rollback", help="이 버전으로 되돌립니다")] = 0,
    history: Annotated[bool, typer.Option("--history", help="변경 이력을 보여줍니다")] = False,
    no_llm: Annotated[bool, typer.Option("--no-llm", help="AI 없이 규칙 기반 제안만 사용합니다")] = False,
    mock: Annotated[bool, typer.Option("--mock", help="가짜 모델로 시험 실행합니다")] = False,
    allow_structure: Annotated[bool, typer.Option("--allow-structure",
                                                  help="행동 규칙 구조 변경도 자동 적용합니다")] = False,
) -> None:
    """평가 결과를 근거로 개선안을 제안하고, 승인한 것만 적용·재검증합니다."""
    from edu_agent.optimizer.patch import list_snapshots, revert_to
    from edu_agent.storage.jsonl import RunPaths, latest_run

    project = _load_project()
    _load_dotenv(project)

    if history:
        rows = list_snapshots(project.snapshots_dir)
        if not rows:
            ui.info("아직 변경 이력이 없습니다.")
            return
        ui.header("변경 이력")
        for row in rows:
            score = f"{row['overall']:.2f}" if row.get("overall") is not None else "—"
            ui.say(f"  v{row['version']:03d}  {row['created_at'][:16]}  종합 {score}  {row.get('note', '')}")
        ui.say()
        ui.info("되돌리려면: edu-agent improve --rollback <버전>")
        return

    if rollback:
        spec = revert_to(project.snapshots_dir, rollback)
        _write_doc(project, SPEC_DOC, spec)
        ui.ok(t("improve.rolled_back", version=rollback))
        return

    spec = _load_spec(project)
    run_id = latest_run(project.runs_dir)
    if not run_id:
        ui.die("먼저 평가를 실행해야 합니다.", command="edu-agent test")

    report_path = RunPaths(project.runs_dir, run_id).report
    if not report_path.exists():
        ui.die("평가 결과 파일이 없습니다.", command="edu-agent test")

    from edu_agent.schemas.evaluation import EvaluationReport

    baseline = EvaluationReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    _run_improve(project, spec, baseline, auto=auto, rounds=rounds, dry_run=dry_run,
                 no_llm=no_llm, mock=mock, allow_structure=allow_structure)


def _run_improve(project, spec, baseline, *, auto, rounds, dry_run, no_llm, mock, allow_structure) -> None:
    from edu_agent.evaluator.judge import Judge
    from edu_agent.evaluator.runner import EvaluationInput, evaluate
    from edu_agent.optimizer.diagnose import diagnose, failures_as_feedback
    from edu_agent.optimizer.loop import run_improve
    from edu_agent.optimizer.proposals import propose
    from edu_agent.simulator.loop import run_simulation
    from edu_agent.simulator.personas import load_personas
    from edu_agent.storage.jsonl import new_run_id

    cfg = project.config.improve
    auto_level = auto or cfg.auto_level
    max_rounds = rounds or cfg.max_rounds

    provider = _provider(project, no_llm=no_llm, mock=mock)
    judge_provider = _provider(project, role="judge", no_llm=no_llm, mock=mock)
    personas = load_personas(project.root / "personas.yaml")
    task = _first_task(project)

    ui.header("개선", f"자동 적용 범위: {auto_level}")

    diagnoses = diagnose(baseline, spec)
    if not diagnoses:
        ui.ok(t("improve.none"))
        return

    proposals = propose(
        diagnoses, spec, provider=provider, feedback=failures_as_feedback(baseline), limit=6
    )
    _show_proposals(proposals)

    if dry_run:
        ui.say()
        ui.info("--dry-run 이므로 아무것도 바꾸지 않았습니다.")
        return

    actionable = [p for p in proposals if p.patches]
    if not actionable:
        ui.say()
        ui.warn("자동으로 적용할 수 있는 변경안이 없습니다. 위 진단을 보고 직접 문서를 고쳐 주세요.")
        return

    def evaluate_fn(candidate, scenarios):
        traces, results = [], []
        run_id = new_run_id("improve")
        for sc in scenarios:
            persona = personas.get(sc.persona_id)
            if persona is None:
                continue
            for seed in range(max(1, sc.seeds)):
                result = run_simulation(
                    candidate, sc, persona, provider or _provider(project, mock=True),
                    task=task, seed=seed, run_id=run_id,
                )
                traces.append(result.trace)
                results.append(result)
        judge = Judge(judge_provider, overlay=_judge_overlay(project)) if judge_provider else None
        return evaluate(
            EvaluationInput(spec=candidate, traces=traces, results=results, judge=judge,
                            run_id=run_id, project=project.config.name)
        )

    def approve_fn(pending):
        return _ask_which(pending)

    ui.say()
    ui.info(t("improve.verifying"))
    outcome = run_improve(
        spec, baseline, evaluate_fn,
        snapshots_dir=project.snapshots_dir,
        approve_fn=approve_fn,
        provider=provider,
        max_rounds=max_rounds,
        min_improvement=cfg.min_improvement,
        auto_level=auto_level,
        allow_structure_edits=allow_structure or cfg.allow_structure_edits,
        holdout_ids=project.config.evaluation.holdout_scenarios,
    )

    ui.say()
    for rnd in outcome.rounds:
        if rnd.verdict is None:
            continue
        prefix = "[green]✔[/green]" if rnd.kept else "[yellow]↩[/yellow]"
        ui.say(f"  {prefix} {rnd.index}회차: {rnd.verdict.summary_ko()}")
        for patch in rnd.applied:
            ui.note(patch.describe())
        for reg in rnd.verdict.regressions[:3]:
            ui.note(f"[red]회귀[/red] {reg}")

    if outcome.changed:
        _write_doc(project, SPEC_DOC, outcome.spec)
        ui.say()
        ui.ok(t("improve.applied", n=len(outcome.applied_patches)))
        ui.note("되돌리려면: edu-agent improve --history")
    else:
        ui.say()
        ui.info(outcome.stopped_because or t("improve.none"))

    deferred = [d for r in outcome.rounds for d in r.deferred_to_human]
    if deferred:
        ui.say()
        ui.warn("직접 판단이 필요한 문제:")
        for d in deferred[:4]:
            ui.say(f"  · {d.title}")
            ui.note(d.detail)
            if d.suggestion:
                ui.note(f"→ {d.suggestion}")


def _show_proposals(proposals) -> None:
    ui.say()
    ui.info(t("improve.found", n=len(proposals)))
    for i, proposal in enumerate(proposals, 1):
        ui.say()
        marker = "[yellow](직접 판단 필요)[/yellow]" if proposal.needs_human else ""
        ui.say(f"  [bold][{i}] {proposal.summary or proposal.diagnosis.title}[/bold] {marker}")
        ui.note(proposal.rationale or proposal.diagnosis.detail)
        for patch in proposal.patches:
            ui.note(f"바꿀 것: {patch.describe()}")
        for ev in proposal.evidence[:1]:
            ui.note(f"근거 [턴 {ev.turn_index}] 학생: {ev.learner_message}")
            ui.note(f"                튜터: {ev.tutor_message}")


def _ask_which(proposals):
    choices = [
        ui.Choice(str(i + 1), p.summary or p.diagnosis.title, p)
        for i, p in enumerate(proposals)
    ]
    if not choices:
        return []
    picked = ui.ask_multi(t("improve.which"), choices, allow_empty=True)
    return list(picked)


# --- report ---------------------------------------------------------------
@app.command()
def report(
    run: Annotated[str, typer.Option("--run", help="대상 실행 (기본: 가장 최근)")] = "",
    out: Annotated[str, typer.Option("--out", help="저장 위치")] = "",
    final: Annotated[bool, typer.Option("--final", help="제출용 최종 보고서")] = False,
) -> None:
    """제출용 보고서를 만듭니다."""
    from edu_agent.report.markdown import build_report
    from edu_agent.storage.jsonl import RunPaths, latest_run

    project = _load_project()
    spec = _load_spec(project, warn_stale=False)
    run_id = run or latest_run(project.runs_dir)

    evaluation = None
    if run_id:
        report_path = RunPaths(project.runs_dir, run_id).report
        if report_path.exists():
            from edu_agent.schemas.evaluation import EvaluationReport

            evaluation = EvaluationReport.model_validate_json(report_path.read_text(encoding="utf-8"))

    docs = {}
    for slot in INPUT_DOCS:
        if project.exists(slot):
            model, _ = _read_doc(project, slot)
            docs[slot.key] = model

    text = build_report(project, spec, evaluation, docs, final=final)
    target = Path(out) if out else project.root / "report.md"
    target.write_text(text, encoding="utf-8", newline="\n")
    ui.ok(f"보고서를 만들었습니다: {target}")
    if evaluation is None:
        ui.note("평가 결과가 없어 설계 부분만 담겼습니다. edu-agent test 를 먼저 실행하세요.")


# --- view -----------------------------------------------------------------
@app.command()
def view(
    run: Annotated[str, typer.Option("--run", help="대상 실행 (기본: 가장 최근)")] = "",
    session: Annotated[str, typer.Option("--session", help="특정 대화만 봅니다")] = "",
    failures: Annotated[bool, typer.Option("--failures", help="문제가 있었던 턴만 봅니다")] = False,
) -> None:
    """저장된 대화 기록을 봅니다."""
    from edu_agent.storage.jsonl import RunPaths, latest_run, list_runs, load_run

    project = _load_project()
    if not run:
        runs = list_runs(project.runs_dir)
        if not runs:
            ui.die("실행 기록이 없습니다.", command="edu-agent test")
        if len(runs) > 1 and not session:
            ui.header("실행 기록")
            for r in runs[:10]:
                ui.say(f"  {r}")
            ui.say()
            ui.info("특정 실행을 보려면: edu-agent view --run <이름>")
        run = latest_run(project.runs_dir) or runs[0]

    traces = load_run(RunPaths(project.runs_dir, run))
    if session:
        traces = [t_ for t_ in traces if t_.session_id.startswith(session)]
    if not traces:
        ui.die(f"'{run}' 에서 대화를 찾지 못했습니다.")

    ui.header(f"대화 기록 · {run}", f"{len(traces)}개")
    for trace in traces:
        ui.say()
        ui.say(f"[bold]{trace.scenario_id or '—'} · {trace.persona_id or '—'} · seed {trace.seed}[/bold]")
        for turn in trace.turns:
            if failures and not (turn.blocked_gates or turn.leaked_answer):
                continue
            ui.say(f"  [dim]턴 {turn.turn_index}[/dim]")
            ui.say(f"  학생  {turn.learner_message}")
            ui.say(f"  튜터  {turn.tutor_message}")
            marks = []
            if turn.declared_action:
                marks.append(turn.declared_action.value)
            if turn.leaked_answer:
                marks.append(f"[red]정답 노출: {turn.leak_evidence}[/red]")
            for d in turn.blocked_gates:
                marks.append(f"[yellow]{d.gate_id} 차단: {d.reason}[/yellow]")
            if marks:
                ui.note(" · ".join(marks))


# --- build ----------------------------------------------------------------
@app.command()
def build(
    out: Annotated[str, typer.Option("--out", help="내보낼 위치")] = "",
    target: Annotated[str, typer.Option("--target", help="cli | fastapi (비우면 03 문서를 따릅니다)")] = "",
) -> None:
    """독립 실행 프로젝트로 내보냅니다 (선택 기능)."""
    from edu_agent.builder import TARGETS, export

    project = _load_project()
    spec = _load_spec(project, warn_stale=False)
    target = (target or _target_from_technical(project)).lower()
    if target not in TARGETS:
        ui.die(
            f"'{target}' 내보내기는 지원하지 않습니다.",
            hint=f"가능한 값: {', '.join(sorted(TARGETS))}",
        )

    destination = Path(out) if out else project.root / "generated-agent"
    export(target, project, spec, destination)
    ui.ok(f"내보냈습니다 ({target}): {destination}")
    ui.note("이 폴더의 README.md 를 읽고 실행하세요.")
    ui.note("설계를 바꾸려면 이 폴더가 아니라 원래 문서를 고치고 다시 내보내세요.")


def _target_from_technical(project: Project) -> str:
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


def _entry() -> None:
    try:
        app()
    except ui.Abort as exc:
        ui.render_abort(exc)
        raise SystemExit(1) from None
    except ui.UserAbort:
        ui.say()
        ui.info(t("common.cancelled"))
        raise SystemExit(0) from None
    except Exception as exc:
        if _VERBOSE:
            raise
        ui.err_console.print(f"[red]✘[/red] 예상하지 못한 문제가 생겼습니다: {exc}")
        ui.err_console.print("  [dim]자세히 보려면 --verbose 를 붙여 다시 실행하세요.[/dim]")
        raise SystemExit(1) from None


if __name__ == "__main__":  # pragma: no cover
    _entry()
