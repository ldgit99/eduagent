"""Shared fixtures.

Everything here runs offline. If a test needs a model it gets
:class:`MockProvider`, so the suite is deterministic and costs nothing — which is
what lets CI gate on it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from edu_agent.project import Project, create_project  # noqa: E402
from edu_agent.providers import MockProvider  # noqa: E402
from edu_agent.schemas.agent import AgentSpec  # noqa: E402
from edu_agent.schemas.educational import EducationalDesign, TaskItem  # noqa: E402
from edu_agent.schemas.principles import DesignPrinciples  # noqa: E402
from edu_agent.schemas.technical import TechnicalSpec  # noqa: E402


@pytest.fixture
def tmp_project(tmp_path: Path) -> Project:
    return create_project(tmp_path / "proj", name="test-agent", title="테스트", language="ko")


@pytest.fixture
def mock_provider() -> MockProvider:
    return MockProvider()


@pytest.fixture
def leaky_provider() -> MockProvider:
    """A tutor that hands over the answer the moment it is asked."""
    return MockProvider(behavior="leaky", answer_text="int sum = 0;")


@pytest.fixture
def sycophant_provider() -> MockProvider:
    return MockProvider(behavior="sycophant")


@pytest.fixture
def example_docs() -> tuple[EducationalDesign, DesignPrinciples, TechnicalSpec]:
    """The three input documents of the shipped example, built in-memory."""
    from make_example import build_educational, build_principles, build_technical

    return build_educational(), build_principles(), build_technical()


@pytest.fixture
def compiled_spec(example_docs) -> AgentSpec:
    from edu_agent.compiler import compile_spec

    educational, principles, technical = example_docs
    result = compile_spec(educational, principles, technical, provider=None)
    assert result.spec is not None, [str(i) for i in result.errors]
    return result.spec


@pytest.fixture
def sample_task() -> TaskItem:
    return TaskItem(
        id="t01",
        title="합 구하기",
        reference_answer="int sum = 0;\nfor (int i = 1; i <= 10; i++) { sum += i; }",
        answer_fragments=["int sum = 0;"],
    )
