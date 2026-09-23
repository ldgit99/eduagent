"""LLM-as-judge with the safeguards the literature says are mandatory.

Three of them are wired in rather than left to discipline:

* **Three-way labels.** ``partial`` is a real class (BEA 2025), so a rubric never
  collapses to pass/fail.
* **Order swapping.** Judges show measurable position bias (>0.10 in Norman et al.
  2026), so when ``order_swap`` is on, each verdict is taken twice with the
  conversation presented in a different order and disagreement downgrades the
  label to ``partial`` instead of picking a winner.
* **Provisional until calibrated.** Nothing here decides whether the score is
  trusted — :mod:`edu_agent.evaluator.calibration` does, and the report shows the
  warning until κ clears the threshold.
"""

from __future__ import annotations

import functools
from collections.abc import Sequence
from pathlib import Path

import yaml
from pydantic import Field

from edu_agent.evaluator.registry import dimension_for_metric
from edu_agent.providers.base import ChatMessage, Provider, ProviderError
from edu_agent.schemas.common import CheckType, HarnessModel
from edu_agent.schemas.evaluation import CheckResult, Dimension, Evidence, Label
from edu_agent.schemas.trace import SessionTrace
from edu_agent.utils.text import truncate

_RUBRIC_DIR = Path(__file__).parent / "rubrics"

VERDICT_SCHEMA: dict[str, object] = {
    "name": "JudgeVerdict",
    "schema": {
        "type": "object",
        "properties": {
            "label": {"type": "string", "enum": ["yes", "partial", "no"]},
            "rationale": {"type": "string"},
            "turn_index": {"type": "integer", "description": "근거가 된 턴 번호 (없으면 -1)"},
        },
        "required": ["label", "rationale"],
        "additionalProperties": False,
    },
    "strict": False,
}


class Rubric(HarnessModel):
    metric: str
    dimension: str = Dimension.INTERACTION_QUALITY.value
    question: str
    note: str = ""
    anchors: dict[str, str] = Field(default_factory=dict)
    source: str = ""


class RubricExemplar(HarnessModel):
    """One turn a human rated, shown to the judge as a worked example."""

    learner_message: str = ""
    tutor_message: str = ""
    label: Label = Label.PARTIAL
    note: str = ""


class MetricOverlay(HarnessModel):
    """What human ratings taught us about one metric."""

    note: str = Field(default="", description="사람 채점과 어긋난 방향을 알려주는 한 줄")
    exemplars: list[RubricExemplar] = Field(default_factory=list)


class RubricOverlay(HarnessModel):
    """A versioned layer on top of the shipped rubrics.

    The rubric files stay under version control and untouched (PReMISE); what a
    project's own human ratings produce is kept separately, so it is obvious which
    part of the judge's prompt came from the literature and which part came from
    twenty turns this class scored.
    """

    version: int = 0
    created_at: str = ""
    kappa_before: float | None = None
    kappa_after: float | None = None
    n_holdout: int = 0
    metrics: dict[str, MetricOverlay] = Field(default_factory=dict)

    def for_metric(self, metric: str) -> MetricOverlay | None:
        return self.metrics.get(metric)


@functools.lru_cache(maxsize=1)
def load_rubrics() -> dict[str, Rubric]:
    rubrics: dict[str, Rubric] = {}
    for path in sorted(_RUBRIC_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for raw in data.get("rubrics", []):
            r = Rubric.model_validate(raw)
            rubrics[r.metric] = r
    return rubrics


def rubric_for(metric: str) -> Rubric | None:
    return load_rubrics().get(metric)


class Judge:
    """Scores one rubric against one conversation."""

    def __init__(
        self,
        provider: Provider,
        *,
        order_swap: bool = True,
        max_turns: int = 20,
        overlay: RubricOverlay | None = None,
    ) -> None:
        self.provider = provider
        self.order_swap = order_swap
        self.max_turns = max_turns
        self.overlay = overlay
        self.calls = 0

    def score_turn(self, metric: str, trace: SessionTrace, turn_index: int) -> Label:
        """Judge one specific turn — the unit a human rates on the worksheet.

        ``score`` judges a whole conversation, which is the right unit for a
        report but the wrong one for calibration: comparing a conversation-level
        label against a turn-level human label measures the mismatch, not the
        judge. Everything downstream of calibration uses this instead.
        """
        rubric = rubric_for(metric)
        turn = next((t for t in trace.turns if t.turn_index == turn_index), None)
        if turn is None:
            return Label.PARTIAL
        window = SessionTrace(
            session_id=trace.session_id,
            scenario_id=trace.scenario_id,
            persona_id=trace.persona_id,
            seed=trace.seed,
            # A little context on either side: a turn read in isolation loses the
            # thing most rubrics ask about ("did the tutor adapt?").
            turns=[t for t in trace.turns if abs(t.turn_index - turn_index) <= 2],
        )
        label, _, _ = self._ask(
            rubric,
            "",
            window,
            f"판정 대상은 [턴 {turn_index}] 하나입니다. 다른 턴은 맥락으로만 보세요.",
            reversed_order=False,
        )
        return label

    def score(
        self,
        metric: str,
        trace: SessionTrace,
        *,
        criterion_id: str = "",
        statement: str = "",
        context: str = "",
    ) -> CheckResult:
        rubric = rubric_for(metric)
        dimension = dimension_for_metric(metric)

        if rubric is None and not statement:
            return CheckResult(
                criterion_id=criterion_id or metric,
                dimension=dimension,
                check=CheckType.LLM_JUDGE,
                label=Label.PARTIAL,
                metric=metric,
                rationale=f"'{metric}' 루브릭이 없어 판정하지 못했습니다.",
            )

        first = self._ask(rubric, statement, trace, context, reversed_order=False)
        if not self.order_swap:
            return self._result(criterion_id or metric, dimension, metric, first, trace)

        second = self._ask(rubric, statement, trace, context, reversed_order=True)
        if first[0] is second[0]:
            return self._result(criterion_id or metric, dimension, metric, first, trace, swapped=True)

        # Disagreement between orderings means the judge is not stable on this item.
        # Reporting the midpoint with both rationales is more honest than picking one.
        merged = (
            Label.PARTIAL,
            f"순서를 바꿔 판정했을 때 결과가 달랐습니다 ({first[0].value} vs {second[0].value}). "
            f"[1] {first[1]} [2] {second[1]}",
            first[2],
        )
        return self._result(criterion_id or metric, dimension, metric, merged, trace, swapped=True)

    # --- internals --------------------------------------------------------
    def _ask(
        self,
        rubric: Rubric | None,
        statement: str,
        trace: SessionTrace,
        context: str,
        *,
        reversed_order: bool,
    ) -> tuple[Label, str, int]:
        prompt = self._prompt(rubric, statement, trace, context, reversed_order)
        try:
            self.calls += 1
            completion = self.provider.complete(
                [ChatMessage("user", prompt)],
                response_schema=VERDICT_SCHEMA,
                temperature=0.0,
                max_tokens=400,
            )
            data = completion.parse_json()
        except ProviderError as exc:
            return Label.PARTIAL, f"판정 실패: {exc}", -1

        if not isinstance(data, dict):
            return Label.PARTIAL, "판정 형식을 읽지 못했습니다.", -1
        try:
            label = Label(str(data.get("label", "partial")).lower())
        except ValueError:
            label = Label.PARTIAL
        return label, str(data.get("rationale", "")).strip(), int(data.get("turn_index", -1) or -1)

    def _prompt(
        self,
        rubric: Rubric | None,
        statement: str,
        trace: SessionTrace,
        context: str,
        reversed_order: bool,
    ) -> str:
        question = rubric.question if rubric else statement
        lines = [
            "당신은 교육 대화를 평가하는 전문가입니다. 아래 대화를 읽고 하나의 항목만 판정하세요.",
            "",
            f"## 판정 항목\n{question}",
        ]
        if rubric and rubric.note:
            lines.append(f"## 주의\n{rubric.note.strip()}")
        if rubric and rubric.anchors:
            anchors = "\n".join(f"- **{k}**: {v}" for k, v in rubric.anchors.items())
            lines.append(f"## 판정 기준\n{anchors}")
        else:
            lines.append(
                "## 판정 기준\n- **yes**: 충족함\n- **partial**: 부분적으로 충족함\n- **no**: 충족하지 않음"
            )
        overlay = self.overlay.for_metric(rubric.metric) if (self.overlay and rubric) else None
        if overlay is not None:
            if overlay.note:
                lines.append(f"## 사람 채점에서 확인된 것\n{overlay.note}")
            if overlay.exemplars:
                shown = "\n\n".join(
                    f"- 학습자: {truncate(e.learner_message, 200)}\n"
                    f"  튜터: {truncate(e.tutor_message, 300)}\n"
                    f"  → 사람의 판정: **{e.label.value}**"
                    + (f" ({e.note})" if e.note else "")
                    for e in overlay.exemplars
                )
                lines.append(f"## 사람이 채점한 예\n{shown}")

        if context:
            lines.append(f"## 설계 맥락\n{context}")

        lines.append(f"## 대화\n{self._transcript(trace, reversed_order)}")
        lines.append(
            "## 답변 형식\n"
            "JSON 하나로 답하세요: label(yes|partial|no), rationale(한 문장, 근거가 된 발화를 인용), "
            "turn_index(근거 턴 번호, 없으면 -1).\n"
            "길거나 공손한 응답이라는 이유로 높게 평가하지 마세요. 판정 항목만 보세요."
        )
        return "\n\n".join(lines)

    def _transcript(self, trace: SessionTrace, reversed_order: bool) -> str:
        turns = trace.turns[: self.max_turns]
        blocks = [
            f"[턴 {t.turn_index}]\n학습자: {truncate(t.learner_message, 300)}\n튜터: {truncate(t.tutor_message, 500)}"
            for t in turns
        ]
        if reversed_order:
            blocks = list(reversed(blocks))
            blocks.insert(0, "(아래 대화는 마지막 턴부터 역순으로 제시됩니다.)")
        return "\n\n".join(blocks)

    def _result(
        self,
        criterion_id: str,
        dimension: Dimension,
        metric: str,
        verdict: tuple[Label, str, int],
        trace: SessionTrace,
        *,
        swapped: bool = False,
    ) -> CheckResult:
        label, rationale, turn_index = verdict
        evidence: list[Evidence] = []
        turn = next((t for t in trace.turns if t.turn_index == turn_index), None)
        if turn is not None:
            evidence.append(
                Evidence(
                    session_id=trace.session_id,
                    scenario_id=trace.scenario_id,
                    persona_id=trace.persona_id,
                    seed=trace.seed,
                    turn_index=turn.turn_index,
                    learner_message=truncate(turn.learner_message, 100),
                    tutor_message=truncate(turn.tutor_message, 160),
                )
            )
        return CheckResult(
            criterion_id=criterion_id,
            dimension=dimension,
            check=CheckType.LLM_JUDGE,
            label=label,
            metric=metric,
            rationale=rationale,
            evidence=evidence,
            judge_model=getattr(self.provider, "model", ""),
            order_swapped=swapped,
        )


def default_judge_metrics(spec_metrics: Sequence[str]) -> list[str]:
    """Baseline judge metrics plus whatever the spec asked for."""
    baseline = [
        "goal_alignment",
        "guidance_quality",
        "actionability",
        "coherence",
        "tutor_tone",
        "adaptation",
        "pedagogical_safety",
        "no_unproductive_withholding",
    ]
    out = list(baseline)
    for m in spec_metrics:
        if m in load_rubrics() and m not in out:
            out.append(m)
    return out
