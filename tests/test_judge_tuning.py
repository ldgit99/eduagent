"""Improving the judge prompt from human ratings — and refusing to when it does not help.

The guard these tests exist for is the one the plan is emphatic about: a judge
that agrees with itself is worthless, so a tuned rubric has to earn its place on
items it has never seen.
"""

from __future__ import annotations

from typing import Any

import pytest

from edu_agent.evaluator.calibration import HumanRating
from edu_agent.evaluator.judge import Judge, RubricOverlay
from edu_agent.evaluator.judge_tuning import (
    MIN_RATINGS,
    append_history,
    build_overlay,
    find_disagreements,
    judge_labels_for,
    load_overlay,
    save_overlay,
    split_ratings,
    tune_judge,
)
from edu_agent.providers.base import ChatMessage, Completion, Usage
from edu_agent.schemas.evaluation import Label
from edu_agent.schemas.trace import SessionTrace, TurnRecord

METRIC = "actionability"
OVERLAY_MARKER = "사람이 채점한 예"


# --- doubles --------------------------------------------------------------
class ScriptedJudge:
    """A judge model whose answer depends only on whether the overlay is present.

    ``improves`` is the whole experiment: a model that reads the human examples
    and one that ignores them should lead the loop to opposite decisions.
    """

    name = "scripted"
    model = "scripted"

    def __init__(self, *, improves: bool, truth: dict[int, str]) -> None:
        self.improves = improves
        self.truth = truth
        self.prompts: list[str] = []

    def complete(self, messages: list[ChatMessage], **kwargs: Any) -> Completion:
        prompt = "\n".join(m.content for m in messages)
        self.prompts.append(prompt)
        turn_index = _target_turn(prompt)
        if self.improves and OVERLAY_MARKER in prompt:
            label = self.truth.get(turn_index, "partial")
        else:
            label = "yes"  # the uncalibrated judge is cheerfully lenient
        return Completion(
            text=f'{{"label": "{label}", "rationale": "테스트", "turn_index": {turn_index}}}',
            model=self.model,
            usage=Usage(1, 1),
        )

    def ping(self) -> float:
        return 0.0


def _target_turn(prompt: str) -> int:
    marker = "판정 대상은 [턴 "
    if marker not in prompt:
        return -1
    return int(prompt.split(marker, 1)[1].split("]", 1)[0])


# --- fixtures -------------------------------------------------------------
@pytest.fixture
def trace() -> SessionTrace:
    session = SessionTrace(session_id="s_tune", scenario_id="T01", persona_id="S02")
    for index in range(12):
        session.turns.append(
            TurnRecord(
                turn_index=index,
                learner_message=f"{index}번째 질문입니다",
                tutor_message=("다음으로 무엇을 해 볼까요?" if index % 2 else "음, 그렇군요."),
            )
        )
    return session


@pytest.fixture
def truth() -> dict[int, str]:
    """What a human said about each turn: odd turns actionable, even ones not."""
    return {index: ("yes" if index % 2 else "no") for index in range(12)}


@pytest.fixture
def ratings(truth) -> list[HumanRating]:
    return [
        HumanRating(
            session_id="s_tune", turn_index=index, metric=METRIC, label=Label(label),
            note="다음 행동이 분명한지로 보았습니다",
        )
        for index, label in truth.items()
    ]


# --- splitting ------------------------------------------------------------
class TestSplit:
    def test_leaves_items_for_verification(self, ratings):
        tune, holdout = split_ratings(ratings)
        assert tune and holdout
        assert len(tune) + len(holdout) == len(ratings)

    def test_no_item_is_in_both_halves(self, ratings):
        tune, holdout = split_ratings(ratings)
        keys = {(r.session_id, r.turn_index, r.metric) for r in tune}
        assert not keys & {(r.session_id, r.turn_index, r.metric) for r in holdout}

    def test_is_deterministic(self, ratings):
        first = [r.turn_index for r in split_ratings(ratings)[0]]
        second = [r.turn_index for r in split_ratings(ratings)[0]]
        assert first == second

    def test_stratifies_by_metric(self, ratings):
        mixed = ratings + [
            HumanRating(session_id="s_tune", turn_index=i, metric="coherence", label=Label.YES)
            for i in range(4)
        ]
        tune, holdout = split_ratings(mixed)
        assert {r.metric for r in tune} == {METRIC, "coherence"}
        assert {r.metric for r in holdout} == {METRIC, "coherence"}


# --- building -------------------------------------------------------------
class TestBuildOverlay:
    def test_uses_human_labelled_turns_as_examples(self, ratings, trace):
        labels = {(r.session_id, r.turn_index, r.metric): Label.YES for r in ratings}
        overlay = build_overlay(ratings, labels, [trace])

        metric = overlay.metrics[METRIC]
        assert metric.exemplars
        assert all(e.tutor_message for e in metric.exemplars)

    def test_prefers_the_turns_the_judge_got_wrong(self, ratings, trace):
        labels = {(r.session_id, r.turn_index, r.metric): Label.YES for r in ratings}
        overlay = build_overlay(ratings, labels, [trace])
        # Every disagreement here is a human "no"; those are the useful examples.
        assert all(e.label is Label.NO for e in overlay.metrics[METRIC].exemplars)

    def test_names_the_direction_of_the_error(self, ratings, trace):
        labels = {(r.session_id, r.turn_index, r.metric): Label.YES for r in ratings}
        overlay = build_overlay(ratings, labels, [trace])
        assert "관대" in overlay.metrics[METRIC].note

    def test_notes_when_the_judge_was_too_strict(self, trace):
        strict = [
            HumanRating(session_id="s_tune", turn_index=i, metric=METRIC, label=Label.YES)
            for i in range(6)
        ]
        labels = {(r.session_id, r.turn_index, r.metric): Label.NO for r in strict}
        overlay = build_overlay(strict, labels, [trace])
        assert "엄격" in overlay.metrics[METRIC].note

    def test_version_increments_from_the_previous_overlay(self, ratings, trace):
        labels = {(r.session_id, r.turn_index, r.metric): Label.YES for r in ratings}
        first = build_overlay(ratings, labels, [trace])
        second = build_overlay(ratings, labels, [trace], previous=first)
        assert (first.version, second.version) == (1, 2)

    def test_ignores_metrics_with_no_rubric(self, trace):
        unknown = [
            HumanRating(session_id="s_tune", turn_index=0, metric="not_a_metric", label=Label.YES)
        ]
        assert build_overlay(unknown, {}, [trace]).metrics == {}


# --- the loop -------------------------------------------------------------
class TestTuneJudge:
    def test_adopts_a_rubric_that_improves_agreement(self, ratings, trace, truth):
        judge = Judge(ScriptedJudge(improves=True, truth=truth), order_swap=False)
        result = tune_judge(judge, ratings, [trace])

        assert result.accepted, result.reason
        assert result.delta is not None and result.delta > 0
        assert result.overlay is not None and result.overlay.version == 1
        assert judge.overlay is result.overlay

    def test_reverts_a_rubric_that_does_not(self, ratings, trace, truth):
        judge = Judge(ScriptedJudge(improves=False, truth=truth), order_swap=False)
        result = tune_judge(judge, ratings, [trace])

        assert not result.accepted
        assert "되돌" in result.reason or "못 미칩" in result.reason
        assert judge.overlay is None

    def test_verification_uses_items_the_overlay_never_saw(self, ratings, trace, truth):
        judge = Judge(ScriptedJudge(improves=True, truth=truth), order_swap=False)
        result = tune_judge(judge, ratings, [trace])

        assert result.overlay is not None
        exemplar_texts = {
            e.tutor_message for m in result.overlay.metrics.values() for e in m.exemplars
        }
        holdout_turns = {d.key[1] for d in result.disagreements}
        # Not a proof of independence on its own, but it catches the obvious bug:
        # a holdout that is really just the tuning set again.
        assert result.n_holdout > 0
        assert result.n_tune + result.n_holdout == len(ratings)
        assert exemplar_texts or not holdout_turns

    def test_refuses_when_there_is_too_little_to_learn_from(self, trace, truth):
        few = [
            HumanRating(session_id="s_tune", turn_index=i, metric=METRIC, label=Label.YES)
            for i in range(MIN_RATINGS - 1)
        ]
        judge = Judge(ScriptedJudge(improves=True, truth=truth), order_swap=False)
        result = tune_judge(judge, few, [trace])

        assert not result.accepted
        assert str(MIN_RATINGS) in result.reason

    def test_records_the_disagreements_it_found(self, ratings, trace, truth):
        judge = Judge(ScriptedJudge(improves=True, truth=truth), order_swap=False)
        result = tune_judge(judge, ratings, [trace])
        assert result.disagreements
        assert all(d.metric == METRIC for d in result.disagreements)


# --- per-turn judging -----------------------------------------------------
class TestScoreTurn:
    def test_judges_the_named_turn(self, trace, truth):
        model = ScriptedJudge(improves=False, truth=truth)
        label = Judge(model, order_swap=False).score_turn(METRIC, trace, 5)

        assert label is Label.YES
        assert "[턴 5]" in model.prompts[-1]

    def test_shows_surrounding_context_only(self, trace, truth):
        model = ScriptedJudge(improves=False, truth=truth)
        Judge(model, order_swap=False).score_turn(METRIC, trace, 5)
        prompt = model.prompts[-1]

        assert "[턴 3]" in prompt and "[턴 7]" in prompt
        assert "[턴 0]" not in prompt

    def test_missing_turn_does_not_raise(self, trace, truth):
        label = Judge(ScriptedJudge(improves=False, truth=truth)).score_turn(METRIC, trace, 99)
        assert label is Label.PARTIAL

    def test_overlay_reaches_the_prompt(self, trace, truth, ratings):
        labels = {(r.session_id, r.turn_index, r.metric): Label.YES for r in ratings}
        overlay = build_overlay(ratings, labels, [trace])
        model = ScriptedJudge(improves=False, truth=truth)
        Judge(model, order_swap=False, overlay=overlay).score_turn(METRIC, trace, 5)

        assert OVERLAY_MARKER in model.prompts[-1]
        assert "관대" in model.prompts[-1]


# --- persistence ----------------------------------------------------------
class TestPersistence:
    def test_overlay_round_trips(self, tmp_path, ratings, trace):
        labels = {(r.session_id, r.turn_index, r.metric): Label.YES for r in ratings}
        overlay = build_overlay(ratings, labels, [trace])
        path = save_overlay(tmp_path / "judge_overlay.yaml", overlay)
        reloaded = load_overlay(path)

        assert reloaded is not None
        assert reloaded.version == overlay.version
        assert reloaded.metrics[METRIC].note == overlay.metrics[METRIC].note

    def test_missing_overlay_is_not_an_error(self, tmp_path):
        assert load_overlay(tmp_path / "nothing.yaml") is None

    def test_history_records_rejected_rounds_too(self, tmp_path, ratings, trace, truth):
        judge = Judge(ScriptedJudge(improves=False, truth=truth), order_swap=False)
        result = tune_judge(judge, ratings, [trace])
        path = append_history(tmp_path / "history.json", result)

        import json

        rows = json.loads(path.read_text(encoding="utf-8"))
        assert len(rows) == 1
        assert rows[0]["accepted"] is False
        assert rows[0]["reason"]


def test_find_disagreements_carries_the_evidence(ratings, trace):
    labels = {(r.session_id, r.turn_index, r.metric): Label.YES for r in ratings}
    found = find_disagreements(ratings, labels, [trace])

    assert found
    assert all(d.judge is Label.YES for d in found)
    assert all(d.tutor_message for d in found)
    assert all(d.judge_was_lenient for d in found)


def test_judge_labels_for_only_asks_about_rated_items(ratings, trace, truth):
    model = ScriptedJudge(improves=False, truth=truth)
    labels = judge_labels_for(Judge(model, order_swap=False), [trace], ratings[:3])

    assert len(labels) == 3
    assert len(model.prompts) == 3


def test_empty_overlay_is_falsy_for_the_report():
    assert RubricOverlay().version == 0
