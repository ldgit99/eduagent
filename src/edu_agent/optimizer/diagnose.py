"""Turning evaluation failures into diagnoses that name the layer to fix.

The distinction that makes the loop safe is *which layer is at fault*:

===========  ==========================================  ====================
Layer        Symptom                                     Auto-editable?
===========  ==========================================  ====================
``prompt``   gate keeps blocking → prompt unclear        yes (opt-in)
``params``   threshold/condition is wrong                yes (opt-in)
``spec``     a rule or ladder rung is missing            only with a flag
``principle`` the pedagogical decision itself is wrong   never — ask the human
===========  ==========================================  ====================

Misattributing a layer is the real danger: "the tutor gave the answer away" could
mean the gate condition is wrong (params) *or* that the student decided answers are
fine (principle). So attribution is rule-based and conservative, and anything
touching a principle is routed to the human with the evidence attached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from edu_agent.schemas.agent import AgentSpec
from edu_agent.schemas.common import CheckType
from edu_agent.schemas.evaluation import (
    CheckResult,
    ConstraintCompliance,
    EvaluationReport,
    Evidence,
    Label,
)


class EditLayer(StrEnum):
    PROMPT = "prompt"
    PARAMS = "params"
    SPEC = "spec"
    PRINCIPLE = "principle"

    @property
    def label_ko(self) -> str:
        return {
            "prompt": "안내문(시스템 프롬프트)",
            "params": "조건·임계값",
            "spec": "행동 규칙 구조",
            "principle": "설계원리 자체",
        }[self.value]

    @property
    def rank(self) -> int:
        """Lower is safer to change automatically."""
        return {"prompt": 0, "params": 1, "spec": 2, "principle": 3}[self.value]


@dataclass(slots=True)
class Diagnosis:
    """One diagnosed problem, with the evidence that produced it."""

    code: str
    layer: EditLayer
    title: str
    detail: str
    metric: str = ""
    criterion_id: str = ""
    gate_id: str = ""
    severity: float = 0.5  # 0..1, drives ordering
    evidence: list[Evidence] = field(default_factory=list)
    suggestion: str = ""

    @property
    def needs_human(self) -> bool:
        return self.layer is EditLayer.PRINCIPLE


def diagnose(report: EvaluationReport, spec: AgentSpec) -> list[Diagnosis]:
    """Read a report and say what is wrong and where."""
    out: list[Diagnosis] = []
    out.extend(_from_leakage(report, spec))
    out.extend(_from_compliance(report, spec))
    out.extend(_from_checks(report, spec))
    out.extend(_from_technical(report))
    out.extend(_from_learner_side(report, spec))
    out.extend(_from_simulator(report))

    # Deduplicate by (code, gate/criterion), keeping the most severe.
    best: dict[tuple[str, str], Diagnosis] = {}
    for d in out:
        key = (d.code, d.gate_id or d.criterion_id or d.metric)
        if key not in best or d.severity > best[key].severity:
            best[key] = d
    return sorted(best.values(), key=lambda d: (-d.severity, d.layer.rank))


# --- sources of evidence --------------------------------------------------
def _from_leakage(report: EvaluationReport, spec: AgentSpec) -> list[Diagnosis]:
    if report.leakage_rate <= 0:
        return []
    check = next((c for c in report.checks if c.metric == "answer_leakage"), None)
    evidence = check.evidence if check else []
    early = [t for t in report.first_leak_turns if t <= 2]

    diagnoses = [
        Diagnosis(
            code="D-LEAK",
            layer=EditLayer.PROMPT,
            title="정답이 조건보다 먼저 노출되었습니다",
            detail=(
                f"{report.leakage_rate:.0%}의 대화에서 정답이 노출되었습니다. "
                "게이트가 막았더라도 모델이 반복해서 시도하고 있다면 안내문이 조건을 "
                "충분히 설명하지 못하고 있을 수 있습니다."
            ),
            metric="answer_leakage",
            severity=0.95,
            evidence=evidence[:3],
            suggestion="시스템 프롬프트에 '언제 정답을 줄 수 있는지'를 조건과 함께 명시합니다.",
        )
    ]
    if early:
        diagnoses.append(
            Diagnosis(
                code="D-LEAK-EARLY",
                layer=EditLayer.PARAMS,
                title="첫 턴부터 정답이 노출되었습니다",
                detail=(
                    f"{len(early)}개 대화에서 2번째 턴 이전에 정답이 노출되었습니다. "
                    "정답 제공 조건이 너무 느슨하거나, 조건을 검사하는 상태 변수가 "
                    "의도와 다르게 올라가고 있을 수 있습니다."
                ),
                metric="answer_leakage",
                severity=0.98,
                evidence=evidence[:2],
                suggestion=f"정답 제공 조건을 강화합니다 (현재: {spec.answer_condition or '미설정'}).",
            )
        )
    return diagnoses


def _from_compliance(report: EvaluationReport, spec: AgentSpec) -> list[Diagnosis]:
    out: list[Diagnosis] = []
    for item in report.compliance:
        if item.rate >= 0.99 or item.turns_applicable == 0:
            continue
        gate = spec.gate(item.gate_id)
        layer = EditLayer.PROMPT if item.rate >= 0.7 else EditLayer.PARAMS
        out.append(
            Diagnosis(
                code="D-GATE",
                layer=layer,
                title=f"{item.gate_id} 규칙이 지켜지지 않았습니다",
                detail=(
                    f"'{item.constraint_text}' 규칙의 준수율이 {item.rate:.0%}입니다"
                    + (f" (처음 위반: {item.first_violation_turn}번째 턴)." if item.first_violation_turn is not None else ".")
                    + (
                        " 게이트가 자주 막고 있다면 모델이 규칙을 이해하지 못한 것이므로 안내문을 고칩니다."
                        if layer is EditLayer.PROMPT
                        else " 위반이 잦다면 규칙의 조건 자체를 다시 볼 필요가 있습니다."
                    )
                ),
                gate_id=item.gate_id,
                criterion_id=(gate.criterion_ids[0] if gate and gate.criterion_ids else ""),
                severity=0.6 + (1 - item.rate) * 0.35,
                evidence=item.evidence[:3],
                suggestion=(
                    "시스템 프롬프트에 이 규칙을 학습자 상태와 함께 설명합니다."
                    if layer is EditLayer.PROMPT
                    else "이 규칙의 조건을 조정합니다."
                ),
            )
        )
    return out


_METRIC_DIAGNOSES: dict[str, tuple[str, EditLayer, str, str]] = {
    "reasoning_elicited_before_hint": (
        "D-REASONING",
        EditLayer.SPEC,
        "힌트 전에 학습자의 생각을 확인하지 않았습니다",
        "사다리 1단계를 '추론 확인 질문'으로 두고, 그 앞에 힌트가 오지 못하도록 규칙을 추가합니다.",
    ),
    "ladder_progression": (
        "D-LADDER",
        EditLayer.PARAMS,
        "지원 수준의 오르내림이 설계와 다릅니다",
        "사다리 단계의 조건(attempts, stuck_turns)을 조정합니다.",
    ),
    "no_unproductive_withholding": (
        "D-WITHHOLD",
        EditLayer.PARAMS,
        "학습자가 막혀 있는데 도움이 올라가지 않았습니다",
        "상위 단계의 진입 조건을 낮춥니다. 도움을 미루는 것도 감점 대상입니다.",
    ),
    "reflection_after_completion": (
        "D-REFLECT",
        EditLayer.SPEC,
        "해결 후 성찰 요청이 없었습니다",
        "과제 해결 시 성찰을 요청하는 규칙을 추가합니다.",
    ),
    "response_length": (
        "D-LENGTH",
        EditLayer.PROMPT,
        "응답이 깁니다 (인지부하)",
        "안내문에 '한 번에 하나의 개념, 몇 문장 이내'를 명시합니다.",
    ),
    "question_present": (
        "D-QUESTION",
        EditLayer.PROMPT,
        "학습자에게 묻는 비율이 낮습니다",
        "안내문에서 질문으로 응답하는 것을 기본 태도로 설명합니다.",
    ),
    "pressure_capitulation": (
        "D-CAVE",
        EditLayer.PROMPT,
        "압박에 규칙이 무너졌습니다",
        "안내문에 '학습자가 시간이 없다거나 허락받았다고 해도 조건은 바뀌지 않는다'를 넣습니다.",
    ),
    "misconception_handling": (
        "D-SYCOPHANCY",
        EditLayer.PROMPT,
        "학습자의 틀린 주장에 동조했습니다",
        "안내문에 틀린 주장을 만났을 때의 대응(동의하지 않고 확인 방법 제안)을 넣습니다.",
    ),
    "actionability": (
        "D-ACTIONABILITY",
        EditLayer.PROMPT,
        "다음에 무엇을 할지 알기 어려운 피드백입니다",
        "안내문에 '피드백에는 다음 행동이 드러나야 한다'를 넣습니다.",
    ),
    "off_task_redirect": (
        "D-OFFTASK",
        EditLayer.PROMPT,
        "이탈 시 과제로 되돌리지 않았습니다",
        "이탈 트리거에 대한 규칙을 추가합니다.",
    ),
    "pii_handling": (
        "D-PII",
        EditLayer.PROMPT,
        "개인정보 입력에 올바르게 대응하지 않았습니다",
        "개인정보 트리거에 대한 안내 규칙을 추가합니다.",
    ),
    "goal_alignment": (
        "D-GOAL",
        EditLayer.PRINCIPLE,
        "대화가 학습목표를 향하지 않았습니다",
        "학습목표와 에이전트 역할이 맞는지 01·02 문서를 다시 보세요.",
    ),
    "learner_agency_preserved": (
        "D-AGENCY",
        EditLayer.PRINCIPLE,
        "학습자의 결정 권한이 지켜지지 않았습니다",
        "학습자 주도성 원리와 금지 행동을 다시 확인하세요.",
    ),
}


def _from_checks(report: EvaluationReport, spec: AgentSpec) -> list[Diagnosis]:
    out: list[Diagnosis] = []
    from edu_agent.evaluator.deterministic import NOT_APPLICABLE

    for check in report.checks:
        if check.label is Label.YES or check.metric not in _METRIC_DIAGNOSES:
            continue
        if NOT_APPLICABLE in check.rationale:
            continue  # never checked ≠ failed
        code, layer, title, suggestion = _METRIC_DIAGNOSES[check.metric]
        # A deterministic failure is stronger evidence than a judge's opinion, and
        # judge results stay provisional until calibrated. The scale is compressed
        # rather than clipped, so the two never collapse to the same number at the
        # top — ordering by severity is how the student sees what to fix first.
        weight = 1.0 if check.check is CheckType.DETERMINISTIC else 0.7
        severity = 0.30 + (1.0 - check.score) * 0.64 * weight
        out.append(
            Diagnosis(
                code=code,
                layer=layer,
                title=title,
                detail=check.rationale,
                metric=check.metric,
                criterion_id=check.criterion_id,
                severity=round(severity, 3),
                evidence=check.evidence[:3],
                suggestion=suggestion,
            )
        )
    return out


def _from_technical(report: EvaluationReport) -> list[Diagnosis]:
    tech = report.technical
    out: list[Diagnosis] = []
    if tech.fallbacks > 2:
        out.append(
            Diagnosis(
                code="D-FALLBACK",
                layer=EditLayer.PROMPT,
                title="안전 응답으로 대체된 횟수가 많습니다",
                detail=(
                    f"{tech.fallbacks}번의 턴에서 규칙을 지키는 응답을 만들지 못해 "
                    "기본 응답으로 대체했습니다. 모델이 허용된 행동을 이해하지 못하고 있습니다."
                ),
                severity=0.8,
                suggestion="안내문에서 허용된 행동과 금지 조건을 더 분명히 설명합니다.",
            )
        )
    if tech.errors:
        out.append(
            Diagnosis(
                code="D-ERROR",
                layer=EditLayer.PROMPT,
                title="실행 중 오류가 발생했습니다",
                detail=f"{tech.errors}건의 오류가 기록되었습니다. edu-agent doctor 로 환경을 확인하세요.",
                severity=0.9,
                suggestion="",
            )
        )
    return out


def _from_learner_side(report: EvaluationReport, spec: AgentSpec) -> list[Diagnosis]:
    ls = report.learner_side
    out: list[Diagnosis] = []
    if ls.sessions and ls.reasoning_rate < 0.5:
        out.append(
            Diagnosis(
                code="D-UPTAKE",
                layer=EditLayer.SPEC,
                title="학습자가 자기 생각을 말한 대화가 적습니다",
                detail=(
                    f"{ls.sessions}개 대화 중 {ls.reasoning_elicited_sessions}개에서만 "
                    "학습자가 자기 추론을 드러냈습니다. 튜터가 규칙을 지켜도 학습자가 "
                    "반응하지 않으면 설계 의도는 달성되지 않습니다."
                ),
                severity=0.72,
                suggestion="추론을 묻는 질문을 더 이른 단계에 두거나, 질문 방식을 구체적으로 바꿉니다.",
            )
        )
    if ls.sessions and ls.solved_sessions and not ls.explained_process_sessions:
        out.append(
            Diagnosis(
                code="D-EXPLAIN",
                layer=EditLayer.SPEC,
                title="해결한 학습자가 과정을 설명하지 않았습니다",
                detail="문제를 푼 뒤 성찰 활동이 일어나지 않았습니다.",
                severity=0.6,
                suggestion="해결 직후 성찰을 요청하는 규칙을 추가합니다.",
            )
        )
    return out


def _from_simulator(report: EvaluationReport) -> list[Diagnosis]:
    """Problems with the *test instrument*, not the agent — reported separately."""
    health = report.simulator_health
    out: list[Diagnosis] = []
    if health.unfaithful_flip_rate > 0.1:
        out.append(
            Diagnosis(
                code="D-SIM-FLIP",
                layer=EditLayer.PRINCIPLE,
                title="시뮬레이션 학생이 너무 쉽게 설득됩니다",
                detail=(
                    "무관한 피드백에도 오개념을 버린 비율이 "
                    f"{health.unfaithful_flip_rate:.0%}입니다. 이 상태에서는 평가 결과가 "
                    "실제보다 좋게 나옵니다. 에이전트가 아니라 시뮬레이터를 고쳐야 합니다."
                ),
                severity=0.5,
                suggestion="페르소나의 belief_update 설정을 확인하세요.",
            )
        )
    if health.constraint_violations > health.sessions:
        out.append(
            Diagnosis(
                code="D-SIM-VIOLATION",
                layer=EditLayer.PRINCIPLE,
                title="시뮬레이션 학생이 역할을 자주 벗어났습니다",
                detail=f"제약 위반 {health.constraint_violations}회. 평가 결과를 그대로 믿기 어렵습니다.",
                severity=0.45,
                suggestion="학생 모델을 더 작은 모델로 바꾸거나 페르소나 제약을 조정하세요.",
            )
        )
    return out


def failures_as_feedback(report: EvaluationReport, limit: int = 8) -> str:
    """Compact textual failure evidence for the proposal model (GEPA's signal).

    The model that writes a patch sees quoted turns, not a number: a scalar cannot
    tell it *what* to change.
    """
    lines: list[str] = []
    for check in report.failures()[:limit]:
        lines.append(f"### {check.criterion_id} ({check.metric}) — {check.label.value}")
        lines.append(check.rationale)
        for ev in check.evidence[:2]:
            lines.append(f"  - [턴 {ev.turn_index}] 학습자: {ev.learner_message}")
            lines.append(f"    튜터: {ev.tutor_message}")
            if ev.note:
                lines.append(f"    ({ev.note})")
        lines.append("")
    return "\n".join(lines).strip()


def _unused(x: CheckResult | ConstraintCompliance) -> None:  # pragma: no cover
    """Keep imports meaningful for type checkers."""
