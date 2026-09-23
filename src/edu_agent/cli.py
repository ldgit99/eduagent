"""``edu-agent`` command line interface.

Command set (plan v2 §2)::

    doctor init status review compile run test calibrate improve report build view

This file is the *shell*: it declares the arguments, calls one workflow in
:mod:`edu_agent.commands`, and prints the result. The workflows live there so
they can be read — and driven by a test — without argument parsing around them.

Design rules that apply to every command:

* Never show a traceback to a student. Failures raise :class:`ui.Abort` with a
  message, a hint and the command to run next, and :func:`run_cli` renders it the
  same way however the CLI was started.
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

from edu_agent import commands, ui
from edu_agent._version import __version__
from edu_agent.i18n import set_language, t
from edu_agent.project import Project, ProjectNotFound, create_project, find_project
from edu_agent.project.layout import DOC_FILES, INPUT_DOCS, SPEC_DOC, slot_for

app = typer.Typer(
    name="edu-agent",
    help="교육용 AI 에이전트를 설계·실행·검증하는 하네스",
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)

_VERBOSE = False


# --- shared helpers -------------------------------------------------------




















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

    commands.context.load_dotenv(project)

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

    commands.diagnose.report_sandbox(project)

    ui.say()
    ui.info(t("doctor.all_ok"))




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
        commands.review.run_review(project, DOC_FILES[0], no_llm=True, mock=False)
    else:
        ui.info(t("init.next"))


# --- status ---------------------------------------------------------------
@app.command()
def status() -> None:
    """4개 문서의 진행 상태와 다음에 할 일을 보여줍니다."""
    from edu_agent.documents.io import detect_drift, load_document
    from edu_agent.schemas.common import DocumentStatus

    project = commands.context.load_project()
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
        current = commands.context.spec_hashes(project)
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
    from_file: Annotated[str, typer.Option("--from", help="설계원리를 적어 둔 Markdown 파일 (02 전용)")] = "",
) -> None:
    """문서를 작성하거나 검토합니다. 질문 → 확인 → 저장."""
    project = commands.context.load_project()
    commands.context.load_dotenv(project)

    if which:
        slot = slot_for(which)
    else:
        slot = next((s for s in INPUT_DOCS if not project.exists(s)), INPUT_DOCS[0])
    if slot is SPEC_DOC:
        ui.die("04 는 직접 작성하지 않습니다.", command="edu-agent compile")

    source = Path(from_file).expanduser() if from_file else None
    if source is not None and slot.key != "principles":
        ui.die("--from 은 02 설계원리에만 쓸 수 있습니다.", command="edu-agent review 02 --from " + from_file)

    commands.review.run_review(project, slot, no_llm=no_llm, mock=mock, source=source)




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

    project = commands.context.load_project()
    commands.context.load_dotenv(project)

    for slot in INPUT_DOCS:
        if not project.exists(slot):
            ui.die(
                t("errors.doc_missing", doc=slot.filename, n=f"{slot.index:02d}"),
                command=f"edu-agent review {slot.index:02d}",
            )

    educational, _ = commands.context.read_doc(project, DOC_FILES[0])
    principles, _ = commands.context.read_doc(project, DOC_FILES[1])
    technical, _ = commands.context.read_doc(project, DOC_FILES[2])

    ui.header(t("compile.running"))
    # The compiler's core is deterministic; the model only assists.
    provider = commands.context.provider(project, no_llm=no_llm, mock=mock, optional=True)

    result = compile_spec(
        educational,  # type: ignore[arg-type]
        principles,  # type: ignore[arg-type]
        technical,  # type: ignore[arg-type]
        provider=provider,
        input_hashes=commands.context.spec_hashes(project),
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
    saved = commands.context.write_doc(project, SPEC_DOC, spec)

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

    project = commands.context.load_project()
    commands.context.load_dotenv(project)
    spec = commands.context.load_spec(project)

    if show_prompt:
        from edu_agent.runtime.prompt import build_system_prompt

        ui.panel(build_system_prompt(spec), title="시스템 프롬프트", style="blue")
        if not persona:
            return

    provider = commands.context.provider(project, mock=mock)
    assert provider is not None
    task = commands.context.first_task(project)

    if persona:
        commands.chat.run_with_persona(project, spec, provider, persona, task, turns, mock)
        return

    if web:
        commands.chat.run_web(project, spec, provider, task, port=port, open_browser=open_browser)
        return

    ui.header(t("run.banner", name=project.config.name))
    ui.note(t("run.privacy"))
    ui.say()

    runtime = AgentRuntime(
        spec=spec, provider=provider, task=task, tools=commands.context.tool_runtime(project, spec, task)
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
            ui.note(commands.context.tool_line(call))
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

    project = commands.context.load_project()
    commands.context.load_dotenv(project)
    spec = commands.context.load_spec(project)

    if regrade:
        commands.evaluate.regrade(project, spec, regrade if regrade != "latest" else (latest_run(project.runs_dir) or ""),
                 no_llm=no_llm, mock=mock)
        return

    from edu_agent.evaluator.judge import Judge
    from edu_agent.evaluator.runner import EvaluationInput, evaluate
    from edu_agent.simulator.loop import run_simulation
    from edu_agent.simulator.personas import load_personas

    provider = commands.context.provider(project, mock=mock)
    assert provider is not None
    student_provider = (
        commands.context.provider(project, role="student", mock=mock) if llm_student else None
    )
    judge_provider = commands.context.provider(project, role="judge", no_llm=no_llm, mock=mock)

    personas = load_personas(project.root / "personas.yaml")
    task = commands.context.first_task(project)
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
                tools=commands.context.tool_runtime(project, spec, task),
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
            overlay=commands.evaluate.judge_overlay(project),
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
    commands.evaluate.attach_calibration(project, report)

    paths.report.write_text(report.model_dump_json(indent=2), encoding="utf-8", newline="\n")
    save_manifest(paths, {"run_id": run_id, "scenarios": [s.id for s in scenarios], "seeds": seeds})

    ui.say()
    render_report(report)
    ui.say()
    ui.info(f"기록: {paths.dir}")
    ui.info(f"{t('common.next_step')}: edu-agent improve  (또는 edu-agent calibrate)")










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

    project = commands.context.load_project()
    commands.context.load_dotenv(project)
    worksheet = project.evals_dir / "calibration.md"

    if tune:
        commands.calibrate.tune_judge(project, run=run, no_llm=no_llm, mock=mock)
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
        commands.calibrate.submit_calibration(project, ratings, run=run, no_llm=no_llm, mock=mock)
        return

    run_id = run or latest_run(project.runs_dir)
    if not run_id:
        ui.die("채점할 대화가 없습니다.", command="edu-agent test")
    traces = load_run(RunPaths(project.runs_dir, run_id))
    if not traces:
        ui.die(f"'{run_id}' 기록을 찾을 수 없습니다.")

    spec = commands.context.load_spec(project, warn_stale=False)
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

    project = commands.context.load_project()
    commands.context.load_dotenv(project)

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
        commands.context.write_doc(project, SPEC_DOC, spec)
        ui.ok(t("improve.rolled_back", version=rollback))
        return

    spec = commands.context.load_spec(project)
    run_id = latest_run(project.runs_dir)
    if not run_id:
        ui.die("먼저 평가를 실행해야 합니다.", command="edu-agent test")

    report_path = RunPaths(project.runs_dir, run_id).report
    if not report_path.exists():
        ui.die("평가 결과 파일이 없습니다.", command="edu-agent test")

    from edu_agent.schemas.evaluation import EvaluationReport

    baseline = EvaluationReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    commands.improve.run_improve(project, spec, baseline, auto=auto, rounds=rounds, dry_run=dry_run,
                 no_llm=no_llm, mock=mock, allow_structure=allow_structure)








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

    project = commands.context.load_project()
    spec = commands.context.load_spec(project, warn_stale=False)
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
            model, _ = commands.context.read_doc(project, slot)
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

    project = commands.context.load_project()
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

    project = commands.context.load_project()
    spec = commands.context.load_spec(project, warn_stale=False)
    target = (target or commands.export.target_from_technical(project)).lower()
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




def run_cli(argv: list[str] | None = None) -> int:
    """Run the CLI and turn any failure into a message plus an exit code.

    Every way of starting the harness goes through here — the console script,
    ``python -m edu_agent.cli``, and the tests. Until now the friendly rendering
    lived in the console-script wrapper alone, so a test invoking the app saw a
    blank screen where a student sees an explanation, and the explanations went
    untested as a result.
    """
    try:
        app(args=argv, standalone_mode=False)
    except ui.Abort as exc:
        ui.render_abort(exc)
        return 1
    except ui.UserAbort:
        ui.say()
        ui.info(t("common.cancelled"))
        return 0
    except typer.Exit as exc:
        return int(exc.exit_code)
    except SystemExit as exc:  # --help and friends
        return int(exc.code or 0)
    except Exception as exc:
        if _VERBOSE:
            raise
        # Usage errors know how to print themselves. Duck-typed rather than
        # imported: typer vendors click, so there is no top-level ``click`` here.
        show = getattr(exc, "show", None)
        if callable(show) and hasattr(exc, "exit_code"):
            show()
            return int(exc.exit_code)
        ui.err_console.print(f"[red]✘[/red] 예상하지 못한 문제가 생겼습니다: {exc}")
        ui.err_console.print("  [dim]자세히 보려면 --verbose 를 붙여 다시 실행하세요.[/dim]")
        return 1
    return 0


def _entry() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":  # pragma: no cover
    _entry()
