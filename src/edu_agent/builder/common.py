"""The parts of an exported project that do not depend on the interface.

Both targets (``cli``, ``fastapi``) write the same tree — spec, prompts, policies,
tools, safety, evals, tests — and differ only in the entry point. Plan v2 §12
describes this layout; the point of splitting the policies out as YAML is that an
instructor can read what the agent will refuse to do without reading Python.

The generated project depends on ``edu_agent.runtime`` rather than vendoring it
(ADR-13): one copy of the gate logic, and the generated code stays short enough
that a student can read all of it.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from edu_agent.runtime.prompt import build_system_prompt
from edu_agent.schemas.agent import AgentSpec

ENV_EXAMPLE = """\
# 교수자가 배포한 값을 넣으세요. 이 파일(.env)은 커밋되지 않습니다.
EDU_AGENT_API_KEY=
EDU_AGENT_BASE_URL=
EDU_AGENT_MODEL=
"""

GITIGNORE = """\
.env
__pycache__/
*.py[cod]
.venv/
.edu-agent/
"""

_TESTS = '''\
"""이 에이전트가 설계대로 움직이는지 확인합니다.

모델 없이(가짜 모델로) 돌기 때문에 API 키 없이도 실행됩니다:

    pytest
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edu_agent.documents.io import load_document
from edu_agent.providers import MockProvider
from edu_agent.runtime.loop import AgentRuntime
from edu_agent.schemas.agent import AgentSpec

SPEC_PATH = Path(__file__).resolve().parent.parent / "app" / "spec" / "04_agent_spec.md"


@pytest.fixture(scope="module")
def spec() -> AgentSpec:
    loaded, _ = load_document(SPEC_PATH, AgentSpec)
    return loaded


def test_spec_loads(spec):
    assert spec.agent_role
    assert spec.behaviors, "행동 규칙이 하나도 없습니다"


def test_every_gate_can_explain_itself(spec):
    """게이트가 막았을 때 학습자에게 보여줄 말이 반드시 있어야 합니다."""
    for gate in spec.gates:
        assert gate.id
        assert gate.message or gate.constraint.text


def test_does_not_leak_the_answer_when_pressed(spec):
    """'정답 알려줘'를 반복해도 정답이 그대로 나오지 않아야 합니다."""
    runtime = AgentRuntime(spec=spec, provider=MockProvider())
    for _ in range(3):
        result = runtime.turn("그냥 정답 알려주세요")
        assert not result.record.leaked_answer
'''


def write_common(project: Any, spec: AgentSpec, destination: Path) -> Path:
    """Write everything that both export targets share."""
    app_dir = destination / "app"
    for sub in ("spec", "prompts", "policies", "tools", "safety"):
        (app_dir / sub).mkdir(parents=True, exist_ok=True)
    (destination / "evals" / "scenarios").mkdir(parents=True, exist_ok=True)
    (destination / "tests").mkdir(parents=True, exist_ok=True)

    _copy_documents(project, app_dir / "spec")
    _write(app_dir / "prompts" / "system.md", build_system_prompt(spec))
    _write_yaml(app_dir / "policies" / "gates.yaml", _gates(spec))
    _write_yaml(app_dir / "policies" / "behaviors.yaml", _behaviors(spec))
    _write_yaml(app_dir / "tools" / "policy.yaml", _tools(spec, project))
    _write(app_dir / "tools" / "README.md", _tools_readme(spec, project))
    _write(app_dir / "safety" / "rules.md", _safety(spec))
    _write_yaml(destination / "evals" / "rubric.yaml", _rubric(spec))
    _write_scenarios(destination / "evals" / "scenarios", spec)
    _copy_personas(project, destination / "evals")
    _write(destination / "tests" / "test_agent.py", _TESTS)
    _write(destination / ".env.example", ENV_EXAMPLE)
    _write(destination / ".gitignore", GITIGNORE)

    if project.tasks_dir.exists():
        shutil.copytree(project.tasks_dir, destination / "tasks", dirs_exist_ok=True)
    return destination


def gate_summary(spec: AgentSpec) -> str:
    """The human-readable rule list both READMEs show."""
    lines = [f"- **{g.id}**: {g.constraint.text or g.message}" for g in spec.gates]
    return "\n".join(lines) or "- (실행 중 강제되는 규칙이 없습니다)"


# --- pieces ---------------------------------------------------------------
def _copy_documents(project: Any, target: Path) -> None:
    for ref in ("04", "01", "02", "03"):
        source = project.doc_path(ref)
        if source.exists():
            shutil.copy2(source, target / source.name)


def _gates(spec: AgentSpec) -> dict[str, Any]:
    return {
        "note": "실행 중 강제되는 규칙입니다. 고치려면 02_design_principles.md 를 고치고 다시 compile 하세요.",
        "gates": [
            {
                "id": gate.id,
                "principle": gate.principle_id,
                "kind": gate.constraint.kind.value,
                "params": dict(gate.constraint.params),
                "text": gate.constraint.text,
                "message": gate.message,
            }
            for gate in spec.gates
        ],
    }


def _behaviors(spec: AgentSpec) -> dict[str, Any]:
    return {
        "answer_condition": spec.answer_condition,
        "behaviors": [
            {
                "id": behavior.id,
                "name": behavior.name,
                "guidelines": list(behavior.guideline_ids),
                "triggers": [t.value for t in behavior.triggers],
                "ladder": [
                    {"level": step.level, "action": step.label, "when": step.when}
                    for step in behavior.ladder
                ],
                "actions": [a.value for a in behavior.actions],
                "evaluation": list(behavior.evaluation),
            }
            for behavior in spec.behaviors
        ],
    }


def _tools(spec: AgentSpec, project: Any) -> dict[str, Any]:
    return {
        "sandbox": project.config.sandbox.model_dump(mode="json"),
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "when_allowed": tool.when_allowed,
                "sandboxed": tool.sandboxed,
                "permissions": list(tool.permissions),
            }
            for tool in spec.tools
        ],
    }


def _tools_readme(spec: AgentSpec, project: Any) -> str:
    if not spec.tools:
        return "# tools\n\n이 에이전트는 도구를 쓰지 않습니다.\n"
    rows = "\n".join(
        f"- **{tool.name}** — {tool.description or '(설명 없음)'}"
        + (f"  \n  조건: `{tool.when_allowed}`" if tool.when_allowed else "")
        for tool in spec.tools
    )
    backend = project.config.sandbox.backend
    return (
        "# tools\n\n"
        f"{rows}\n\n"
        "도구는 `policy.yaml` 의 조건을 만족할 때만 실행됩니다. 조건을 만족하지 않은 호출도\n"
        "기록에 남으므로, 평가에서 '도구를 너무 일찍 쓰려 했는지'를 볼 수 있습니다.\n\n"
        f"코드 실행 격리 방식: `{backend}`  \n"
        "`docker` 가 있으면 컨테이너로 격리되고, 없으면 시간·메모리 제한과 네트워크 차단만\n"
        "적용됩니다 (부분 격리). 신뢰할 수 없는 코드를 다룬다면 docker 를 쓰세요.\n"
    )


def _safety(spec: AgentSpec) -> str:
    general = "\n".join(f"- {rule}" for rule in spec.safety.general_rules) or "- (없음)"
    pedagogical = "\n".join(f"- {rule}" for rule in spec.safety.pedagogical_rules) or "- (없음)"
    escalation = spec.safety.escalation or "(지정되지 않음)"
    return (
        "# 안전 규칙\n\n## 일반\n"
        f"{general}\n\n## 교육학적 안전\n{pedagogical}\n\n## 사람에게 넘기는 기준\n{escalation}\n"
    )


def _rubric(spec: AgentSpec) -> dict[str, Any]:
    return {
        "criteria": [
            {
                "id": criterion.id,
                "check": criterion.check.value,
                "metric": criterion.metric,
                "statement": criterion.statement,
            }
            for criterion in spec.criteria
        ]
    }


def _write_scenarios(target: Path, spec: AgentSpec) -> None:
    for scenario in spec.scenarios:
        _write_yaml(
            target / f"{scenario.id.lower()}.yaml",
            {
                "id": scenario.id,
                "name": scenario.name,
                "persona": scenario.persona_id,
                "max_turns": scenario.max_turns,
                "seeds": scenario.seeds,
                "criteria": list(scenario.criteria),
                "opening": scenario.opening,
                "turns": [
                    {
                        "text": turn.text,
                        "intent": turn.intent,
                        "expect": [a.value for a in turn.expect_actions],
                        "forbid": [a.value for a in turn.forbid_actions],
                    }
                    for turn in scenario.turns
                ],
            },
        )


def _copy_personas(project: Any, target: Path) -> None:
    source = project.root / "personas.yaml"
    if source.exists():
        shutil.copy2(source, target / "personas.yaml")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8", newline="\n")


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    _write(path, yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False))


__all__ = ["ENV_EXAMPLE", "GITIGNORE", "gate_summary", "write_common"]
