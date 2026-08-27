"""Exporting a runnable Python CLI project.

The generated project *depends on* ``edu_agent.runtime`` rather than vendoring a
copy of it (ADR-13). Two reasons: the generated code stays short enough that a
student can read it, and the policy-gate logic exists in one place — a vendored
copy would drift the moment the harness fixed a bug.
"""

from __future__ import annotations

import shutil
from pathlib import Path

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
from edu_agent.schemas.agent import AgentSpec

SPEC_PATH = Path(__file__).parent / "spec" / "04_agent_spec.md"


def load_spec() -> AgentSpec:
    spec, _ = load_document(SPEC_PATH, AgentSpec)
    return spec


def main() -> None:
    spec = load_spec()
    profile = ProviderProfile(
        kind=os.getenv("EDU_AGENT_KIND", "openai_compatible"),
        base_url=os.getenv("EDU_AGENT_BASE_URL", ""),
        model=os.getenv("EDU_AGENT_MODEL", ""),
    )
    provider = get_provider(profile)
    runtime = AgentRuntime(spec=spec, provider=provider)

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
   pip install edu-agent-harness[openai]
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

## 이 에이전트가 지키는 규칙

{gates}

## 설계를 바꾸려면

`app/spec/04_agent_spec.md` 를 고치거나, 원래 프로젝트에서
`edu-agent compile` 을 다시 실행한 뒤 이 폴더로 다시 내보내세요.

행동 규칙과 정책 게이트는 그 문서에 있습니다. `agent.py` 를 고칠 필요는 없습니다.
"""

_ENV_EXAMPLE = """\
EDU_AGENT_API_KEY=
EDU_AGENT_BASE_URL=
EDU_AGENT_MODEL=
"""

_PYPROJECT = """\
[project]
name = "{slug}"
version = "0.1.0"
description = "{role}"
requires-python = ">=3.12"
dependencies = ["edu-agent-harness[openai]>=0.1.0"]

[project.scripts]
{slug} = "app.agent:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
"""


def export_cli(project, spec: AgentSpec, destination: Path) -> Path:
    """Write a standalone CLI project to ``destination``."""
    app_dir = destination / "app"
    (app_dir / "spec").mkdir(parents=True, exist_ok=True)
    (destination / "evals" / "scenarios").mkdir(parents=True, exist_ok=True)
    (destination / "tests").mkdir(parents=True, exist_ok=True)

    slug = project.config.name.replace("-", "_")
    role = spec.agent_role or "교육용 AI 에이전트"

    (app_dir / "agent.py").write_text(
        _AGENT_PY.format(name=project.config.name, role=role), encoding="utf-8", newline="\n"
    )

    spec_source = project.doc_path("04")
    if spec_source.exists():
        shutil.copy2(spec_source, app_dir / "spec" / "04_agent_spec.md")

    for slot_ref in ("01", "02", "03"):
        source = project.doc_path(slot_ref)
        if source.exists():
            shutil.copy2(source, app_dir / "spec" / source.name)

    gates = "\n".join(
        f"- **{g.id}**: {g.constraint.text or g.message}" for g in spec.gates
    ) or "- (실행 중 강제되는 규칙이 없습니다)"

    (destination / "README.md").write_text(
        _README.format(name=project.config.name, gates=gates), encoding="utf-8", newline="\n"
    )
    (destination / ".env.example").write_text(_ENV_EXAMPLE, encoding="utf-8", newline="\n")
    (destination / ".gitignore").write_text(".env\n__pycache__/\n", encoding="utf-8", newline="\n")
    (destination / "pyproject.toml").write_text(
        _PYPROJECT.format(slug=slug, role=role), encoding="utf-8", newline="\n"
    )

    if project.tasks_dir.exists():
        shutil.copytree(project.tasks_dir, destination / "tasks", dirs_exist_ok=True)

    return destination
