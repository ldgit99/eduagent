"""Sandboxed execution and the tool policy around it.

The sandbox tests run real subprocesses — they are the only place in the suite
that does — because a sandbox that is only ever mocked is not evidence of
anything. They stay offline and finish in a couple of seconds.
"""

from __future__ import annotations

import json
import os
import shutil
import sys

import pytest

from edu_agent.evaluator.deterministic import run_check
from edu_agent.runtime.loop import AgentRuntime
from edu_agent.runtime.state import LearnerState
from edu_agent.runtime.tools import ToolCall, ToolRuntime, parse_tool_call, safe_eval
from edu_agent.schemas.agent import ToolPolicy
from edu_agent.schemas.evaluation import Label
from edu_agent.schemas.trace import SessionTrace, ToolInvocation, TurnRecord
from edu_agent.security.sandbox import (
    DisabledSandbox,
    ExecRequest,
    SandboxError,
    SandboxPolicy,
    SubprocessSandbox,
    describe_backends,
    get_sandbox,
    resolve_language,
)
from edu_agent.storage.jsonl import RunPaths, load_session, save_session

LOCAL = SandboxPolicy(backend="subprocess", timeout_s=8)


@pytest.fixture
def sandbox() -> SubprocessSandbox:
    return SubprocessSandbox(LOCAL)


# --- the calculator -------------------------------------------------------
class TestSafeEval:
    def test_arithmetic(self):
        assert safe_eval("2 * (3 + 4)") == 14
        assert safe_eval("sqrt(16)") == 4.0
        assert safe_eval("max(1, 7, 3)") == 7

    def test_rejects_code(self):
        for expression in ("__import__('os').system('x')", "open('f')", "[].__class__"):
            with pytest.raises(ValueError):
                safe_eval(expression)

    def test_rejects_denial_of_service(self):
        with pytest.raises(ValueError, match="지수"):
            safe_eval("2 ** 10000000")

    def test_reports_division_by_zero_in_words(self):
        with pytest.raises(ValueError, match="0으로"):
            safe_eval("1/0")


# --- the sandbox ----------------------------------------------------------
class TestSubprocessSandbox:
    def test_runs_python_and_captures_output(self, sandbox):
        result = sandbox.run(ExecRequest(language="python", code="print(sum(range(10)))"))
        assert result.ok
        assert result.stdout.strip() == "45"
        assert result.exit_code == 0
        # The honesty requirement: never claim isolation we do not have.
        assert result.isolation == "partial"

    def test_passes_stdin(self, sandbox):
        result = sandbox.run(
            ExecRequest(language="python", code="print(int(input()) * 2)", stdin="21")
        )
        assert result.stdout.strip() == "42"

    def test_learner_error_is_a_result_not_an_exception(self, sandbox):
        result = sandbox.run(ExecRequest(language="python", code="1/0"))
        assert not result.ok
        assert "ZeroDivisionError" in result.stderr

    def test_blocks_network(self, sandbox):
        result = sandbox.run(
            ExecRequest(language="python", code="import socket; socket.socket()")
        )
        assert not result.ok
        assert "허용되지 않습니다" in result.stderr

    def test_blocks_spawning_processes(self, sandbox):
        result = sandbox.run(
            ExecRequest(language="python", code="import os; os.system('echo hi')")
        )
        assert not result.ok
        assert "허용되지 않습니다" in result.stderr

    def test_kills_an_infinite_loop(self):
        sandbox = SubprocessSandbox(SandboxPolicy(backend="subprocess", timeout_s=2))
        result = sandbox.run(ExecRequest(language="python", code="while True: pass"))
        assert result.timed_out
        assert not result.ok

    def test_clips_runaway_output(self):
        sandbox = SubprocessSandbox(
            SandboxPolicy(backend="subprocess", timeout_s=8, max_output_bytes=500)
        )
        result = sandbox.run(ExecRequest(language="python", code="print('x' * 100000)"))
        assert result.truncated
        assert len(result.stdout) == 500

    def test_does_not_hand_api_keys_to_learner_code(self, sandbox, monkeypatch):
        monkeypatch.setenv("EDU_AGENT_API_KEY", "sk-should-not-be-visible")
        result = sandbox.run(
            ExecRequest(language="python", code="import os; print(os.getenv('EDU_AGENT_API_KEY'))")
        )
        assert result.stdout.strip() == "None"

    def test_refuses_unknown_language(self, sandbox):
        result = sandbox.run(ExecRequest(language="ruby", code="puts 1"))
        assert not result.ok
        assert "ruby" in result.error

    def test_refuses_paths_outside_the_working_directory(self, sandbox):
        with pytest.raises(SandboxError):
            sandbox._prepare(
                ExecRequest(language="python", code="", files={"../escape.txt": "x"}),
                __import__("pathlib").Path(__import__("tempfile").mkdtemp()),
                resolve_language("python"),
            )

    @pytest.mark.skipif(shutil.which("gcc") is None, reason="C 컴파일러가 없는 환경")
    def test_compiles_and_runs_c(self, sandbox):
        code = '#include <stdio.h>\nint main(void){printf("hi");return 0;}'
        result = sandbox.run(ExecRequest(language="c", code=code))
        assert result.ok
        assert result.stdout.strip() == "hi"

    @pytest.mark.skipif(shutil.which("gcc") is None, reason="C 컴파일러가 없는 환경")
    def test_reports_compile_failure_separately(self, sandbox):
        result = sandbox.run(ExecRequest(language="c", code="int main(void){ return }"))
        assert not result.ok
        assert "컴파일" in result.error


class TestNeverRaises:
    """``run`` returning a failed result is the contract; raising is a bug.

    macOS refuses ``RLIMIT_AS``, which made every execution die with
    ``SubprocessError`` from inside ``preexec_fn`` — a whole platform where the
    sandbox threw instead of reporting.
    """

    def test_child_setup_failure_becomes_a_result(self, sandbox, monkeypatch):
        import subprocess

        from edu_agent.security import sandbox as sandbox_module

        def explode(*args, **kwargs):
            raise subprocess.SubprocessError("Exception occurred in preexec_fn.")

        monkeypatch.setattr(sandbox_module.subprocess, "run", explode)
        result = sandbox.run(ExecRequest(language="python", code="print(1)"))

        assert not result.ok
        assert "preexec_fn" in result.stderr

    @pytest.mark.skipif(os.name != "posix", reason="rlimit은 POSIX 전용")
    def test_unsupported_limits_are_skipped_not_fatal(self):
        """A limit the platform rejects weakens the sandbox; it must not kill it."""
        from edu_agent.security.sandbox import _limits

        apply = _limits(SandboxPolicy(backend="subprocess", memory_mb=64))
        # Runs in a forked child in real use; calling it here only has to prove
        # that a rejected setrlimit is swallowed rather than raised.
        code = (
            "import sys; sys.path.insert(0, 'src');"
            "from edu_agent.security.sandbox import _limits;"
            "from edu_agent.security.sandbox import SandboxPolicy;"
            "_limits(SandboxPolicy())(); print('ok')"
        )
        import subprocess

        done = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=30, check=False
        )
        assert apply is not None
        assert done.returncode == 0, done.stderr


class TestCompiledBinary:
    """The compiler names the artefact, not us.

    MinGW turns ``-o program`` into ``program.exe``, so running ``./program``
    failed on Windows with "cannot find the file specified" — a platform where
    C execution never worked. This runs everywhere, with no compiler needed.
    """

    def test_finds_a_windows_style_executable(self, tmp_path):
        from edu_agent.security.sandbox import compiled_binary

        (tmp_path / "program.exe").write_text("", encoding="utf-8")
        found = compiled_binary(tmp_path)
        assert found is not None and found.name == "program.exe"
        assert found.is_absolute()

    def test_finds_a_posix_style_executable(self, tmp_path):
        from edu_agent.security.sandbox import compiled_binary

        (tmp_path / "program").write_text("", encoding="utf-8")
        found = compiled_binary(tmp_path)
        assert found is not None and found.name == "program"

    def test_returns_none_when_nothing_was_produced(self, tmp_path):
        from edu_agent.security.sandbox import compiled_binary

        assert compiled_binary(tmp_path) is None


def test_compilation_gets_its_own_time_budget():
    """Charging a cold compiler to the learner's timeout reports the wrong failure."""
    from edu_agent.security.sandbox import MIN_COMPILE_TIMEOUT_S, compile_timeout

    policy = SandboxPolicy(backend="subprocess", timeout_s=2)
    assert compile_timeout(policy) >= MIN_COMPILE_TIMEOUT_S
    assert compile_timeout(policy) > policy.timeout_s


def test_disabled_sandbox_explains_itself():
    result = DisabledSandbox(SandboxPolicy(backend="disabled")).run(
        ExecRequest(language="python", code="print(1)")
    )
    assert not result.ok
    assert result.error


def test_get_sandbox_honours_an_explicit_backend():
    assert get_sandbox(SandboxPolicy(backend="subprocess")).name == "subprocess"
    assert get_sandbox(SandboxPolicy(backend="disabled")).name == "disabled"


def test_describe_backends_lists_what_is_available():
    rows = describe_backends(LOCAL)
    names = [name for name, _, _ in rows]
    assert "subprocess" in names
    assert any(ok for name, ok, _ in rows if name == "subprocess")


# --- policy ---------------------------------------------------------------
class TestToolPolicy:
    def test_undeclared_tool_is_refused(self):
        runtime = ToolRuntime([], sandbox_policy=LOCAL)
        call = runtime.call(ToolCall("code_execution", {"code": "print(1)"}), LearnerState())
        assert not call.allowed
        assert "선언" in call.blocked_reason

    def test_condition_is_enforced_before_execution(self):
        policy = ToolPolicy(name="code_execution", when_allowed="reasoning_shown == true")
        runtime = ToolRuntime([policy], sandbox_policy=LOCAL)
        state = LearnerState()

        blocked = runtime.call(
            ToolCall("code_execution", {"language": "python", "code": "print(1)"}), state
        )
        assert not blocked.allowed
        assert "reasoning_shown" in blocked.blocked_reason

        state.set("reasoning_shown", True)
        allowed = runtime.call(
            ToolCall("code_execution", {"language": "python", "code": "print(1)"}), state
        )
        assert allowed.allowed
        assert allowed.ok
        assert "1" in allowed.output

    def test_calculator_runs_without_a_sandbox(self):
        runtime = ToolRuntime([ToolPolicy(name="calculator")], sandbox_policy=LOCAL)
        call = runtime.call(ToolCall("calculator", {"expression": "6*7"}), LearnerState())
        assert call.ok
        assert "42" in call.output

    def test_arguments_are_clipped_in_the_trace(self):
        runtime = ToolRuntime([ToolPolicy(name="calculator")], sandbox_policy=LOCAL)
        call = runtime.call(ToolCall("calculator", {"expression": "1+" * 5000}), LearnerState())
        assert len(call.arguments["expression"]) <= 2100

    def test_describe_mentions_the_condition(self):
        runtime = ToolRuntime(
            [ToolPolicy(name="code_execution", when_allowed="attempts >= 2")], sandbox_policy=LOCAL
        )
        block = runtime.describe()
        assert "code_execution" in block
        assert "attempts >= 2" in block


def test_parse_tool_call_tolerates_loose_shapes():
    assert parse_tool_call({"name": "calculator", "arguments": {"expression": "1"}}) is not None
    assert parse_tool_call({"tool": "calculator", "input": {"expression": "1"}}) is not None
    assert parse_tool_call({"name": ""}) is None
    assert parse_tool_call("calculator") is None


# --- the turn loop --------------------------------------------------------
def _turn_json(action: str, message: str, tool: dict | None = None) -> str:
    payload: dict[str, object] = {"action": action, "message": message}
    if tool is not None:
        payload["tool_call"] = tool
    return json.dumps(payload, ensure_ascii=False)


class TestRuntimeToolLoop:
    def test_tool_result_feeds_the_next_generation(self, compiled_spec, sample_task):
        from edu_agent.providers import MockProvider

        provider = MockProvider(
            scripted=[
                _turn_json(
                    "ask_for_reasoning",
                    "",
                    {"name": "calculator", "arguments": {"expression": "6*7"}},
                ),
                _turn_json("ask_for_reasoning", "직접 계산해 보면 어떤 값이 나올까요?"),
            ]
        )
        runtime = AgentRuntime(
            spec=compiled_spec,
            provider=provider,
            task=sample_task,
            tools=ToolRuntime([ToolPolicy(name="calculator")], sandbox_policy=LOCAL),
        )
        result = runtime.turn("6 곱하기 7이 뭐예요?")

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].ok
        assert "어떤 값" in result.message
        # The tool result has to reach the second call, or the loop is pointless.
        assert "42" in "\n".join(m.content for m in provider.calls[-1])

    def test_tool_budget_is_bounded(self, compiled_spec):
        from edu_agent.providers import MockProvider

        asking = _turn_json(
            "ask_for_reasoning", "", {"name": "calculator", "arguments": {"expression": "1+1"}}
        )
        provider = MockProvider(scripted=[asking] * 8)
        runtime = AgentRuntime(
            spec=compiled_spec,
            provider=provider,
            tools=ToolRuntime([ToolPolicy(name="calculator")], sandbox_policy=LOCAL),
        )
        result = runtime.turn("계산해 주세요")

        assert len(result.tool_calls) <= 2
        assert result.message  # a turn always ends with something for the learner

    def test_blocked_tool_is_recorded_on_the_turn(self, compiled_spec):
        from edu_agent.providers import MockProvider

        provider = MockProvider(
            scripted=[
                _turn_json(
                    "ask_for_reasoning",
                    "",
                    {"name": "code_execution", "arguments": {"code": "print(1)"}},
                ),
                _turn_json("ask_for_reasoning", "먼저 어떻게 생각했는지 알려주세요."),
            ]
        )
        runtime = AgentRuntime(
            spec=compiled_spec,
            provider=provider,
            tools=ToolRuntime(
                [ToolPolicy(name="code_execution", when_allowed="reasoning_shown == true")],
                sandbox_policy=LOCAL,
            ),
        )
        result = runtime.turn("이거 실행해 주세요")
        assert result.tool_calls and not result.tool_calls[0].allowed
        assert result.record.tool_calls[0].blocked_reason


def test_tool_calls_survive_the_trace_round_trip(tmp_path):
    trace = SessionTrace(session_id="s_tool")
    trace.turns.append(
        TurnRecord(
            turn_index=0,
            learner_message="실행해 주세요",
            tutor_message="먼저 생각을 들려주세요",
            tool_calls=[
                ToolInvocation(name="code_execution", allowed=False, blocked_reason="조건 미충족")
            ],
        )
    )
    paths = RunPaths(tmp_path, "run1")
    save_session(paths, trace)
    reloaded = load_session(paths.session("s_tool"))

    assert len(reloaded.turns) == 1
    assert reloaded.turns[0].tool_calls[0].blocked_reason == "조건 미충족"


# --- the evaluator check --------------------------------------------------
class TestToolPolicyCheck:
    def _check(self, calls: list[ToolInvocation]):
        trace = SessionTrace(session_id="s1")
        trace.turns.append(TurnRecord(turn_index=0, tool_calls=calls))
        outcome = run_check("tool_policy_compliance", trace)
        assert outcome is not None, "check is not registered"
        return outcome

    def test_no_tools_is_not_applicable(self):
        label, _, rationale = self._check([])
        assert label is Label.PARTIAL
        assert "없습니다" in rationale

    def test_all_allowed_passes(self):
        label, _, _ = self._check([ToolInvocation(name="calculator", allowed=True, ok=True)])
        assert label is Label.YES

    def test_blocked_call_fails_with_evidence(self):
        label, evidence, rationale = self._check(
            [ToolInvocation(name="code_execution", allowed=False, blocked_reason="조건 미충족")]
        )
        assert label is Label.NO
        assert evidence and "조건 미충족" in evidence[0].note
        assert "0%" in rationale
