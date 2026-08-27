"""Schema invariants — IDs, conditions, and the hard/soft distinction."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from edu_agent.schemas.common import (
    DocumentStatus,
    IdPrefix,
    Strength,
    make_id,
    next_id,
    validate_id,
)
from edu_agent.schemas.educational import EducationalDesign, LearningObjective
from edu_agent.schemas.principles import (
    AgentAction,
    BehaviorRule,
    Constraint,
    ConstraintKind,
    DesignPrinciple,
    DesignPrinciples,
    LadderStep,
    TriggerEvent,
    validate_condition,
)


class TestIds:
    def test_make_and_validate(self):
        assert make_id(IdPrefix.PRINCIPLE, 2) == "P02"
        assert make_id(IdPrefix.CRITERION, 12) == "E12"
        assert validate_id("P02", IdPrefix.PRINCIPLE) == "P02"

    def test_wrong_prefix_rejected(self):
        with pytest.raises(ValueError, match="must start with"):
            validate_id("E01", IdPrefix.PRINCIPLE)

    def test_next_id_fills_gaps(self):
        assert next_id({"P01", "P03"}, IdPrefix.PRINCIPLE) == "P02"
        assert next_id(set(), IdPrefix.BEHAVIOR) == "B01"

    def test_next_id_ignores_other_prefixes(self):
        assert next_id({"E01", "E02"}, IdPrefix.PRINCIPLE) == "P01"


class TestConditions:
    @pytest.mark.parametrize(
        "expr",
        [
            "",
            "attempts >= 3",
            "reasoning_shown == true",
            "attempts >= 3 or stuck_turns >= 2",
            "reasoning_shown == true and attempts >= 2",
        ],
    )
    def test_valid(self, expr):
        assert validate_condition(expr) == expr.strip()

    @pytest.mark.parametrize(
        "expr",
        [
            "attempts",  # no operator
            "student.is_smart()",  # code injection shape
            "__import__('os').system('rm -rf /')",
            "attempts >= three",
        ],
    )
    def test_malformed_rejected(self, expr):
        with pytest.raises(ValueError):
            validate_condition(expr)

    def test_unknown_variable_rejected(self):
        with pytest.raises(ValueError, match="알 수 없는"):
            validate_condition("motivation >= 3")


class TestConstraints:
    def test_hard_constraint_is_gateable(self):
        c = Constraint(
            kind=ConstraintKind.NEVER_ACTION,
            strength=Strength.HARD,
            params={"action": "give_direct_answer"},
        )
        assert c.gateable

    def test_soft_constraint_is_not_gateable(self):
        c = Constraint(
            kind=ConstraintKind.NEVER_ACTION,
            strength=Strength.SOFT,
            params={"action": "give_direct_answer"},
        )
        assert not c.gateable

    def test_custom_constraint_downgraded_to_soft(self):
        """A free-text rule cannot be machine-checked, so it must not become a gate."""
        c = Constraint(kind=ConstraintKind.CUSTOM, strength=Strength.HARD, text="친절하게 말한다")
        assert c.strength is Strength.SOFT
        assert not c.gateable

    def test_missing_params_rejected(self):
        with pytest.raises(ValidationError):
            Constraint(kind=ConstraintKind.ACTION_ONLY_AFTER_LEVEL, params={"action": "x"})

    def test_condition_in_params_validated(self):
        with pytest.raises(ValidationError):
            Constraint(kind=ConstraintKind.NO_ANSWER_LEAKAGE_UNLESS, params={"when": "bogus!!"})


class TestBehaviorRule:
    def test_ladder_must_increase(self):
        with pytest.raises(ValidationError):
            BehaviorRule(
                id="B01",
                name="x",
                triggers=[TriggerEvent.TURN_ANY],
                ladder=[
                    LadderStep(level=2, action=AgentAction.ASK_FOR_REASONING),
                    LadderStep(level=1, action=AgentAction.PROVIDE_DIRECTIONAL_HINT),
                ],
            )

    def test_needs_ladder_or_actions(self):
        with pytest.raises(ValidationError, match="ladder or at least one action"):
            BehaviorRule(id="B01", name="x", triggers=[TriggerEvent.TURN_ANY])

    def test_needs_trigger(self):
        with pytest.raises(ValidationError, match="trigger"):
            BehaviorRule(id="B01", name="x", actions=[AgentAction.ASK_FOR_REASONING])


class TestDesignPrinciples:
    def test_duplicate_ids_rejected(self):
        rule = BehaviorRule(
            id="B01", name="r", triggers=[TriggerEvent.TURN_ANY],
            actions=[AgentAction.ASK_FOR_REASONING],
        )
        with pytest.raises(ValidationError, match="중복된 id"):
            DesignPrinciples.new().model_copy(
                update={
                    "principles": [
                        DesignPrinciple(id="P01", name="a", rules=[rule]),
                        DesignPrinciple(id="P01", name="b"),
                    ]
                }
            ).model_validate(
                {
                    "meta": DesignPrinciples.new().meta.model_dump(),
                    "principles": [
                        {"id": "P01", "name": "a", "rules": [rule.model_dump()]},
                        {"id": "P01", "name": "b"},
                    ],
                }
            )

    def test_unconfirmed_principles_excluded(self):
        doc = DesignPrinciples.new()
        doc.principles = [
            DesignPrinciple(id="P01", name="a", confirmed=True),
            DesignPrinciple(id="P02", name="b", confirmed=False),
        ]
        assert [p.id for p in doc.confirmed_principles()] == ["P01"]

    def test_answer_condition_validated(self):
        with pytest.raises(ValidationError):
            DesignPrinciples.new().model_validate(
                {
                    "meta": DesignPrinciples.new().meta.model_dump(),
                    "answer_condition": "if student.wants: give()",
                }
            )


class TestEducationalDesign:
    def test_missing_required_reports_gaps(self):
        doc = EducationalDesign.new()
        missing = doc.missing_required()
        assert "context.target_learners" in missing
        assert "objectives" in missing

    def test_complete_document_has_no_gaps(self):
        from edu_agent.schemas.educational import (
            LearningContext,
            LearningProblem,
            SupportType,
        )

        doc = EducationalDesign.new()
        doc.context = LearningContext(target_learners="중2", subject="정보")
        doc.problem = LearningProblem(core_problem="정답만 요구함")
        doc.objectives = [LearningObjective(id="O01", statement="할 수 있다")]
        doc.expected_support.types = [SupportType.HINT]
        assert doc.missing_required() == []

    def test_schema_name_is_classvar(self):
        """Regression: a bare annotation would make it a Pydantic field."""
        assert EducationalDesign.SCHEMA_NAME == "educational_design"
        assert "SCHEMA_NAME" not in EducationalDesign.model_fields
        assert EducationalDesign.new().meta.schema_name == "educational_design"
        assert EducationalDesign.new().meta.status is DocumentStatus.DRAFT
