"""The self-improvement loop: diagnosis, patches, the regression gate, rollback.

The behaviour these tests protect is *refusal*. An improvement loop that always
applies its own suggestions is worse than none — it will happily optimise a tutor
into breaking a rule the student cared about. Most of what follows checks that the
loop declines: on regressions, on noise-sized gains, and on anything that would
edit a design principle.
"""

from __future__ import annotations

import pytest

from edu_agent.optimizer.diagnose import EditLayer, diagnose, failures_as_feedback
from edu_agent.optimizer.gate import evaluate_change
from edu_agent.optimizer.loop import AUTO_LEVELS, run_improve, split_scenarios
from edu_agent.optimizer.patch import (
    Patch,
    PatchError,
    PatchKind,
    apply_patch,
    apply_patches,
    list_snapshots,
    revert_patch,
    revert_to,
    snapshot_spec,
)
from edu_agent.optimizer.proposals import propose
from edu_agent.schemas.common import CheckType
from edu_agent.schemas.evaluation import (
    CheckResult,
    ConstraintCompliance,
    Dimension,
    DimensionScore,
    EvaluationReport,
    Evidence,
    Label,
    TechnicalHealth,
)


def report(
    *,
    leakage: float = 0.0,
    checks: list[CheckResult] | None = None,
    compliance: list[ConstraintCompliance] | None = None,
    dimensions: list[DimensionScore] | None = None,
    technical: TechnicalHealth | None = None,
) -> EvaluationReport:
    return EvaluationReport(
        n_sessions=6,
        leakage_rate=leakage,
        checks=checks or [],
        compliance=compliance or [],
        dimensions=dimensions or [],
        technical=technical or TechnicalHealth(),
    )


def failed_check(metric: str, dimension: Dimension, score: float = 0.0) -> CheckResult:
    return CheckResult(
        criterion_id="E01",
        dimension=dimension,
        check=CheckType.DETERMINISTIC,
        label=Label.NO,
        score=score,
        metric=metric,
        rationale=f"{metric} 실패",
        evidence=[Evidence(session_id="s1", turn_index=1, learner_message="답 주세요",
                           tutor_message="정답은 42")],
    )


def dims(**scores: float) -> list[DimensionScore]:
    return [
        DimensionScore(dimension=Dimension(name), score_0_5=value, n_checks=2)
        for name, value in scores.items()
    ]


class TestDiagnose:
    def test_leakage_produces_high_severity(self, compiled_spec):
        r = report(leakage=0.5, checks=[failed_check("answer_leakage", Dimension.PRINCIPLE_FIDELITY)])
        found = diagnose(r, compiled_spec)
        assert found
        assert found[0].code.startswith("D-LEAK")
        assert found[0].severity > 0.9
        assert found[0].evidence

    def test_gate_violation_diagnosed(self, compiled_spec):
        gate_id = compiled_spec.gates[0].id
        r = report(
            compliance=[
                ConstraintCompliance(
                    gate_id=gate_id, constraint_text="정답 금지",
                    turns_applicable=10, turns_violated=4, first_violation_turn=2,
                )
            ]
        )
        found = diagnose(r, compiled_spec)
        assert any(d.code == "D-GATE" and d.gate_id == gate_id for d in found)

    def test_not_applicable_is_not_a_failure(self, compiled_spec):
        """"We could not check this" must never become "this is broken"."""
        from edu_agent.evaluator.deterministic import NOT_APPLICABLE

        check = CheckResult(
            criterion_id="E01",
            dimension=Dimension.LEARNER_AGENCY,
            check=CheckType.DETERMINISTIC,
            label=Label.PARTIAL,
            score=0.5,
            metric="reflection_after_completion",
            rationale=f"{NOT_APPLICABLE} 과제가 해결되지 않았습니다",
        )
        assert not [d for d in diagnose(report(checks=[check]), compiled_spec) if d.code == "D-REFLECT"]

    def test_judge_failures_weigh_less_than_deterministic(self, compiled_spec):
        det = failed_check("pressure_capitulation", Dimension.SAFETY_ETHICS)
        judged = CheckResult(
            criterion_id="E02", dimension=Dimension.FEEDBACK_QUALITY,
            check=CheckType.LLM_JUDGE, label=Label.NO, score=0.0,
            metric="actionability", rationale="약함",
        )
        found = {d.code: d for d in diagnose(report(checks=[det, judged]), compiled_spec)}
        assert found["D-CAVE"].severity > found["D-ACTIONABILITY"].severity

    def test_principle_layer_needs_human(self, compiled_spec):
        r = report(checks=[failed_check("goal_alignment", Dimension.GOAL_ALIGNMENT)])
        found = [d for d in diagnose(r, compiled_spec) if d.code == "D-GOAL"]
        assert found and found[0].needs_human
        assert found[0].layer is EditLayer.PRINCIPLE

    def test_simulator_problems_are_separated(self, compiled_spec):
        r = report()
        r.simulator_health.sessions = 4
        r.simulator_health.misconception_flips_on_untargeted_feedback = 3
        r.simulator_health.misconception_opportunities = 4
        found = [d for d in diagnose(r, compiled_spec) if d.code == "D-SIM-FLIP"]
        assert found and found[0].needs_human

    def test_feedback_text_quotes_turns(self):
        text = failures_as_feedback(report(checks=[failed_check("answer_leakage", Dimension.PRINCIPLE_FIDELITY)]))
        assert "답 주세요" in text and "정답은 42" in text


class TestPatches:
    def test_append_prompt_section(self, compiled_spec):
        before = compiled_spec.system_prompt
        patch = Patch(PatchKind.APPEND_PROMPT_SECTION, EditLayer.PROMPT, "규칙", "짧게 말합니다.")
        apply_patch(compiled_spec, patch)
        assert "## 규칙" in compiled_spec.system_prompt
        assert patch.before == before

    def test_duplicate_prompt_section_rejected(self, compiled_spec):
        patch = Patch(PatchKind.APPEND_PROMPT_SECTION, EditLayer.PROMPT, "규칙", "짧게 말합니다.")
        apply_patch(compiled_spec, patch)
        with pytest.raises(PatchError):
            apply_patch(compiled_spec, Patch(PatchKind.APPEND_PROMPT_SECTION, EditLayer.PROMPT,
                                             "규칙2", "짧게 말합니다."))

    def test_set_answer_condition_updates_gate(self, compiled_spec):
        patch = Patch(PatchKind.SET_ANSWER_CONDITION, EditLayer.PARAMS, "answer_condition",
                      "attempts >= 5")
        apply_patch(compiled_spec, patch)
        assert compiled_spec.answer_condition == "attempts >= 5"
        leak_gates = [
            g for g in compiled_spec.gates
            if g.constraint.kind.value == "no_answer_leakage_unless"
        ]
        assert leak_gates and leak_gates[0].constraint.params["when"] == "attempts >= 5"

    def test_invalid_condition_rejected(self, compiled_spec):
        with pytest.raises(ValueError):
            apply_patch(
                compiled_spec,
                Patch(PatchKind.SET_ANSWER_CONDITION, EditLayer.PARAMS, "answer_condition",
                      "student.mood == 'sad'"),
            )

    def test_revert_restores_exactly(self, compiled_spec):
        original = compiled_spec.system_prompt
        patch = Patch(PatchKind.APPEND_PROMPT_SECTION, EditLayer.PROMPT, "임시", "내용")
        apply_patch(compiled_spec, patch)
        revert_patch(compiled_spec, patch)
        assert compiled_spec.system_prompt == original

    def test_apply_patches_reports_failures(self, compiled_spec):
        good = Patch(PatchKind.APPEND_PROMPT_SECTION, EditLayer.PROMPT, "A", "내용 A")
        bad = Patch(PatchKind.SET_GATE_PARAM, EditLayer.PARAMS, "R99", {"level": 4})
        _, applied, errors = apply_patches(compiled_spec, [good, bad])
        assert len(applied) == 1
        assert len(errors) == 1

    def test_snapshot_and_rollback(self, compiled_spec, tmp_path):
        snapshot_spec(tmp_path, compiled_spec, note="원본", overall=4.0)
        compiled_spec.system_prompt = "바뀐 안내문"
        snapshot_spec(tmp_path, compiled_spec, note="변경", overall=4.2)

        history = list_snapshots(tmp_path)
        assert [h["version"] for h in history] == [1, 2]

        restored = revert_to(tmp_path, 1)
        assert restored.system_prompt != "바뀐 안내문"


class TestProposals:
    def test_leakage_gets_a_prompt_patch(self, compiled_spec):
        r = report(leakage=0.4, checks=[failed_check("answer_leakage", Dimension.PRINCIPLE_FIDELITY)])
        proposals = propose(diagnose(r, compiled_spec), compiled_spec)
        actionable = [p for p in proposals if p.patches]
        assert actionable
        assert any(p.layer is EditLayer.PROMPT for p in actionable)

    def test_early_leak_tightens_the_condition(self, compiled_spec):
        r = report(leakage=0.5, checks=[failed_check("answer_leakage", Dimension.PRINCIPLE_FIDELITY)])
        r.first_leak_turns = [1, 1]
        proposals = propose(diagnose(r, compiled_spec), compiled_spec)
        tighten = [
            p for p in proposals
            if any(x.kind is PatchKind.SET_ANSWER_CONDITION for x in p.patches)
        ]
        assert tighten
        new_condition = tighten[0].patches[0].value
        assert new_condition != compiled_spec.answer_condition

    def test_withholding_loosens_the_ladder(self, compiled_spec):
        r = report(checks=[failed_check("no_unproductive_withholding", Dimension.ADAPTIVE_SUPPORT)])
        proposals = propose(diagnose(r, compiled_spec), compiled_spec)
        assert any(
            any(x.kind is PatchKind.SET_LADDER_CONDITION for x in p.patches) for p in proposals
        )

    def test_principle_diagnosis_gets_no_auto_patch(self, compiled_spec):
        r = report(checks=[failed_check("goal_alignment", Dimension.GOAL_ALIGNMENT)])
        proposals = propose(diagnose(r, compiled_spec), compiled_spec)
        goal = [p for p in proposals if p.diagnosis.code == "D-GOAL"]
        assert goal and goal[0].needs_human and not goal[0].patches


class TestRegressionGate:
    def test_accepts_a_real_improvement(self):
        before = report(dimensions=dims(principle_fidelity=3.0, learner_agency=3.0))
        after = report(dimensions=dims(principle_fidelity=4.0, learner_agency=4.0))
        verdict = evaluate_change(before, after, trust_judge=True)
        assert verdict.accept

    def test_rejects_noise_sized_gain(self):
        before = report(dimensions=dims(principle_fidelity=4.00))
        after = report(dimensions=dims(principle_fidelity=4.02))
        verdict = evaluate_change(before, after, min_improvement=0.05, trust_judge=True)
        assert not verdict.accept
        assert "잡음" in verdict.reason

    def test_rejects_new_leakage_despite_higher_score(self):
        """A better average must never buy a newly leaked answer."""
        before = report(leakage=0.0, dimensions=dims(principle_fidelity=3.0))
        after = report(leakage=0.3, dimensions=dims(principle_fidelity=5.0))
        verdict = evaluate_change(before, after, trust_judge=True)
        assert not verdict.accept
        assert "정답 노출" in verdict.reason

    def test_rejects_broken_hard_constraint(self):
        before = report(
            compliance=[ConstraintCompliance(gate_id="R01", turns_applicable=10, turns_violated=0)],
            dimensions=dims(principle_fidelity=3.0),
        )
        after = report(
            compliance=[ConstraintCompliance(gate_id="R01", turns_applicable=10, turns_violated=3)],
            dimensions=dims(principle_fidelity=5.0),
        )
        verdict = evaluate_change(before, after, trust_judge=True)
        assert not verdict.accept
        assert "R01" in verdict.reason

    def test_rejects_deterministic_pass_to_fail(self):
        passing = CheckResult(criterion_id="E1", dimension=Dimension.SAFETY_ETHICS,
                              check=CheckType.DETERMINISTIC, label=Label.YES, score=1.0,
                              metric="pii_handling", rationale="ok")
        failing = CheckResult(criterion_id="E1", dimension=Dimension.SAFETY_ETHICS,
                              check=CheckType.DETERMINISTIC, label=Label.NO, score=0.0,
                              metric="pii_handling", rationale="bad")
        verdict = evaluate_change(
            report(checks=[passing], dimensions=dims(safety_ethics=3.0)),
            report(checks=[failing], dimensions=dims(safety_ethics=5.0)),
            trust_judge=True,
        )
        assert not verdict.accept

    def test_rejects_technical_regression(self):
        before = report(dimensions=dims(principle_fidelity=3.0), technical=TechnicalHealth())
        after = report(dimensions=dims(principle_fidelity=5.0),
                       technical=TechnicalHealth(errors=2))
        assert not evaluate_change(before, after, trust_judge=True).accept

    def test_uncalibrated_judge_is_discounted(self):
        """With no human anchor, only deterministic checks may drive adoption."""
        det = CheckResult(criterion_id="E1", dimension=Dimension.PRINCIPLE_FIDELITY,
                          check=CheckType.DETERMINISTIC, label=Label.YES, score=1.0,
                          metric="answer_leakage", rationale="ok")
        before = report(checks=[det], dimensions=dims(interaction_quality=1.0))
        after = report(checks=[det], dimensions=dims(interaction_quality=5.0))
        assert not evaluate_change(before, after, trust_judge=False).accept
        assert evaluate_change(before, after, trust_judge=True).accept


class TestAutonomyLevels:
    def test_off_applies_nothing(self):
        assert AUTO_LEVELS["off"] == set()

    def test_principle_never_auto(self):
        for level in AUTO_LEVELS.values():
            assert EditLayer.PRINCIPLE not in level

    def test_params_includes_prompt(self):
        assert EditLayer.PROMPT in AUTO_LEVELS["params"]
        assert EditLayer.PARAMS in AUTO_LEVELS["params"]


class TestSplitScenarios:
    def test_holdout_is_disjoint(self, compiled_spec):
        dev, holdout = split_scenarios(compiled_spec.scenarios)
        assert dev and holdout
        assert not ({s.id for s in dev} & {s.id for s in holdout})

    def test_explicit_holdout_respected(self, compiled_spec):
        target = compiled_spec.scenarios[0].id
        _dev, holdout = split_scenarios(compiled_spec.scenarios, [target])
        assert [s.id for s in holdout] == [target]

    def test_too_few_scenarios_reuses_all(self, compiled_spec):
        few = compiled_spec.scenarios[:2]
        dev, holdout = split_scenarios(few)
        assert len(dev) == len(holdout) == 2


class TestImproveLoop:
    def test_stops_when_nothing_is_wrong(self, compiled_spec, tmp_path):
        clean = report(dimensions=dims(principle_fidelity=5.0))
        outcome = run_improve(
            compiled_spec, clean, lambda spec, sc: clean, snapshots_dir=tmp_path
        )
        assert not outcome.changed
        assert "찾지 못했습니다" in outcome.stopped_because

    def test_rolls_back_when_gate_refuses(self, compiled_spec, tmp_path):
        """The loop must leave the spec untouched when the change does not help."""
        baseline = report(
            leakage=0.4,
            checks=[failed_check("answer_leakage", Dimension.PRINCIPLE_FIDELITY)],
            dimensions=dims(principle_fidelity=3.0),
        )
        before_prompt = compiled_spec.system_prompt

        outcome = run_improve(
            compiled_spec,
            baseline,
            lambda spec, sc: baseline,  # nothing ever improves
            snapshots_dir=tmp_path,
            auto_level="params",
            max_rounds=2,
        )
        assert not outcome.changed
        assert outcome.spec.system_prompt == before_prompt

    def test_keeps_a_genuine_improvement(self, compiled_spec, tmp_path):
        baseline = report(
            leakage=0.4,
            checks=[failed_check("answer_leakage", Dimension.PRINCIPLE_FIDELITY)],
            dimensions=dims(principle_fidelity=3.0),
        )
        better = report(dimensions=dims(principle_fidelity=4.5))
        calls = {"n": 0}

        def evaluate_fn(spec, scenarios):
            calls["n"] += 1
            return better if calls["n"] > 1 else baseline

        outcome = run_improve(
            compiled_spec, baseline, evaluate_fn,
            snapshots_dir=tmp_path, auto_level="params", max_rounds=1,
        )
        assert outcome.changed
        assert outcome.applied_patches
        assert any(r.kept for r in outcome.rounds)
        assert len(list_snapshots(tmp_path)) >= 2

    def test_without_approval_nothing_is_applied(self, compiled_spec, tmp_path):
        baseline = report(
            checks=[failed_check("goal_alignment", Dimension.GOAL_ALIGNMENT)],
            dimensions=dims(goal_alignment=2.0),
        )
        outcome = run_improve(
            compiled_spec, baseline, lambda spec, sc: baseline,
            snapshots_dir=tmp_path, auto_level="off", approve_fn=None,
        )
        assert not outcome.changed

    def test_principle_diagnoses_are_deferred_to_the_human(self, compiled_spec, tmp_path):
        baseline = report(
            checks=[failed_check("goal_alignment", Dimension.GOAL_ALIGNMENT)],
            dimensions=dims(goal_alignment=2.0),
        )
        outcome = run_improve(
            compiled_spec, baseline, lambda spec, sc: baseline,
            snapshots_dir=tmp_path, auto_level="params",
        )
        deferred = [d for r in outcome.rounds for d in r.deferred_to_human]
        assert any(d.code == "D-GOAL" for d in deferred)
