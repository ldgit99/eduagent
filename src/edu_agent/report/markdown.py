"""The submission report (plan v2 §18.5).

What a student hands in. It carries the design, the traceability chain, the
evidence behind each score, the improvement history — and, always, the limitation
notice: simulated learners screen a design, they do not demonstrate learning.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from edu_agent.documents.render import render_document
from edu_agent.optimizer.patch import list_snapshots
from edu_agent.schemas.agent import AgentSpec
from edu_agent.schemas.common import CheckType
from edu_agent.schemas.evaluation import SCORED_DIMENSIONS, EvaluationReport, Label


def limitation() -> str:
    """The caveat every report carries (plan v2 §4.5).

    In a template because it is the most carefully worded paragraph the harness
    produces, it differs by language, and an instructor may want to adjust it for
    their course — none of which should require editing Python.
    """
    return render_document("report_limitation.md.j2").strip()


def build_report(
    project,
    spec: AgentSpec,
    evaluation: EvaluationReport | None,
    docs: dict[str, Any],
    *,
    final: bool = False,
) -> str:
    parts = [
        _header(project, spec, final),
        _design(docs),
        _principles(docs),
        _traceability(spec),
        _evaluation(evaluation),
        _evidence(evaluation),
        _improvements(project),
        _simulator(evaluation),
        limitation(),
    ]
    return "\n\n".join(p for p in parts if p).strip() + "\n"


def _header(project, spec: AgentSpec, final: bool) -> str:
    now = datetime.now(UTC).astimezone().strftime("%Y-%m-%d")
    title = "최종 보고서" if final else "중간 보고서"
    return (
        f"# {project.config.name} · {title}\n\n"
        f"- 작성일: {now}\n"
        f"- 프로젝트: {project.config.title or project.config.name}\n"
        f"- 에이전트 역할: {spec.agent_role or '—'}\n"
        f"- 대상 학습자: {spec.target_learner or '—'}"
    )


def _design(docs: dict[str, Any]) -> str:
    ed = docs.get("educational")
    if ed is None:
        return ""
    lines = ["## 1. 교육 설계", "", f"**해결하려는 문제**  \n{ed.problem.core_problem or '—'}", ""]
    if ed.objectives:
        lines.append("**학습목표**")
        lines.extend(f"- {o.id}: {o.statement}" for o in ed.objectives)
        lines.append("")
    if ed.expected_support.must_do:
        lines.append("**AI가 반드시 해야 하는 행동**")
        lines.extend(f"- {m}" for m in ed.expected_support.must_do)
        lines.append("")
    if ed.expected_support.must_not_do:
        lines.append("**AI가 해서는 안 되는 행동**")
        lines.extend(f"- {m}" for m in ed.expected_support.must_not_do)
    return "\n".join(lines).strip()


def _principles(docs: dict[str, Any]) -> str:
    pr = docs.get("principles")
    if pr is None:
        return ""
    lines = ["## 2. 설계원리와 실행 규칙", ""]
    for p in pr.confirmed_principles():
        lines.append(f"### {p.id}. {p.title or p.name}")
        lines.append("")
        if p.description:
            lines.append(p.description.strip())
            lines.append("")
        if p.basis:
            lines.append("근거: " + "; ".join(p.basis))
            lines.append("")
        for rule in p.rules:
            triggers = ", ".join(t.value for t in rule.triggers)
            lines.append(f"- **{rule.id}** ({triggers})")
            for step in rule.ladder:
                cond = f" — 조건: `{step.when}`" if step.when else ""
                lines.append(f"  - {step.level}단계: `{step.label}`{cond}")
            for constraint in rule.constraints:
                mark = "**[실행 중 강제]**" if constraint.gateable else "[안내문]"
                lines.append(f"  - {mark} {constraint.text or constraint.kind.value}")
        lines.append("")
    return "\n".join(lines).strip()


def _traceability(spec: AgentSpec) -> str:
    if not spec.traceability:
        return ""
    lines = [
        "## 3. 추적성",
        "",
        "설계원리가 어떤 행동·규칙·검사·시나리오로 이어졌는지 보여줍니다.",
        "시나리오까지 이어지지 않은 원리는 검증되지 않습니다.",
        "",
        "| 원리 | 행동 | 게이트 | 검사 기준 | 시나리오 | 완결 |",
        "|---|---|---|---|---|---|",
    ]
    for link in spec.traceability:
        lines.append(
            f"| {link.principle_id} | {', '.join(link.behavior_ids) or '—'} "
            f"| {', '.join(link.gate_ids) or '—'} | {', '.join(link.criterion_ids) or '—'} "
            f"| {', '.join(link.scenario_ids) or '—'} | {'✔' if link.complete else '⚠️'} |"
        )
    untraced = spec.untraced_principles()
    if untraced:
        lines += ["", f"> ⚠️ 검증되지 않은 원리: {', '.join(untraced)}"]
    return "\n".join(lines)


def _evaluation(report: EvaluationReport | None) -> str:
    if report is None:
        return "## 4. 평가\n\n아직 평가를 실행하지 않았습니다. `edu-agent test` 를 실행하세요."

    lines = [
        "## 4. 평가 결과",
        "",
        f"- 시나리오 {report.n_scenarios}개 · 학생 {report.n_personas}종 · 대화 {report.n_sessions}개",
        f"- 판정 신뢰도: {report.calibration.status_text}",
        "",
        "| 평가 영역 | 점수 | 검사 수 | 자동 검사 비율 |",
        "|---|---|---|---|",
    ]
    for dim in report.dimensions:
        if dim.dimension not in SCORED_DIMENSIONS:
            continue
        score = f"{dim.score_0_5:.2f} / 5" if dim.n_checks else "—"
        lines.append(
            f"| {dim.label_ko} | {score} | {dim.n_checks} | {dim.deterministic_share:.0%} |"
        )
    tech = report.technical
    lines.append(f"| 기술적 안정성 | {'PASS' if tech.passed else 'FAIL'} | — | — |")
    lines += ["", f"**종합: {report.overall:.2f} / 5**", ""]

    lines += [
        "### 핵심 수치",
        "",
        f"- 정답 노출: {'없음' if report.leakage_rate == 0 else f'{report.leakage_rate:.0%} 의 대화'}",
        f"- 압박에 굴복: {report.pressure_capitulation_rate:.0%}",
    ]
    onset = report.mean_collapse_onset()
    lines.append(f"- 규칙이 무너진 시점: {'없음' if onset is None else f'평균 {onset:.1f}번째 턴'}")

    ls = report.learner_side
    if ls.sessions:
        lines += [
            f"- 학습자가 자기 생각을 말한 대화: {ls.reasoning_elicited_sessions}/{ls.sessions}",
            f"- 학습자가 해결한 대화: {ls.solved_sessions}/{ls.sessions}",
        ]

    imperfect = [c for c in report.compliance if c.rate < 0.999 and c.turns_applicable]
    if imperfect:
        lines += ["", "### 지켜지지 않은 규칙", "", "| 규칙 | 준수율 | 내용 |", "|---|---|---|"]
        lines.extend(f"| {c.gate_id} | {c.rate:.0%} | {c.constraint_text} |" for c in imperfect)
    return "\n".join(lines)


def _evidence(report: EvaluationReport | None) -> str:
    if report is None:
        return ""
    failures = [c for c in report.failures() if c.evidence]
    if not failures:
        return ""

    lines = ["## 5. 근거", "", "점수만으로는 무엇을 고쳐야 할지 알 수 없으므로 실제 대화를 함께 싣습니다.", ""]
    for check in failures[:6]:
        kind = "자동 검사" if check.check is CheckType.DETERMINISTIC else "AI 판정"
        tag = "FAIL" if check.label is Label.NO else "일부 충족"
        lines += [
            f"### {tag} · {check.criterion_id} ({check.metric})",
            "",
            f"- 검사 방식: {kind}",
            f"- 판정 근거: {check.rationale}",
            "",
        ]
        for ev in check.evidence[:2]:
            lines += [
                f"> **{ev.scenario_id or '—'} · {ev.persona_id or '—'} · 턴 {ev.turn_index}**  ",
                f"> 학생: {ev.learner_message}  ",
                f"> 튜터: {ev.tutor_message}",
            ]
            if ev.note:
                lines.append(f"> ({ev.note})")
            lines.append("")
    return "\n".join(lines).strip()


def _improvements(project) -> str:
    rows = list_snapshots(project.snapshots_dir)
    if len(rows) <= 1:
        return ""
    lines = [
        "## 6. 개선 이력",
        "",
        "무엇을 왜 바꿨는지, 그리고 그 변경이 실제로 나아졌는지 기록합니다.",
        "",
        "| 버전 | 시각 | 종합 | 변경 내용 |",
        "|---|---|---|---|",
    ]
    for row in rows:
        score = f"{row['overall']:.2f}" if row.get("overall") is not None else "—"
        lines.append(f"| v{row['version']:03d} | {row['created_at'][:16]} | {score} | {row.get('note', '')} |")
    return "\n".join(lines)


def _simulator(report: EvaluationReport | None) -> str:
    if report is None:
        return ""
    health = report.simulator_health
    lines = [
        "## 7. 시뮬레이션 학생 점검",
        "",
        "평가 도구 자체가 타당했는지 확인합니다. 시뮬레이션 학생이 실제 학생과 너무 다르면",
        "위의 결과를 그대로 믿을 수 없습니다.",
        "",
        f"- 턴당 평균 발화 길이: {health.mean_words_per_turn} 단어",
        f"- 시뮬레이터 제약 위반: {health.constraint_violations}회",
        f"- 무관한 피드백에 오개념을 버린 비율: {health.unfaithful_flip_rate:.0%}",
    ]
    if health.warnings:
        lines += ["", "**주의**"] + [f"- {w}" for w in health.warnings]
    return "\n".join(lines)
