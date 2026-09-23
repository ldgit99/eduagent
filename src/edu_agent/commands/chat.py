"""Talking to the agent: in a browser, or against a simulated student.

The terminal loop stays in ``cli.py`` because it is a handful of lines around a
prompt. These two are not: serving a page until Ctrl+C and driving a persona
through a scenario are workflows with their own lifecycle, and both need to be
runnable from a test without a terminal.
"""

from __future__ import annotations

from edu_agent import ui
from edu_agent.commands import context
from edu_agent.i18n import t


def run_web(project, spec, provider, task, *, port: int, open_browser: bool) -> None:
    """Serve the chat in a browser until Ctrl+C, then save what was said."""
    import webbrowser

    from edu_agent.runtime.loop import AgentRuntime
    from edu_agent.storage.jsonl import RunPaths, new_run_id, save_session
    from edu_agent.web import ChatServer, ChatSession

    run_id = new_run_id("web")

    def build_runtime() -> AgentRuntime:
        runtime = AgentRuntime(
            spec=spec, provider=provider, task=task, tools=context.tool_runtime(project, spec, task)
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


def run_with_persona(project, spec, provider, persona_id, task, turns, mock) -> None:
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
    student_provider = context.provider(project, role="student", mock=mock) if mock else None

    run_id = new_run_id("persona")
    result = run_simulation(
        spec, scenario, target, provider,
        student_provider=student_provider, task=task, run_id=run_id, max_turns=turns,
        tools=context.tool_runtime(project, spec, task),
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
            marks.append(context.tool_line(call))
        if marks:
            ui.note(" · ".join(marks))
        ui.say()

    paths = RunPaths(project.runs_dir, run_id)
    save_session(paths, result.trace)
    ui.ok(f"기록: {paths.dir}")

