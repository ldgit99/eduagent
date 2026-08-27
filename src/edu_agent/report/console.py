"""Terminal rendering of an evaluation report.

Ordering is deliberate: the **evidence comes before the number**. A student who
sees "4.2 / 5" learns nothing; a student who sees the turn where their tutor handed
over the answer learns what to change. Scores are the summary, not the message.
"""

from __future__ import annotations

from edu_agent import ui
from edu_agent.i18n import t
from edu_agent.schemas.common import CheckType
from edu_agent.schemas.evaluation import (
    SCORED_DIMENSIONS,
    CheckResult,
    EvaluationReport,
    Label,
)


def render_report(report: EvaluationReport, *, max_failures: int = 4) -> None:
    ui.header(
        t("test.title"),
        f"{report.n_scenarios}개 시나리오 · 학생 {report.n_personas}종 · 대화 {report.n_sessions}개",
    )

    _render_scores(report)
    _render_key_numbers(report)
    _render_compliance(report)
    _render_failures(report, max_failures)
    _render_simulator(report)
    _render_notes(report)


def _render_scores(report: EvaluationReport) -> None:
    ui.say()
    width = max(len(d.label_ko) for d in report.dimensions) if report.dimensions else 12
    for dim in report.dimensions:
        if dim.dimension not in SCORED_DIMENSIONS:
            continue
        if dim.n_checks == 0:
            ui.say(f"  {dim.label_ko.ljust(width)}  [dim]검사 항목 없음[/dim]")
            continue
        bar = ui.score_bar(dim.score_0_5)
        judge_mark = "" if dim.deterministic_share >= 0.999 else " [dim]*[/dim]"
        ui.console.print(
            f"  {dim.label_ko.ljust(width)}  ", bar, f"  {dim.score_0_5:.2f} / 5{judge_mark}", sep=""
        )

    tech = report.technical
    label = f"[green]{t('test.pass_')}[/green]" if tech.passed else f"[red]{t('test.fail')}[/red]"
    ui.say(f"  {'기술적 안정성'.ljust(width)}  {label}   [dim](오류 {tech.errors} · 재생성 {tech.gate_regenerations} · 대체 {tech.fallbacks})[/dim]")

    ui.say()
    ui.say(f"  [bold]{t('test.overall').ljust(width)}  {report.overall:.2f} / 5[/bold]")

    has_judge = any(c.check is CheckType.LLM_JUDGE for c in report.checks)
    if has_judge:
        ui.note("* 표시는 AI 판정이 섞인 항목입니다.")
        ui.say(f"  [dim]판정 신뢰도: {report.calibration.status_text}[/dim]")


def _render_key_numbers(report: EvaluationReport) -> None:
    ui.say()
    rows: list[tuple[str, str]] = []

    leak = report.leakage_rate
    leak_text = "없음" if leak == 0 else f"[red]{leak:.0%} 의 대화[/red]"
    if report.first_leak_turns:
        leak_text += f" (가장 이른 턴: {min(report.first_leak_turns)})"
    rows.append(("정답 노출", leak_text))

    onset = report.mean_collapse_onset()
    rows.append(
        (
            "규칙이 무너진 시점",
            "없음" if onset is None else f"평균 {onset:.1f}번째 턴 ({len(report.collapse_onsets)}개 대화)",
        )
    )
    rows.append(
        (
            "압박에 굴복",
            "없음" if report.pressure_capitulation_rate == 0
            else f"[red]{report.pressure_capitulation_rate:.0%}[/red]",
        )
    )

    ls = report.learner_side
    if ls.sessions:
        rows.append(("학습자가 자기 생각을 말함", f"{ls.reasoning_elicited_sessions}/{ls.sessions} 대화"))
        rows.append(("학습자가 해결함", f"{ls.solved_sessions}/{ls.sessions} 대화"))
        if ls.solved_sessions:
            rows.append(("해결 후 과정을 설명함", f"{ls.explained_process_sessions}/{ls.solved_sessions}"))

    ui.key_value(rows)


def _render_compliance(report: EvaluationReport) -> None:
    imperfect = [c for c in report.compliance if c.rate < 0.999 and c.turns_applicable]
    if not imperfect:
        if report.compliance:
            ui.say()
            ui.ok(f"정책 게이트 {len(report.compliance)}개 모두 100% 준수")
        return

    ui.say()
    ui.info("[bold]지켜지지 않은 규칙[/bold]")
    for item in imperfect[:5]:
        ui.say(
            f"  {item.gate_id}  {item.rate:.0%}  [dim]{item.constraint_text}[/dim]"
            + (f"  [dim](처음 위반: {item.first_violation_turn}턴)[/dim]" if item.first_violation_turn is not None else "")
        )


def _render_failures(report: EvaluationReport, limit: int) -> None:
    failures = [c for c in report.failures() if c.evidence or c.label is Label.NO]
    if not failures:
        return

    ui.say()
    ui.info("[bold]무엇이 왜 문제였는지[/bold]")
    for check in failures[:limit]:
        ui.say()
        _render_failure(check)


def _render_failure(check: CheckResult) -> None:
    tag = "FAIL" if check.label is Label.NO else "일부"
    colour = "red" if check.label is Label.NO else "yellow"
    kind = "자동 검사" if check.check is CheckType.DETERMINISTIC else "AI 판정"
    ui.say(f"  [{colour}]{tag}[/{colour}]  {check.criterion_id} · {check.metric}  [dim]({kind})[/dim]")
    ui.note(check.rationale)
    for ev in check.evidence[:2]:
        where = f"{ev.scenario_id or '—'} · {ev.persona_id or '—'} · 턴 {ev.turn_index}"
        ui.say(f"      [dim]{where}[/dim]")
        ui.say(f"      학생  {ev.learner_message}")
        ui.say(f"      튜터  {ev.tutor_message}")
        if ev.note:
            ui.say(f"      [dim]{ev.note}[/dim]")


def _render_simulator(report: EvaluationReport) -> None:
    health = report.simulator_health
    if not health.warnings:
        return
    ui.say()
    ui.warn("[bold]시뮬레이션 학생 점검[/bold]")
    ui.note("아래는 에이전트가 아니라 '테스트 도구' 자체의 문제입니다.")
    for warning in health.warnings:
        ui.say(f"  · {warning}")


def _render_notes(report: EvaluationReport) -> None:
    ui.say()
    for note in report.notes:
        ui.note(note)
    ui.say()
    ui.console.print(f"[dim]{t('test.limitation').strip()}[/dim]")
