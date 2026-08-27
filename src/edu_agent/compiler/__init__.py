"""Compiling the three input documents into an executable agent specification."""

from edu_agent.compiler.checks import CompileIssue, Severity, run_checks
from edu_agent.compiler.compile import CompileResult, compile_spec
from edu_agent.compiler.recommend import recommend_stack

__all__ = [
    "CompileIssue",
    "CompileResult",
    "Severity",
    "compile_spec",
    "recommend_stack",
    "run_checks",
]
