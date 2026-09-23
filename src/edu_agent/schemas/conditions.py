"""The learner-state condition language — parsed once, used twice.

``attempts >= 3 or stuck_turns >= 2`` is what lets a design principle say *when*
the answer may be given. It is deliberately tiny so that a string coming out of a
student's Markdown file can never execute code: no ``eval``, no attribute access,
no function calls. Only ``<var> <op> <int|true|false>`` joined by ``and``/``or``.

This module exists because the grammar used to be written twice — a validating
regex in the schemas and an evaluating one in the runtime. Two definitions of one
language drift, and the direction of that drift is dangerous: a condition the
validator accepts but the evaluator misreads silently changes when a hard gate
opens.

Precedence is **left to right**, with no special status for ``and``. That is not
Python's rule, so it is stated here and tested, rather than left to whichever
implementation a reader happens to open. The grammar has no parentheses, so
anything relying on precedence is better written as two conditions anyway.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

#: Variables the runtime tracks. Part of the grammar's vocabulary, so they live
#: with the grammar rather than with the documents that happen to use it.
STATE_VARIABLES: tuple[str, ...] = (
    "attempts",
    "help_requests",
    "answer_requests",
    "stuck_turns",
    "ladder_level",
    "misconception_active",
    "reasoning_shown",
    "off_task_count",
    "frustration_flag",
    "pii_detected",
    "task_completed",
    "turn_index",
)

OPERATORS = ("<=", ">=", "==", "!=", "<", ">")

_COMPARISON = re.compile(
    r"^\s*(?P<var>[a-z_][a-z0-9_]*)\s*(?P<op><=|>=|==|!=|<|>)\s*(?P<value>true|false|\d+)\s*$"
)
_JUNCTION = re.compile(r"\s+(and|or)\s+")


class ConditionError(ValueError):
    """The expression is not in the supported grammar."""


@dataclass(frozen=True, slots=True)
class Comparison:
    variable: str
    operator: str
    value: int | bool

    def evaluate(self, lookup: Callable[[str], int | bool]) -> bool:
        current = lookup(self.variable)
        if isinstance(self.value, bool):
            return _compare(bool(current), self.value, self.operator)
        left = int(bool(current)) if isinstance(current, bool) else int(current)
        return _compare(left, self.value, self.operator)


@dataclass(frozen=True, slots=True)
class Condition:
    """One or more comparisons joined left to right."""

    first: Comparison
    rest: tuple[tuple[str, Comparison], ...] = ()

    def evaluate(self, lookup: Callable[[str], int | bool]) -> bool:
        result = self.first.evaluate(lookup)
        for junction, comparison in self.rest:
            value = comparison.evaluate(lookup)
            result = (result and value) if junction == "and" else (result or value)
        return result

    def variables(self) -> tuple[str, ...]:
        return (self.first.variable, *(c.variable for _, c in self.rest))


def parse(expr: str) -> Condition | None:
    """Parse ``expr``. Empty means "always", which is ``None``."""
    text = (expr or "").strip()
    if not text:
        return None

    parts = _JUNCTION.split(text)
    if len(parts) % 2 == 0:  # a trailing and/or
        raise ConditionError(_unreadable(text))

    first = _comparison(parts[0], text)
    rest: list[tuple[str, Comparison]] = []
    for index in range(1, len(parts) - 1, 2):
        rest.append((parts[index], _comparison(parts[index + 1], text)))
    return Condition(first, tuple(rest))


def validate(expr: str, *, known: tuple[str, ...] = STATE_VARIABLES) -> str:
    """Parse and check the variable names, returning the trimmed expression."""
    condition = parse(expr)
    if condition is None:
        return ""
    for name in condition.variables():
        if name not in known:
            raise ConditionError(
                f"알 수 없는 학습자 상태 변수 {name!r}. 사용 가능: {', '.join(known)}"
            )
    return expr.strip()


def evaluate(expr: str, lookup: Callable[[str], int | bool]) -> bool:
    """Evaluate ``expr``. Empty is true; **malformed is false**.

    Failing closed matters: a condition the runtime cannot read guards a hard
    gate, and treating it as "always true" would open that gate silently.
    """
    try:
        condition = parse(expr)
    except ConditionError:
        return False
    if condition is None:
        return True
    return condition.evaluate(lookup)


def _comparison(text: str, whole: str) -> Comparison:
    match = _COMPARISON.match(text)
    if not match:
        raise ConditionError(_unreadable(whole))
    raw = match.group("value")
    value: int | bool = raw == "true" if raw in {"true", "false"} else int(raw)
    return Comparison(match.group("var"), match.group("op"), value)


def _compare(left: int | bool, right: int | bool, operator: str) -> bool:
    match operator:
        case "==":
            return left == right
        case "!=":
            return left != right
        case ">=":
            return int(left) >= int(right)
        case "<=":
            return int(left) <= int(right)
        case ">":
            return int(left) > int(right)
        case "<":
            return int(left) < int(right)
    return False


def _unreadable(expr: str) -> str:
    return (
        f"조건식을 이해할 수 없습니다: {expr!r}. "
        "예: 'attempts >= 2', 'reasoning_shown == true and stuck_turns >= 1'"
    )


__all__ = [
    "OPERATORS",
    "STATE_VARIABLES",
    "Comparison",
    "Condition",
    "ConditionError",
    "evaluate",
    "parse",
    "validate",
]
