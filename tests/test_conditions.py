"""The learner-state condition language.

This grammar used to be written twice — a validating regex in the schemas and an
evaluating one in the runtime. These tests hold the two ends to *one* definition:
whatever the documents accept, the runtime must read the same way. Drift here is
not cosmetic; a condition validated one way and evaluated another silently
changes when a hard gate opens.
"""

from __future__ import annotations

import pytest

from edu_agent.runtime.state import LearnerState, evaluate_condition
from edu_agent.schemas.conditions import (
    STATE_VARIABLES,
    Condition,
    ConditionError,
    evaluate,
    parse,
    validate,
)
from edu_agent.schemas.principles import validate_condition

WELL_FORMED = [
    "attempts >= 3",
    "attempts>=3",
    "  attempts >= 3  ",
    "reasoning_shown == true",
    "misconception_active != false",
    "attempts >= 3 or stuck_turns >= 2",
    "reasoning_shown == true and attempts >= 2",
    "attempts > 0 and stuck_turns < 5 or help_requests >= 1",
    "turn_index <= 10",
]

MALFORMED = [
    "nonsense",
    "attempts",
    "attempts >=",
    ">= 3",
    "attempts >= three",
    "attempts >= 3 and",
    "attempts >= 3 or or stuck_turns >= 1",
    "attempts == 3 xor stuck_turns == 1",
    "__import__('os')",
    "attempts.__class__ == 1",
    "attempts >= 3; import os",
]


def _lookup(**values):
    state = LearnerState()
    for name, value in values.items():
        state.set(name, value)
    return state.get


class TestGrammar:
    @pytest.mark.parametrize("expr", WELL_FORMED)
    def test_accepts_what_it_should(self, expr):
        assert isinstance(parse(expr), Condition)
        assert validate(expr) == expr.strip()

    @pytest.mark.parametrize("expr", MALFORMED)
    def test_rejects_what_it_should(self, expr):
        with pytest.raises(ConditionError):
            parse(expr)

    def test_empty_means_always(self):
        assert parse("") is None
        assert parse("   ") is None
        assert evaluate("", _lookup()) is True

    def test_unknown_variables_are_named_in_the_error(self):
        with pytest.raises(ConditionError, match="attemps"):
            validate("attemps >= 3")

    def test_every_declared_variable_is_usable(self):
        for name in STATE_VARIABLES:
            assert validate(f"{name} >= 1") == f"{name} >= 1"


class TestEvaluation:
    def test_integers(self):
        lookup = _lookup(attempts=3)
        assert evaluate("attempts >= 3", lookup)
        assert evaluate("attempts > 2", lookup)
        assert not evaluate("attempts > 3", lookup)
        assert evaluate("attempts != 4", lookup)

    def test_booleans(self):
        lookup = _lookup(reasoning_shown=True)
        assert evaluate("reasoning_shown == true", lookup)
        assert not evaluate("reasoning_shown == false", lookup)
        assert evaluate("reasoning_shown != false", lookup)

    def test_and_or(self):
        lookup = _lookup(attempts=3, stuck_turns=0)
        assert evaluate("attempts >= 3 or stuck_turns >= 2", lookup)
        assert not evaluate("attempts >= 3 and stuck_turns >= 2", lookup)

    def test_left_to_right_with_no_precedence(self):
        """Stated, not inherited: the grammar has no parentheses to express intent.

        ``a or b and c`` groups as ``(a or b) and c`` here, unlike Python.
        """
        lookup = _lookup(attempts=1, stuck_turns=0, help_requests=0)
        # (attempts >= 1 or stuck_turns >= 9) and help_requests >= 9  ->  False
        assert not evaluate("attempts >= 1 or stuck_turns >= 9 and help_requests >= 9", lookup)

    def test_malformed_fails_closed(self):
        """A condition the runtime cannot read guards a hard gate. It must not open it."""
        for expr in MALFORMED:
            assert evaluate(expr, _lookup(attempts=99)) is False


class TestTheTwoEndsAgree:
    """What a document may contain is exactly what the runtime can evaluate."""

    @pytest.mark.parametrize("expr", WELL_FORMED)
    def test_validated_conditions_are_evaluable(self, expr):
        validate_condition(expr)
        assert evaluate_condition(expr, LearnerState()) in (True, False)

    @pytest.mark.parametrize("expr", MALFORMED)
    def test_rejected_conditions_never_reach_the_runtime_as_true(self, expr):
        with pytest.raises(ValueError):
            validate_condition(expr)
        assert evaluate_condition(expr, LearnerState()) is False

    def test_the_documents_and_the_runtime_share_one_vocabulary(self):
        from edu_agent.schemas import principles

        assert principles.STATE_VARIABLES is STATE_VARIABLES

    def test_the_runtime_tracks_every_variable_a_document_may_name(self):
        state = LearnerState()
        for name in STATE_VARIABLES:
            assert name in state.values or state.get(name) is not None
