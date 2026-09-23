"""Turning human ratings into a better judge prompt — and only keeping it if it helps.

``edu-agent calibrate`` tells a student whether the judge agrees with them. This
module is the loop that closes: the same ratings are used to add worked examples
and a direction-of-error note to the judge's prompt, and the result is only kept
if agreement actually improves.

Three rules, borrowed from the improve loop (plan v2 §16) because the failure mode
is identical — fitting the thing you are measuring on:

* **Split before tuning.** Exemplars come from one half of the ratings; κ is
  measured on the other half, which the overlay has never seen.
* **A margin, not a tie.** A tuned rubric is adopted only if κ rises by at least
  :data:`MIN_IMPROVEMENT`. Noise on twenty items is easy to mistake for progress.
* **Never touch the shipped rubric.** The overlay is a separate, versioned file,
  so what came from the literature and what came from this class stay legible.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

from edu_agent.evaluator.calibration import HumanRating, cohens_kappa
from edu_agent.evaluator.judge import (
    Judge,
    MetricOverlay,
    RubricExemplar,
    RubricOverlay,
    rubric_for,
)
from edu_agent.schemas.evaluation import Label
from edu_agent.schemas.trace import SessionTrace
from edu_agent.utils.text import truncate

#: κ has to rise by this much on held-out items before a tuned rubric is adopted.
MIN_IMPROVEMENT = 0.05
#: More than a few examples and the prompt starts to crowd out the conversation.
MAX_EXEMPLARS = 3
#: Below this, a split leaves too little on either side to mean anything.
MIN_RATINGS = 6

OVERLAY_NAME = "judge_overlay.yaml"
HISTORY_NAME = "judge_tuning_history.json"

ItemKey = tuple[str, int, str]


@dataclass(slots=True)
class Disagreement:
    """One item where the human and the judge did not agree."""

    key: ItemKey
    metric: str
    human: Label
    judge: Label
    learner_message: str = ""
    tutor_message: str = ""
    note: str = ""

    @property
    def judge_was_lenient(self) -> bool:
        """The judge gave the *more favourable* label — the common failure mode."""
        return _favourability(self.judge) > _favourability(self.human)


@dataclass(slots=True)
class TuningResult:
    """What one tuning round decided, and why."""

    accepted: bool = False
    reason: str = ""
    kappa_before: float | None = None
    kappa_after: float | None = None
    n_tune: int = 0
    n_holdout: int = 0
    overlay: RubricOverlay | None = None
    disagreements: list[Disagreement] = field(default_factory=list)

    @property
    def delta(self) -> float | None:
        if self.kappa_before is None or self.kappa_after is None:
            return None
        return self.kappa_after - self.kappa_before


# --- splitting ------------------------------------------------------------
def split_ratings(
    ratings: list[HumanRating], *, holdout_ratio: float = 0.5
) -> tuple[list[HumanRating], list[HumanRating]]:
    """Split into (tune, holdout), stratified by metric, deterministically.

    Deterministic on purpose: a student who runs ``--tune`` twice should see the
    same decision, and a seed that moved would make the accept/reject verdict
    look arbitrary.
    """
    tune: list[HumanRating] = []
    holdout: list[HumanRating] = []
    by_metric: dict[str, list[HumanRating]] = {}
    for rating in sorted(ratings, key=_rating_key):
        by_metric.setdefault(rating.metric, []).append(rating)

    for items in by_metric.values():
        cut = max(1, round(len(items) * (1 - holdout_ratio)))
        tune.extend(items[:cut])
        holdout.extend(items[cut:])
    return tune, holdout


def judge_labels_for(
    judge: Judge, traces: list[SessionTrace], ratings: list[HumanRating]
) -> dict[ItemKey, Label]:
    """Ask the judge about exactly the items a human rated."""
    by_session = {trace.session_id: trace for trace in traces}
    labels: dict[ItemKey, Label] = {}
    for rating in ratings:
        trace = by_session.get(rating.session_id)
        if trace is None:
            continue
        labels[(rating.session_id, rating.turn_index, rating.metric)] = judge.score_turn(
            rating.metric, trace, rating.turn_index
        )
    return labels


def find_disagreements(
    ratings: list[HumanRating],
    judge_labels: dict[ItemKey, Label],
    traces: list[SessionTrace],
) -> list[Disagreement]:
    by_session = {trace.session_id: trace for trace in traces}
    out: list[Disagreement] = []
    for rating in ratings:
        key = (rating.session_id, rating.turn_index, rating.metric)
        judged = judge_labels.get(key)
        if judged is None or judged is rating.label:
            continue
        turn = None
        trace = by_session.get(rating.session_id)
        if trace is not None:
            turn = next((t for t in trace.turns if t.turn_index == rating.turn_index), None)
        out.append(
            Disagreement(
                key=key,
                metric=rating.metric,
                human=rating.label,
                judge=judged,
                learner_message=truncate(turn.learner_message, 200) if turn else "",
                tutor_message=truncate(turn.tutor_message, 300) if turn else "",
                note=rating.note,
            )
        )
    return out


# --- building the overlay -------------------------------------------------
def build_overlay(
    ratings: list[HumanRating],
    judge_labels: dict[ItemKey, Label],
    traces: list[SessionTrace],
    *,
    previous: RubricOverlay | None = None,
) -> RubricOverlay:
    """Turn the tuning half into exemplars plus a direction-of-error note."""
    by_session = {trace.session_id: trace for trace in traces}
    overlay = RubricOverlay(
        version=(previous.version + 1) if previous else 1,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )

    by_metric: dict[str, list[HumanRating]] = {}
    for rating in ratings:
        by_metric.setdefault(rating.metric, []).append(rating)

    for metric, items in sorted(by_metric.items()):
        if rubric_for(metric) is None:
            continue
        exemplars: list[RubricExemplar] = []
        # Disagreements first: an example the judge already gets right teaches it
        # nothing, and prompt space is the scarce resource here.
        ordered = sorted(
            items,
            key=lambda r: (judge_labels.get(_key(r)) is r.label, _rating_key(r)),
        )
        for rating in ordered[:MAX_EXEMPLARS]:
            trace = by_session.get(rating.session_id)
            turn = (
                next((t for t in trace.turns if t.turn_index == rating.turn_index), None)
                if trace
                else None
            )
            if turn is None:
                continue
            exemplars.append(
                RubricExemplar(
                    learner_message=truncate(turn.learner_message, 200),
                    tutor_message=truncate(turn.tutor_message, 300),
                    label=rating.label,
                    note=truncate(rating.note, 120),
                )
            )
        note = _bias_note(metric, items, judge_labels)
        if exemplars or note:
            overlay.metrics[metric] = MetricOverlay(note=note, exemplars=exemplars)
    return overlay


def _bias_note(
    metric: str, items: list[HumanRating], judge_labels: dict[ItemKey, Label]
) -> str:
    """State the *direction* of the judge's error, which is what it can act on."""
    directions = Counter[str]()
    for rating in items:
        judged = judge_labels.get(_key(rating))
        if judged is None or judged is rating.label:
            continue
        lenient = _favourability(judged) > _favourability(rating.label)
        directions["lenient" if lenient else "strict"] += 1

    total = sum(directions.values())
    if not total:
        return ""
    if directions["lenient"] >= max(2, total * 0.6):
        return (
            f"이 항목에서 지금까지 AI 판정이 사람보다 관대했습니다 "
            f"({directions['lenient']}/{len(items)}건). 애매하면 낮은 쪽을 고르세요. "
            "길이나 공손함은 근거가 되지 않습니다."
        )
    if directions["strict"] >= max(2, total * 0.6):
        return (
            f"이 항목에서 지금까지 AI 판정이 사람보다 엄격했습니다 "
            f"({directions['strict']}/{len(items)}건). 요건을 충족했다면 형식이 달라도 yes 로 보세요."
        )
    return f"이 항목은 사람 채점과 {total}건 어긋났습니다. 판정 기준을 다시 읽고 시작하세요."


# --- the loop -------------------------------------------------------------
def tune_judge(
    judge: Judge,
    ratings: list[HumanRating],
    traces: list[SessionTrace],
    *,
    previous: RubricOverlay | None = None,
    min_improvement: float = MIN_IMPROVEMENT,
) -> TuningResult:
    """Build an overlay from half the ratings and keep it only if κ improves."""
    usable = [r for r in ratings if rubric_for(r.metric) is not None]
    if len(usable) < MIN_RATINGS:
        return TuningResult(
            reason=f"사람 채점이 {len(usable)}건뿐입니다. 최소 {MIN_RATINGS}건이 필요합니다."
        )

    tune_set, holdout = split_ratings(usable)
    if not holdout:
        return TuningResult(reason="검증용으로 남길 채점이 없습니다.")

    judge.overlay = previous
    tune_labels = judge_labels_for(judge, traces, tune_set)
    holdout_before = judge_labels_for(judge, traces, holdout)
    kappa_before = _kappa(holdout, holdout_before)

    overlay = build_overlay(tune_set, tune_labels, traces, previous=previous)
    if not overlay.metrics:
        return TuningResult(
            reason="루브릭을 다듬을 근거를 찾지 못했습니다.",
            kappa_before=kappa_before,
            n_tune=len(tune_set),
            n_holdout=len(holdout),
        )

    judge.overlay = overlay
    holdout_after = judge_labels_for(judge, traces, holdout)
    kappa_after = _kappa(holdout, holdout_after)

    overlay.kappa_before = kappa_before
    overlay.kappa_after = kappa_after
    overlay.n_holdout = len(holdout)

    result = TuningResult(
        kappa_before=kappa_before,
        kappa_after=kappa_after,
        n_tune=len(tune_set),
        n_holdout=len(holdout),
        overlay=overlay,
        disagreements=find_disagreements(holdout, holdout_before, traces),
    )

    if kappa_before is None or kappa_after is None:
        result.reason = "일치도를 계산할 수 없어 적용하지 않았습니다."
        judge.overlay = previous
        return result
    if kappa_after >= kappa_before + min_improvement:
        result.accepted = True
        result.reason = (
            f"검증용 {len(holdout)}건에서 일치도가 {kappa_before:.2f} → {kappa_after:.2f} 로 "
            f"올랐습니다 (+{kappa_after - kappa_before:.2f})."
        )
        return result

    judge.overlay = previous
    result.reason = (
        f"개선 폭이 기준({min_improvement:+.2f})에 못 미칩니다 "
        f"({kappa_before:.2f} → {kappa_after:.2f}). 되돌립니다."
    )
    return result


# --- persistence ----------------------------------------------------------
def save_overlay(path: Path, overlay: RubricOverlay) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            overlay.model_dump(mode="json"),
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ),
        encoding="utf-8",
        newline="\n",
    )
    return path


def load_overlay(path: Path) -> RubricOverlay | None:
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not data:
        return None
    return RubricOverlay.model_validate(data)


def append_history(path: Path, result: TuningResult) -> Path:
    """Every round is recorded, including the rejected ones."""
    rows = []
    if path.exists():
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            rows = []
    rows.append(
        {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "accepted": result.accepted,
            "reason": result.reason,
            "kappa_before": result.kappa_before,
            "kappa_after": result.kappa_after,
            "n_tune": result.n_tune,
            "n_holdout": result.n_holdout,
            "version": result.overlay.version if result.overlay else None,
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    return path


# --- helpers --------------------------------------------------------------
#: How favourable a label is to the tutor. "Lenient" means the judge sat higher on
#: this scale than the human did.
_FAVOURABILITY = {Label.NO: 0, Label.PARTIAL: 1, Label.YES: 2}


def _favourability(label: Label) -> int:
    return _FAVOURABILITY.get(label, 1)


def _key(rating: HumanRating) -> ItemKey:
    return (rating.session_id, rating.turn_index, rating.metric)


def _rating_key(rating: HumanRating) -> tuple[str, str, int]:
    return (rating.metric, rating.session_id, rating.turn_index)


def _kappa(ratings: list[HumanRating], labels: dict[ItemKey, Label]) -> float | None:
    pairs = [(r.label.value, labels[_key(r)].value) for r in ratings if _key(r) in labels]
    if len(pairs) < 2:
        return None
    return cohens_kappa([p[0] for p in pairs], [p[1] for p in pairs])


__all__ = [
    "HISTORY_NAME",
    "MIN_IMPROVEMENT",
    "MIN_RATINGS",
    "OVERLAY_NAME",
    "Disagreement",
    "TuningResult",
    "append_history",
    "build_overlay",
    "find_disagreements",
    "judge_labels_for",
    "load_overlay",
    "save_overlay",
    "split_ratings",
    "tune_judge",
]
