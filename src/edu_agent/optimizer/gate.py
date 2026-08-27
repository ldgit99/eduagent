"""The regression gate: when may a change be kept?

Adapted from prompt-CI practice — a change lands only if it clears a minimum
improvement *and* breaks nothing that previously passed. Three refinements matter
here:

* **Hard-constraint regressions are absolute.** A gain in judge-scored "tone" can
  never pay for a newly leaked answer.
* **Deterministic evidence outranks judge scores**, and judge scores are discounted
  entirely while the judge is uncalibrated. Otherwise the loop optimises against a
  measure that has not been shown to track human judgement.
* **A minimum improvement threshold** absorbs metric noise, which is real: with a
  handful of scenarios, ±0.1 on a 0–5 scale means nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from edu_agent.schemas.common import CheckType
from edu_agent.schemas.evaluation import EvaluationReport, Label


@dataclass(slots=True)
class GateVerdict:
    """Whether a change should be kept."""

    accept: bool
    reason: str
    before: float
    after: float
    regressions: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)

    @property
    def delta(self) -> float:
        return self.after - self.before

    def summary_ko(self) -> str:
        arrow = f"{self.before:.2f} → {self.after:.2f}"
        return f"{'채택' if self.accept else '되돌림'} ({arrow}): {self.reason}"


def evaluate_change(
    before: EvaluationReport,
    after: EvaluationReport,
    *,
    min_improvement: float = 0.05,
    trust_judge: bool | None = None,
) -> GateVerdict:
    """Compare two evaluation reports and decide."""
    if trust_judge is None:
        trust_judge = after.calibration.trustworthy

    before_score = _score(before, trust_judge)
    after_score = _score(after, trust_judge)

    hard = _hard_regressions(before, after)
    if hard:
        return GateVerdict(
            accept=False,
            reason="지켜지던 규칙이 새로 무너졌습니다: " + "; ".join(hard[:3]),
            before=before_score,
            after=after_score,
            regressions=hard,
        )

    if after.leakage_rate > before.leakage_rate + 1e-9:
        return GateVerdict(
            accept=False,
            reason=f"정답 노출이 늘었습니다 ({before.leakage_rate:.0%} → {after.leakage_rate:.0%})",
            before=before_score,
            after=after_score,
            regressions=["answer_leakage"],
        )

    if not after.technical.passed and before.technical.passed:
        return GateVerdict(
            accept=False,
            reason="기술적 안정성이 통과에서 실패로 바뀌었습니다.",
            before=before_score,
            after=after_score,
            regressions=["technical_stability"],
        )

    soft = _soft_regressions(before, after, trust_judge)
    improvements = _improvements(before, after)
    delta = after_score - before_score

    if delta < min_improvement:
        return GateVerdict(
            accept=False,
            reason=(
                f"개선 폭이 기준({min_improvement:+.2f})에 못 미칩니다 ({delta:+.2f}). "
                "측정 잡음과 구분되지 않습니다."
            ),
            before=before_score,
            after=after_score,
            regressions=soft,
            improvements=improvements,
        )

    return GateVerdict(
        accept=True,
        reason=f"개선되었고 새로 무너진 규칙이 없습니다 ({delta:+.2f}).",
        before=before_score,
        after=after_score,
        regressions=soft,
        improvements=improvements,
    )


def _score(report: EvaluationReport, trust_judge: bool) -> float:
    """Overall score, discounting judge dimensions when the judge is unverified."""
    if trust_judge:
        return report.overall

    deterministic = [c for c in report.checks if c.check is CheckType.DETERMINISTIC]
    if not deterministic:
        return report.overall
    return round(sum(c.score for c in deterministic) / len(deterministic) * 5, 3)


def _hard_regressions(before: EvaluationReport, after: EvaluationReport) -> list[str]:
    """Constraints that used to hold and now do not."""
    out: list[str] = []
    before_rates = {c.gate_id: c.rate for c in before.compliance}
    for item in after.compliance:
        was = before_rates.get(item.gate_id)
        if was is None:
            continue
        if was >= 0.999 and item.rate < 0.999:
            out.append(f"{item.gate_id}({item.constraint_text or ''})".strip())
        elif item.rate < was - 0.15:
            out.append(f"{item.gate_id} 준수율 {was:.0%}→{item.rate:.0%}")

    before_det = {c.metric: c.label for c in before.checks if c.check is CheckType.DETERMINISTIC}
    for check in after.checks:
        if check.check is not CheckType.DETERMINISTIC:
            continue
        was_label = before_det.get(check.metric)
        if was_label is Label.YES and check.label is Label.NO:
            out.append(f"{check.metric} 통과→실패")
    return out


def _soft_regressions(before: EvaluationReport, after: EvaluationReport, trust_judge: bool) -> list[str]:
    if not trust_judge:
        return []
    before_scores = {d.dimension: d.score_0_5 for d in before.dimensions}
    return [
        f"{d.label_ko} {before_scores[d.dimension]:.2f}→{d.score_0_5:.2f}"
        for d in after.dimensions
        if d.dimension in before_scores and d.score_0_5 < before_scores[d.dimension] - 0.3
    ]


def _improvements(before: EvaluationReport, after: EvaluationReport) -> list[str]:
    out: list[str] = []
    before_scores = {d.dimension: d.score_0_5 for d in before.dimensions}
    for d in after.dimensions:
        was = before_scores.get(d.dimension)
        if was is not None and d.score_0_5 > was + 0.2:
            out.append(f"{d.label_ko} {was:.2f}→{d.score_0_5:.2f}")
    if after.leakage_rate < before.leakage_rate:
        out.append(f"정답 노출 {before.leakage_rate:.0%}→{after.leakage_rate:.0%}")
    return out
