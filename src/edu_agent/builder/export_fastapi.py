"""Exporting a FastAPI service.

Same tree and the same policy files as the CLI export — only the entry point
differs (:mod:`edu_agent.builder.common` writes the rest). The generated service
keeps one :class:`AgentRuntime` per browser session and saves the conversation as
JSONL, so a deployed agent produces the same traces ``edu-agent test --regrade``
already knows how to read.

What this target deliberately does *not* do: authentication, a database, or user
accounts. Plan v2 §21 keeps those out of scope, and an exported class project that
pretends to have them would be worse than one that says it does not.
"""

from __future__ import annotations

from pathlib import Path

from edu_agent.builder.common import HARNESS_REQUIREMENT, gate_summary, write_common
from edu_agent.schemas.agent import AgentSpec

_MAIN_PY = '''\
"""{name} — {role}

edu-agent-harness 가 만든 FastAPI 서비스입니다.
행동 규칙과 정책 게이트는 spec/04_agent_spec.md 에 있습니다.

    uvicorn app.main:app --reload
"""

from __future__ import annotations

import os
import secrets
import threading
from pathlib import Path
from typing import Any

from fastapi import Cookie, FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from edu_agent.documents.io import load_document
from edu_agent.project.config import ProviderProfile
from edu_agent.providers import get_provider
from edu_agent.runtime.loop import AgentRuntime
from edu_agent.runtime.tools import ToolRuntime
from edu_agent.schemas.agent import AgentSpec
from edu_agent.storage.jsonl import RunPaths, new_run_id, save_session
from edu_agent.web.assets import render_page

HERE = Path(__file__).parent
SPEC_PATH = HERE / "spec" / "04_agent_spec.md"
TRACE_DIR = Path(os.getenv("EDU_AGENT_TRACE_DIR", HERE.parent / ".edu-agent" / "runs"))

#: Sessions live in memory. One process, one class — see the module docstring.
_sessions: dict[str, AgentRuntime] = {{}}
_lock = threading.Lock()

app = FastAPI(title="{name}")
SPEC: AgentSpec = load_document(SPEC_PATH, AgentSpec)[0]
RUN_ID = new_run_id("serve")


class TurnRequest(BaseModel):
    message: str


def _build_runtime() -> AgentRuntime:
    profile = ProviderProfile(
        kind=os.getenv("EDU_AGENT_KIND", "openai_compatible"),
        base_url=os.getenv("EDU_AGENT_BASE_URL", ""),
        model=os.getenv("EDU_AGENT_MODEL", ""),
    )
    tools = ToolRuntime(SPEC.tools) if SPEC.tools else None
    runtime = AgentRuntime(spec=SPEC, provider=get_provider(profile), tools=tools)
    runtime.trace.run_id = RUN_ID
    return runtime


def _runtime_for(session_id: str) -> AgentRuntime:
    with _lock:
        if session_id not in _sessions:
            _sessions[session_id] = _build_runtime()
        return _sessions[session_id]


def _persist(session_id: str) -> None:
    runtime = _sessions.get(session_id)
    if runtime is not None and runtime.trace.turns:
        save_session(RunPaths(TRACE_DIR, RUN_ID), runtime.trace)


@app.get("/health")
def health() -> dict[str, Any]:
    return {{"ok": True, "agent": SPEC.agent_role, "gates": len(SPEC.gates)}}


@app.get("/", response_class=HTMLResponse)
def index(response: Response, sid: str | None = Cookie(default=None)) -> str:
    if not sid:
        response.set_cookie("sid", secrets.token_urlsafe(16), httponly=True, samesite="strict")
    return render_page(title="{name}", role=SPEC.agent_role, lang="{lang}")


@app.post("/api/turn")
def turn(payload: TurnRequest, sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="빈 메시지입니다.")
    runtime = _runtime_for(sid or "anonymous")
    result = runtime.turn(message)
    _persist(sid or "anonymous")
    notes = []
    if result.gate_outcome.blocked:
        notes.append("규칙에 걸려 다시 생성했습니다.")
    if result.fallback_used:
        notes.append("안전한 응답으로 대체했습니다.")
    return {{
        "message": result.message,
        "action": result.action.value if result.action else "",
        "tools": [
            ("도구 차단 · " + c.name) if not c.allowed else ("도구 실행 · " + c.name)
            for c in result.tool_calls
        ],
        "notes": notes,
    }}


@app.post("/api/reset")
def reset(sid: str | None = Cookie(default=None)) -> dict[str, Any]:
    key = sid or "anonymous"
    _persist(key)
    with _lock:
        _sessions.pop(key, None)
    return {{"ok": True}}
'''

_README = """\
# {name}

edu-agent-harness 로 만든 교육용 AI 에이전트입니다. FastAPI 로 서비스합니다.

## 실행 방법

1. 필요한 것 설치
   ```
   pip install -e ".[dev]"
   ```

2. `.env.example` 을 `.env` 로 복사하고 값을 채우기

3. 실행
   ```
   uvicorn app.main:app --reload
   ```
   브라우저에서 <http://127.0.0.1:8000> 을 엽니다.

4. 설계대로 움직이는지 확인 (모델 없이 돕니다)
   ```
   pytest
   ```

## API

| 경로 | 하는 일 |
|---|---|
| `GET /` | 채팅 화면 |
| `GET /health` | 살아 있는지, 게이트가 몇 개인지 |
| `POST /api/turn` | `{{"message": "..."}}` → 튜터 응답 |
| `POST /api/reset` | 대화를 새로 시작 |

대화는 쿠키(`sid`)로 구분되고, 기록은 `.edu-agent/runs/` 에 JSONL 로 쌓입니다.
그 기록은 원래 프로젝트에서 `edu-agent test --regrade` 로 다시 채점할 수 있습니다.

## 이 에이전트가 지키는 규칙

{gates}

## 알아두기

- 로그인·권한·데이터베이스는 들어 있지 않습니다. 수업용 단일 프로세스 서비스입니다.
- 여러 사람이 쓰려면 세션 저장소와 인증을 먼저 붙이세요.
- 설계를 바꾸려면 `app/spec/` 의 문서를 고치고 `edu-agent compile` 을 다시 실행하세요.

## 폴더 구조

| 위치 | 무엇이 있나 |
|---|---|
| `app/main.py` | FastAPI 앱 |
| `app/spec/` | 설계 문서 4개 (이것이 정본입니다) |
| `app/prompts/system.md` | 실제로 모델에 들어가는 시스템 프롬프트 |
| `app/policies/` | 실행 중 강제되는 게이트와 행동 규칙 (YAML) |
| `app/tools/` | 도구 사용 조건과 격리 방식 |
| `app/safety/` | 안전 규칙 |
| `evals/` | 시나리오·페르소나·루브릭 |
| `tests/` | 규칙이 지켜지는지 확인하는 테스트 |
"""

_PYPROJECT = """\
[project]
name = "{slug}"
version = "0.1.0"
description = "{role}"
requires-python = ">=3.12"
dependencies = [
  "{harness}",
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
]

[project.optional-dependencies]
dev = ["pytest>=8.3", "httpx>=0.27"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
"""

_DOCKERFILE = """\
FROM python:3.12-slim

WORKDIR /srv
COPY . /srv
RUN pip install --no-cache-dir .

ENV EDU_AGENT_TRACE_DIR=/srv/.edu-agent/runs
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
"""


def export_fastapi(project, spec: AgentSpec, destination: Path) -> Path:
    """Write a standalone FastAPI project to ``destination``."""
    write_common(project, spec, destination)

    slug = project.config.name.replace("-", "_")
    role = spec.agent_role or "교육용 AI 에이전트"

    (destination / "app" / "main.py").write_text(
        _MAIN_PY.format(name=project.config.name, role=role, lang=project.config.language),
        encoding="utf-8",
        newline="\n",
    )
    (destination / "app" / "__init__.py").write_text("", encoding="utf-8", newline="\n")
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
    (destination / "Dockerfile").write_text(_DOCKERFILE, encoding="utf-8", newline="\n")
    return destination
