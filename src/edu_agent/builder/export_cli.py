"""Exporting a runnable Python CLI project.

The generated project *depends on* ``edu_agent.runtime`` rather than vendoring a
copy of it (ADR-13). Two reasons: the generated code stays short enough that a
student can read it, and the policy-gate logic exists in one place — a vendored
copy would drift the moment the harness fixed a bug.
"""

from __future__ import annotations

from pathlib import Path

from edu_agent.builder.common import HARNESS_REQUIREMENT, gate_summary, write_common
from edu_agent.schemas.agent import AgentSpec

_AGENT_PY = '''\
"""{name} — {role}

이 파일은 edu-agent-harness 가 만들었습니다.
행동 규칙과 정책 게이트는 spec/04_agent_spec.md 에 있습니다.
설계를 바꾸려면 이 파일이 아니라 그 문서를 고치세요.
"""

from __future__ import annotations

import os
from pathlib import Path

from edu_agent.documents.io import load_document
from edu_agent.project.config import ProviderProfile
from edu_agent.providers import get_provider
from edu_agent.runtime.loop import AgentRuntime
from edu_agent.runtime.tools import ToolRuntime
from edu_agent.schemas.agent import AgentSpec

HERE = Path(__file__).parent
SPEC_PATH = HERE / "spec" / "04_agent_spec.md"


def load_spec() -> AgentSpec:
    spec, _ = load_document(SPEC_PATH, AgentSpec)
    return spec


def build_runtime(spec: AgentSpec) -> AgentRuntime:
    profile = ProviderProfile(
        kind=os.getenv("EDU_AGENT_KIND", "openai_compatible"),
        base_url=os.getenv("EDU_AGENT_BASE_URL", ""),
        model=os.getenv("EDU_AGENT_MODEL", ""),
    )
    tools = ToolRuntime(spec.tools) if spec.tools else None
    return AgentRuntime(spec=spec, provider=get_provider(profile), tools=tools)


def main() -> None:
    spec = load_spec()
    runtime = build_runtime(spec)

    print(f"{{spec.agent_role}}")
    print("종료하려면 /quit\\n")

    while True:
        try:
            message = input("나  > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not message or message in {{"/quit", "/q"}}:
            break
        result = runtime.turn(message)
        for call in result.tool_calls:
            state = "차단" if not call.allowed else ("실행" if call.ok else "실패")
            print(f"  [도구 {{state}} · {{call.name}}]")
        print(f"\\n튜터  {{result.message}}\\n")


if __name__ == "__main__":
    main()
'''

_README = """\
# {name}

edu-agent-harness 로 만든 교육용 AI 에이전트입니다.

## 실행 방법

1. 필요한 것 설치
   ```
   pip install -e .
   ```

2. `.env.example` 을 `.env` 로 복사하고 값을 채우기
   ```
   EDU_AGENT_API_KEY=...
   EDU_AGENT_MODEL=...
   ```

3. 실행
   ```
   python app/agent.py
   ```

4. 설계대로 움직이는지 확인 (모델 없이 돕니다)
   ```
   pytest
   ```

## 이 에이전트가 지키는 규칙

{gates}

## 폴더 구조

| 위치 | 무엇이 있나 |
|---|---|
| `app/agent.py` | 실행 진입점 |
| `app/spec/` | 설계 문서 4개 (이것이 정본입니다) |
| `app/prompts/system.md` | 실제로 모델에 들어가는 시스템 프롬프트 |
| `app/policies/` | 실행 중 강제되는 게이트와 행동 규칙 (YAML) |
| `app/tools/` | 도구 사용 조건과 격리 방식 |
| `app/safety/` | 안전 규칙 |
| `evals/` | 시나리오·페르소나·루브릭 |
| `tests/` | 규칙이 지켜지는지 확인하는 테스트 |

## 설계를 바꾸려면

`app/spec/` 의 문서를 고치거나, 원래 프로젝트에서 `edu-agent compile` 을 다시
실행한 뒤 이 폴더로 다시 내보내세요.

행동 규칙과 정책 게이트는 그 문서에 있습니다. `agent.py` 를 고칠 필요는 없습니다.
"""

_PYPROJECT = """\
[project]
name = "{slug}"
version = "0.1.0"
description = "{role}"
requires-python = ">=3.12"
dependencies = ["{harness}"]

[project.scripts]
{slug} = "app.agent:main"

[project.optional-dependencies]
dev = ["pytest>=8.3"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
"""


def export_cli(project, spec: AgentSpec, destination: Path) -> Path:
    """Write a standalone CLI project to ``destination``."""
    write_common(project, spec, destination)

    slug = project.config.name.replace("-", "_")
    role = spec.agent_role or "교육용 AI 에이전트"

    (destination / "app" / "agent.py").write_text(
        _AGENT_PY.format(name=project.config.name, role=role), encoding="utf-8", newline="\n"
    )
    (destination / "README.md").write_text(
        _README.format(name=project.config.name, gates=gate_summary(spec)),
        encoding="utf-8",
        newline="\n",
    )
    (destination / "pyproject.toml").write_text(
        _PYPROJECT.format(slug=slug, role=role, harness=HARNESS_REQUIREMENT),
        encoding="utf-8",
        newline="\n",
    )
    return destination
