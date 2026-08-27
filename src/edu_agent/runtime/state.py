"""Learner state and the tiny condition language.

Conditions such as ``attempts >= 3 or stuck_turns >= 2`` are what let a design
principle say *when* the answer may be given, instead of the blanket "never" the
literature warns against. They are evaluated here **without ``eval``** — the
grammar is deliberately small (see
:func:`edu_agent.schemas.principles.validate_condition`) so that a string coming
from a student's Markdown file can never execute code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from edu_agent.schemas.agent import StateVariableSpec
from edu_agent.schemas.principles import STATE_VARIABLES, TriggerEvent

_TOKEN = re.compile(
    r"(?P<var>[a-z_][a-z0-9_]*)\s*(?P<op><=|>=|==|!=|<|>)\s*(?P<val>true|false|\d+)"
)
_SPLIT = re.compile(r"\s+(and|or)\s+")


@dataclass(slots=True)
class LearnerState:
    """Variables the runtime tracks for one conversation.

    Kept as a flat dict rather than typed fields so a project can declare extra
    variables in ``04_agent_spec.md`` without a schema change.
    """

    values: dict[str, int | bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in STATE_VARIABLES:
            self.values.setdefault(name, False if name in _BOOL_VARS else 0)

    # --- access ----------------------------------------------------------
    def get(self, name: str) -> int | bool:
        return self.values.get(name, 0)

    def set(self, name: str, value: int | bool) -> None:
        self.values[name] = value

    def incr(self, name: str, by: int = 1) -> None:
        current = self.values.get(name, 0)
        self.values[name] = (int(current) if not isinstance(current, bool) else 0) + by

    def reset(self, name: str) -> None:
        self.values[name] = False if name in _BOOL_VARS else 0

    def snapshot(self) -> dict[str, int | bool]:
        return dict(self.values)

    def summary_ko(self) -> str:
        """A compact, human-readable state line for the model prompt."""
        v = self.values
        parts = [
            f"학습자 시도 횟수: {v.get('attempts', 0)}",
            f"도움 요청: {v.get('help_requests', 0)}",
            f"정답 요구: {v.get('answer_requests', 0)}",
            f"연속 막힘: {v.get('stuck_turns', 0)}턴",
            f"현재 지원 단계: {v.get('ladder_level', 0)}",
            f"학습자가 자기 추론을 말함: {'예' if v.get('reasoning_shown') else '아니오'}",
        ]
        if v.get("misconception_active"):
            parts.append("오개념이 활성 상태입니다")
        if v.get("frustration_flag"):
            parts.append("학습자가 좌절을 표현했습니다")
        if v.get("off_task_count"):
            parts.append(f"이탈 {v['off_task_count']}회")
        return " · ".join(parts)


_BOOL_VARS = frozenset(
    {
        "misconception_active",
        "reasoning_shown",
        "frustration_flag",
        "pii_detected",
        "task_completed",
    }
)


def evaluate_condition(expr: str, state: LearnerState) -> bool:
    """Evaluate a ``when`` expression against ``state``. Empty means always true."""
    expr = (expr or "").strip()
    if not expr:
        return True

    parts = _SPLIT.split(expr)
    result = _atom(parts[0], state)
    i = 1
    while i + 1 < len(parts):
        op, rhs = parts[i], parts[i + 1]
        value = _atom(rhs, state)
        result = (result and value) if op == "and" else (result or value)
        i += 2
    return result


def _atom(text: str, state: LearnerState) -> bool:
    m = _TOKEN.search(text)
    if not m:
        # A malformed condition must not silently become "always true": that would
        # open a hard gate. Fail closed.
        return False
    var, op, raw = m.group("var"), m.group("op"), m.group("val")
    current = state.get(var)
    if raw in {"true", "false"}:
        expected: int | bool = raw == "true"
        left: int | bool = bool(current)
    else:
        expected = int(raw)
        left = int(current) if not isinstance(current, bool) else int(bool(current))

    match op:
        case "==":
            return left == expected
        case "!=":
            return left != expected
        case ">=":
            return int(left) >= int(expected)
        case "<=":
            return int(left) <= int(expected)
        case ">":
            return int(left) > int(expected)
        case "<":
            return int(left) < int(expected)
    return False


#: Default state-update rules, used when the spec does not declare its own.
DEFAULT_STATE_RULES: tuple[StateVariableSpec, ...] = (
    StateVariableSpec(
        name="attempts",
        description="학습자가 스스로 시도한 횟수",
        increment_on=[TriggerEvent.LEARNER_INCORRECT, TriggerEvent.LEARNER_SHOWS_REASONING],
        reset_on=[TriggerEvent.TASK_COMPLETED],
    ),
    StateVariableSpec(
        name="help_requests",
        description="도움을 요청한 횟수",
        increment_on=[TriggerEvent.LEARNER_REQUESTS_HELP],
    ),
    StateVariableSpec(
        name="answer_requests",
        description="정답을 직접 요구한 횟수",
        increment_on=[TriggerEvent.LEARNER_REQUESTS_ANSWER],
    ),
    StateVariableSpec(
        name="stuck_turns",
        description="진전 없이 지나간 연속 턴 수",
        increment_on=[TriggerEvent.LEARNER_STUCK, TriggerEvent.LEARNER_INCORRECT],
        reset_on=[TriggerEvent.LEARNER_CORRECT, TriggerEvent.TASK_COMPLETED],
    ),
    StateVariableSpec(
        name="off_task_count",
        description="수업과 무관한 발화 횟수",
        increment_on=[TriggerEvent.LEARNER_OFF_TASK],
    ),
    StateVariableSpec(
        name="reasoning_shown",
        initial=False,
        description="학습자가 자기 추론을 드러냈는가",
        set_true_on=[TriggerEvent.LEARNER_SHOWS_REASONING],
        set_false_on=[TriggerEvent.TASK_COMPLETED],
    ),
    StateVariableSpec(
        name="misconception_active",
        initial=False,
        description="오개념을 주장하고 있는가",
        set_true_on=[TriggerEvent.LEARNER_MISCONCEPTION],
        set_false_on=[TriggerEvent.LEARNER_CORRECT],
    ),
    StateVariableSpec(
        name="frustration_flag",
        initial=False,
        description="좌절을 표현했는가",
        set_true_on=[TriggerEvent.LEARNER_FRUSTRATED],
        set_false_on=[TriggerEvent.LEARNER_CORRECT],
    ),
    StateVariableSpec(
        name="pii_detected",
        initial=False,
        description="개인정보가 감지되었는가",
        set_true_on=[TriggerEvent.LEARNER_SHARES_PII],
    ),
    StateVariableSpec(
        name="task_completed",
        initial=False,
        description="과제가 해결되었는가",
        set_true_on=[TriggerEvent.TASK_COMPLETED],
    ),
)


def apply_triggers(
    state: LearnerState,
    triggers: list[TriggerEvent],
    rules: list[StateVariableSpec] | None = None,
) -> LearnerState:
    """Update ``state`` in place from the triggers detected this turn."""
    specs = list(rules or DEFAULT_STATE_RULES)
    fired = set(triggers)
    for spec in specs:
        if fired & set(spec.reset_on):
            state.reset(spec.name)
            continue
        if fired & set(spec.set_true_on):
            state.set(spec.name, True)
        if fired & set(spec.set_false_on):
            state.set(spec.name, False)
        if fired & set(spec.increment_on):
            state.incr(spec.name)
    state.incr("turn_index")
    return state
