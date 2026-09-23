"""Tools the tutor may use during a turn, and the policy that governs them.

A tool call is a *pedagogical* act, not just a technical one: running the
learner's code for them at the wrong moment removes the debugging work the task
was supposed to teach. So every call passes the same kind of check a response
does — the tool has to be declared in ``04_agent_spec.md`` and its
``when_allowed`` condition has to hold against the current learner state — and
every call is recorded, including the ones that were refused.

Execution itself is delegated to :mod:`edu_agent.security.sandbox`, which decides
*how* to run code safely. This module decides *whether* it may run at all.
"""

from __future__ import annotations

import ast
import math
import operator
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from edu_agent.runtime.state import LearnerState, evaluate_condition
from edu_agent.schemas.agent import ToolPolicy
from edu_agent.schemas.educational import TaskItem
from edu_agent.schemas.trace import ToolInvocation
from edu_agent.security.sandbox import (
    ExecRequest,
    Sandbox,
    SandboxPolicy,
    get_sandbox,
    resolve_language,
)

#: Two is enough to compile-and-rerun once; more usually means the model is
#: looping on the tool instead of talking to the learner.
MAX_CALLS_PER_TURN = 2

CODE_EXECUTION = "code_execution"
CALCULATOR = "calculator"


@dataclass(slots=True)
class ToolCall:
    """What the model asked for."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


class ToolRuntime:
    """Runs declared tools under the spec's policy."""

    def __init__(
        self,
        policies: list[ToolPolicy] | None = None,
        *,
        sandbox: Sandbox | None = None,
        sandbox_policy: SandboxPolicy | None = None,
        task: TaskItem | None = None,
    ) -> None:
        self.policies = {p.name: p for p in (policies or [])}
        self.task = task
        self._sandbox = sandbox
        self._sandbox_policy = sandbox_policy or SandboxPolicy()
        self.calls: list[ToolInvocation] = []

    # --- introspection ----------------------------------------------------
    @property
    def enabled(self) -> bool:
        return any(name in _IMPLEMENTATIONS for name in self.policies)

    @property
    def sandbox(self) -> Sandbox:
        if self._sandbox is None:
            self._sandbox = get_sandbox(self._sandbox_policy)
        return self._sandbox

    def describe(self) -> str:
        """The prompt block that tells the model which tools exist."""
        lines: list[str] = []
        for name, policy in sorted(self.policies.items()):
            if name not in _IMPLEMENTATIONS:
                continue
            spec = _SIGNATURES[name]
            detail = policy.description or spec["summary"]
            line = f"- `{name}`: {detail}\n  입력: {spec['arguments']}"
            if policy.when_allowed:
                line += f"\n  쓸 수 있는 조건: {policy.when_allowed}"
            lines.append(line)
        if not lines:
            return ""
        return (
            "## 쓸 수 있는 도구\n"
            + "\n".join(lines)
            + "\n\n도구를 쓰려면 `tool_call` 에 {\"name\": ..., \"arguments\": {...}} 를 넣으세요. "
            "도구 결과를 받은 뒤 같은 턴에서 학습자에게 할 말을 완성합니다.\n"
            "도구 결과를 그대로 붙여넣지 말고, 학습자가 스스로 원인을 찾도록 활용하세요."
        )

    # --- execution --------------------------------------------------------
    def call(self, request: ToolCall, state: LearnerState) -> ToolInvocation:
        """Check policy, run if allowed, and record either way."""
        started = time.perf_counter()
        policy = self.policies.get(request.name)

        if policy is None or request.name not in _IMPLEMENTATIONS:
            record = ToolInvocation(
                name=request.name,
                arguments=_safe_arguments(request.arguments),
                allowed=False,
                blocked_reason=f"'{request.name}' 도구는 이 에이전트에 선언되어 있지 않습니다.",
            )
            self.calls.append(record)
            return record

        if policy.when_allowed and not evaluate_condition(policy.when_allowed, state):
            record = ToolInvocation(
                name=request.name,
                arguments=_safe_arguments(request.arguments),
                allowed=False,
                blocked_reason=f"아직 조건을 만족하지 않습니다: {policy.when_allowed}",
            )
            self.calls.append(record)
            return record

        record = _IMPLEMENTATIONS[request.name](self, request.arguments)
        record.arguments = _safe_arguments(request.arguments)
        record.duration_ms = record.duration_ms or int((time.perf_counter() - started) * 1000)
        self.calls.append(record)
        return record

    def take_calls(self) -> list[ToolInvocation]:
        """Hand the turn's records to the trace and start fresh."""
        calls, self.calls = self.calls, []
        return calls

    # --- implementations --------------------------------------------------
    def _run_code(self, arguments: dict[str, Any]) -> ToolInvocation:
        code = str(arguments.get("code") or "").strip()
        language = str(arguments.get("language") or "").strip() or _guess_language(self.task)
        if not code:
            return ToolInvocation(
                name=CODE_EXECUTION, ok=False, error="실행할 코드가 비어 있습니다."
            )
        if resolve_language(language) is None:
            return ToolInvocation(
                name=CODE_EXECUTION, ok=False, error=f"'{language}' 언어는 지원하지 않습니다."
            )

        result = self.sandbox.run(
            ExecRequest(language=language, code=code, stdin=str(arguments.get("stdin") or ""))
        )
        return ToolInvocation(
            name=CODE_EXECUTION,
            ok=result.ok,
            output=result.summary(),
            error=result.error,
            backend=result.backend,
            isolation=result.isolation,
            duration_ms=result.duration_ms,
        )

    def _calculate(self, arguments: dict[str, Any]) -> ToolInvocation:
        expression = str(arguments.get("expression") or "").strip()
        try:
            value = safe_eval(expression)
        except ValueError as exc:
            return ToolInvocation(name=CALCULATOR, ok=False, error=str(exc), isolation="none")
        return ToolInvocation(
            name=CALCULATOR, ok=True, output=f"{expression} = {value}", isolation="none"
        )


_IMPLEMENTATIONS: dict[str, Callable[[ToolRuntime, dict[str, Any]], ToolInvocation]] = {
    CODE_EXECUTION: ToolRuntime._run_code,
    CALCULATOR: ToolRuntime._calculate,
}

_SIGNATURES: dict[str, dict[str, str]] = {
    CODE_EXECUTION: {
        "summary": "학습자의 코드를 격리된 환경에서 실행하고 출력을 돌려줍니다.",
        "arguments": '{"language": "python|c", "code": "...", "stdin": "(선택)"}',
    },
    CALCULATOR: {
        "summary": "수식을 계산합니다.",
        "arguments": '{"expression": "2 * (3 + 4)"}',
    },
}


# --- a calculator that cannot execute code --------------------------------
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCTIONS = {
    "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
    "sqrt": math.sqrt, "log": math.log, "log2": math.log2, "log10": math.log10,
    "exp": math.exp, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "floor": math.floor, "ceil": math.ceil, "pi": math.pi, "e": math.e,
}
#: ``2 ** 10_000_000`` is a denial of service in one token, so the exponent is capped.
_MAX_EXPONENT = 1000


def safe_eval(expression: str) -> float | int:
    """Evaluate arithmetic without ``eval``.

    The grammar is walked node by node — same approach as the condition language
    in :mod:`edu_agent.runtime.state`, for the same reason: the string arrives
    from a model, so it never gets to reach the interpreter.
    """
    if not expression:
        raise ValueError("계산할 수식이 없습니다.")
    if len(expression) > 500:
        raise ValueError("수식이 너무 깁니다.")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"수식을 읽을 수 없습니다: {exc.msg}") from None
    return _eval_node(tree.body)


def _eval_node(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, int | float):
            raise ValueError("숫자만 계산할 수 있습니다.")
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_EXPONENT:
            raise ValueError("지수가 너무 큽니다.")
        try:
            return _BIN_OPS[type(node.op)](left, right)
        except ZeroDivisionError:
            raise ValueError("0으로 나눌 수 없습니다.") from None
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.Name) and node.id in _FUNCTIONS:
        value = _FUNCTIONS[node.id]
        if callable(value):
            raise ValueError(f"'{node.id}' 는 함수입니다. 괄호와 함께 쓰세요.")
        return value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        function = _FUNCTIONS.get(node.func.id)
        if not callable(function):
            raise ValueError(f"'{node.func.id}' 함수는 쓸 수 없습니다.")
        if node.keywords:
            raise ValueError("이름 붙은 인자는 쓸 수 없습니다.")
        return function(*[_eval_node(a) for a in node.args])
    if isinstance(node, ast.Tuple | ast.List):
        return [_eval_node(e) for e in node.elts]
    raise ValueError("계산기에서 허용하지 않는 식입니다.")


# --- helpers --------------------------------------------------------------
def _guess_language(task: TaskItem | None) -> str:
    """Fall back to the task's own language instead of refusing the call."""
    if task is None:
        return "python"
    name = (task.prompt_file or "").lower()
    if name.endswith(".c") or name.endswith(".h"):
        return "c"
    return "python"


def _safe_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Keep the trace readable: long code blocks are stored clipped."""
    out: dict[str, Any] = {}
    for key, value in (arguments or {}).items():
        text = value if isinstance(value, int | float | bool) else str(value)
        if isinstance(text, str) and len(text) > 2000:
            text = text[:2000] + " …"
        out[str(key)] = text
    return out


def parse_tool_call(raw: Any) -> ToolCall | None:
    """Read the ``tool_call`` field of a model turn, tolerating loose shapes."""
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or raw.get("tool") or "").strip()
    if not name:
        return None
    arguments = raw.get("arguments") or raw.get("input") or raw.get("args") or {}
    if not isinstance(arguments, dict):
        arguments = {"code": str(arguments)}
    return ToolCall(name=name, arguments=arguments)


__all__ = [
    "CALCULATOR",
    "CODE_EXECUTION",
    "MAX_CALLS_PER_TURN",
    "ToolCall",
    "ToolRuntime",
    "parse_tool_call",
    "safe_eval",
]
