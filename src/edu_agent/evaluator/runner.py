"""Running every check over every session and aggregating into nine dimensions.

Aggregation rules worth knowing:

* A criterion is scored **per session** and averaged, so one bad persona cannot be
  hidden by nine good ones — and the failing sessions stay attached as evidence.
* Deterministic and judge results live in the same list but are distinguishable
  (``deterministic_share`` per dimension), because a dimension carried entirely by
  an uncalibrated judge deserves to be read differently.
* Technical stability is pass/fail. Turning "it crashed twice" into 4.2/5 would be
  worse than useless.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from edu_agent.evaluator.deterministic import BASELINE_CHECKS, run_check
from edu_agent.evaluator.judge import Judge, default_judge_metrics
from edu_agent.evaluator.registry import dimension_for_metric
from edu_agent.schemas.agent import AgentSpec
from edu_agent.schemas.common import CheckType
from edu_agent.schemas.evaluation import (
    SCORED_DIMENSIONS,
    CheckResult,
    ConstraintCompliance,
    DimensionScore,
    EvaluationReport,
    Evidence,
    Label,
    LearnerSideMetrics,
    SimulatorHealth,
    TechnicalHealth,
)
from edu_agent.schemas.trace import SessionTrace
from edu_agent.simulator.loop import SimulationResult
from edu_agent.utils.text import truncate


@dataclass(slots=True)
class EvaluationInput:
    """Everything ``evaluate`` needs. Sessions may come from a fresh run or disk."""

    spec: AgentSpec
    traces: list[SessionTrace]
    results: list[SimulationResult] = field(default_factory=list)
    judge: Judge | None = None
    run_id: str = ""
    project: str = ""
    seeds: int = 1
    calibration_threshold: float = 0.7


def evaluate(inp: EvaluationInput) -> EvaluationReport:
    """Score every session and aggregate."""
    spec = inp.spec
    report = EvaluationReport(
        run_id=inp.run_id,
        project=inp.project,
        spec_hash=spec.meta.content_hash or "",
        n_sessions=len(inp.traces),
        n_scenarios=len({t.scenario_id for t in inp.traces if t.scenario_id}),
        n_personas=len({t.persona_id for t in inp.traces if t.persona_id}),
        seeds=inp.seeds,
    )
    report.calibration.threshold = inp.calibration_threshold
    if not inp.traces:
        report.notes.append("평가할 대화가 없습니다.")
        return report

    checks: list[CheckResult] = []
    checks.extend(_deterministic_checks(spec, inp.traces))
    if inp.judge is not None:
        checks.extend(_judge_checks(spec, inp.traces, inp.judge))

    report.checks = checks
    report.dimensions = _aggregate(checks)
    report.compliance = _compliance(spec, inp.traces)
    report.learner_side = _learner_side(inp.results, inp.traces)
    report.simulator_health = _simulator_health(inp.results, inp.traces)
    report.technical = _technical(inp.traces)

    leaked = [t for t in inp.traces if t.first_leak_turn() is not None]
    report.leakage_rate = len(leaked) / len(inp.traces)
    report.first_leak_turns = [t.first_leak_turn() for t in leaked]  # type: ignore[misc]
    report.collapse_onsets = [
        o for o in (t.collapse_onset() for t in inp.traces) if o is not None
    ]
    report.pressure_capitulation_rate = _capitulation_rate(inp.traces)
    report.notes.extend(_notes(report, inp))
    return report


# --- checks ---------------------------------------------------------------
def _deterministic_checks(spec: AgentSpec, traces: list[SessionTrace]) -> list[CheckResult]:
    metrics: dict[str, str] = {m: "" for m in BASELINE_CHECKS}
    for criterion in spec.deterministic_criteria():
        if criterion.metric:
            metrics[criterion.metric] = criterion.id

    out: list[CheckResult] = []
    for metric, criterion_id in metrics.items():
        per_session: list[tuple[SessionTrace, tuple]] = []
        for trace in traces:
            outcome = run_check(metric, trace)
            if outcome is not None:
                per_session.append((trace, outcome))
        if not per_session:
            continue
        out.append(_merge_sessions(metric, criterion_id or metric, per_session))
    return out


def _merge_sessions(metric: str, criterion_id: str, per_session: list[tuple]) -> CheckResult:
    """Combine a per-session outcome into one criterion result.

    The score is the mean of session scores, but the *label* is driven by the worst
    outcome: if the tutor leaked the answer in even one conversation, "대체로 통과"
    would be the wrong headline.
    """
    labels = [outcome[0] for _, outcome in per_session]
    score = sum(label.score for label in labels) / len(labels)

    if all(label is Label.YES for label in labels):
        label = Label.YES
    elif any(label is Label.NO for label in labels):
        label = Label.NO if score < 0.75 else Label.PARTIAL
    else:
        label = Label.PARTIAL

    evidence: list[Evidence] = []
    rationales: list[str] = []
    for _, (lab, evs, rationale) in per_session:
        if lab is not Label.YES:
            evidence.extend(evs)
            if rationale:
                rationales.append(rationale)
    if not rationales:
        rationales = [per_session[0][1][2]]

    failing = sum(1 for lab in labels if lab is not Label.YES)
    summary = rationales[0]
    if failing:
        summary = f"{len(labels)}개 대화 중 {failing}개에서 문제: {summary}"

    return CheckResult(
        criterion_id=criterion_id,
        dimension=dimension_for_metric(metric),
        check=CheckType.DETERMINISTIC,
        label=label,
        score=score,
        metric=metric,
        rationale=summary,
        evidence=evidence[:5],
    )


def _judge_checks(spec: AgentSpec, traces: list[SessionTrace], judge: Judge) -> list[CheckResult]:
    spec_metrics = [c.metric for c in spec.judge_criteria() if c.metric]
    metrics = default_judge_metrics(spec_metrics)
    criterion_by_metric = {c.metric: c.id for c in spec.judge_criteria() if c.metric}
    context = _judge_context(spec)

    out: list[CheckResult] = []
    for metric in metrics:
        results = [
            judge.score(
                metric,
                trace,
                criterion_id=criterion_by_metric.get(metric, metric),
                context=context,
            )
            for trace in traces
        ]
        out.append(_merge_judge(metric, criterion_by_metric.get(metric, metric), results))
    return out


def _merge_judge(metric: str, criterion_id: str, results: list[CheckResult]) -> CheckResult:
    score = sum(r.score for r in results) / len(results)
    failing = [r for r in results if r.label is not Label.YES]
    if not failing:
        label = Label.YES
    elif score < 0.5:
        label = Label.NO
    else:
        label = Label.PARTIAL
    rationale = failing[0].rationale if failing else results[0].rationale
    evidence = [e for r in failing for e in r.evidence][:5]
    return CheckResult(
        criterion_id=criterion_id,
        dimension=results[0].dimension,
        check=CheckType.LLM_JUDGE,
        label=label,
        score=score,
        metric=metric,
        rationale=(f"{len(results)}개 대화 중 {len(failing)}개에서 문제: {rationale}" if failing else rationale),
        evidence=evidence,
        judge_model=results[0].judge_model,
        order_swapped=any(r.order_swapped for r in results),
    )


def _judge_context(spec: AgentSpec) -> str:
    parts = []
    if spec.agent_role:
        parts.append(f"에이전트 역할: {spec.agent_role}")
    if spec.learning_goals:
        parts.append("학습목표: " + "; ".join(spec.learning_goals[:4]))
    if spec.scaffolding_policy:
        parts.append(f"스캐폴딩 방침: {truncate(spec.scaffolding_policy, 200)}")
    if spec.answer_condition:
        parts.append(f"정답 제공이 허용되는 조건: {spec.answer_condition}")
    return "\n".join(parts)


# --- aggregation ----------------------------------------------------------
def _aggregate(checks: list[CheckResult]) -> list[DimensionScore]:
    out: list[DimensionScore] = []
    for dimension in SCORED_DIMENSIONS:
        items = [c for c in checks if c.dimension is dimension]
        if not items:
            out.append(DimensionScore(dimension=dimension, score_0_5=0.0, n_checks=0))
            continue
        mean = sum(c.score for c in items) / len(items)
        deterministic = sum(1 for c in items if c.check is CheckType.DETERMINISTIC)
        out.append(
            DimensionScore(
                dimension=dimension,
                score_0_5=round(mean * 5, 2),
                n_checks=len(items),
                deterministic_share=deterministic / len(items),
                failures=[c for c in items if c.label is not Label.YES],
            )
        )
    return out


def _compliance(spec: AgentSpec, traces: list[SessionTrace]) -> list[ConstraintCompliance]:
    """Per-constraint compliance rate (SysBench CSR)."""
    by_gate: dict[str, ConstraintCompliance] = {
        g.id: ConstraintCompliance(
            gate_id=g.id,
            constraint_text=g.constraint.text or g.constraint.kind.value,
            principle_id=g.principle_id,
        )
        for g in spec.gates
    }
    for trace in traces:
        for turn in trace.turns:
            for decision in turn.gates:
                item = by_gate.get(decision.gate_id)
                if item is None:
                    continue
                item.turns_applicable += 1
                if not decision.passed:
                    item.turns_violated += 1
                    if item.first_violation_turn is None:
                        item.first_violation_turn = turn.turn_index
                    if len(item.evidence) < 3:
                        item.evidence.append(
                            Evidence(
                                session_id=trace.session_id,
                                scenario_id=trace.scenario_id,
                                persona_id=trace.persona_id,
                                seed=trace.seed,
                                turn_index=turn.turn_index,
                                learner_message=truncate(turn.learner_message, 100),
                                tutor_message=truncate(turn.tutor_message, 160),
                                note=decision.reason,
                            )
                        )
    return sorted(by_gate.values(), key=lambda c: c.rate)


def _learner_side(results: Sequence[SimulationResult], traces: list[SessionTrace]) -> LearnerSideMetrics:
    if not results:
        return LearnerSideMetrics(sessions=len(traces))
    return LearnerSideMetrics(
        sessions=len(results),
        reasoning_elicited_sessions=sum(1 for r in results if r.showed_reasoning),
        retried_after_hint_sessions=sum(1 for r in results if r.attempted_after_hint),
        solved_sessions=sum(1 for r in results if r.solved),
        explained_process_sessions=sum(1 for r in results if r.explained_process),
    )


def _simulator_health(results: Sequence[SimulationResult], traces: list[SessionTrace]) -> SimulatorHealth:
    health = SimulatorHealth(sessions=len(results) or len(traces))
    if results:
        health.constraint_violations = sum(len(r.violations) for r in results)
        health.misconception_flips_on_untargeted_feedback = sum(r.unfaithful_flips for r in results)
        health.misconception_opportunities = sum(r.flip_opportunities for r in results)
        words = [w for r in results for w in r.student_words]
        health.mean_words_per_turn = round(sum(words) / len(words), 1) if words else 0.0
        total_turns = sum(len(r.trace.turns) for r in results) or 1
        health.off_task_share = round(sum(r.off_task_turns for r in results) / total_turns, 3)

    if health.mean_words_per_turn > 40:
        health.warnings.append(
            "시뮬레이션 학생의 발화가 실제 학생보다 깁니다. 페르소나의 verbosity를 낮춰 보세요."
        )
    if health.constraint_violations:
        health.warnings.append(
            f"시뮬레이터가 제약을 {health.constraint_violations}회 벗어났습니다. 결과 해석에 주의하세요."
        )
    if health.unfaithful_flip_rate > 0.1:
        health.warnings.append(
            "시뮬레이션 학생이 무관한 피드백에도 오개념을 버렸습니다 (아첨적 신념 갱신)."
        )
    return health


def _technical(traces: list[SessionTrace]) -> TechnicalHealth:
    turns = [t for trace in traces for t in trace.turns]
    latencies = [t.latency_ms for t in turns if t.latency_ms]
    return TechnicalHealth(
        errors=sum(len(t.errors) for t in traces),
        gate_regenerations=sum(t.total_regenerations() for t in traces),
        fallbacks=sum(1 for t in turns if t.fallback_used),
        mean_latency_ms=int(sum(latencies) / len(latencies)) if latencies else 0,
    )


def _capitulation_rate(traces: list[SessionTrace]) -> float:
    from edu_agent.runtime.triggers import detect_pressure
    from edu_agent.schemas.principles import AgentAction

    pressured = 0
    caved = 0
    for trace in traces:
        for turn in trace.turns:
            if detect_pressure(turn.learner_message):
                pressured += 1
                if turn.leaked_answer or turn.declared_action is AgentAction.GIVE_DIRECT_ANSWER:
                    caved += 1
    return caved / pressured if pressured else 0.0


def _notes(report: EvaluationReport, inp: EvaluationInput) -> list[str]:
    notes: list[str] = []
    if inp.judge is None:
        notes.append("judge를 사용하지 않았습니다 (--no-llm). 결정적 검사 결과만 표시합니다.")
    elif not report.calibration.trustworthy:
        notes.append(
            "judge 점수는 사람 채점으로 보정되기 전까지 참고용입니다 (edu-agent calibrate)."
        )
    if report.n_sessions < 4:
        notes.append("대화 수가 적어 결과가 불안정할 수 있습니다. --seeds 를 늘려 보세요.")
    untraced = inp.spec.untraced_principles()
    if untraced:
        notes.append(f"테스트 시나리오까지 연결되지 않은 설계원리: {', '.join(untraced)}")
    thin = [d.label_ko for d in report.dimensions if d.n_checks == 0]
    if thin:
        notes.append(f"검사 항목이 없는 평가 영역: {', '.join(thin)}")
    return notes
