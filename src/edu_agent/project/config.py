"""``edu-agent.yaml`` — project configuration.

Design rule: **the config never contains a secret.** It records the *names* of
environment variables and non-secret settings such as a base URL. That way a
student can commit the whole project folder to GitHub Classroom without leaking the
key their instructor issued them.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import Field

from edu_agent.schemas.common import HarnessModel
from edu_agent.security.sandbox import SandboxPolicy

#: Environment variables the harness reads. Keeping this list to three is a
#: deliberate UX decision (plan v2 §18.3): a non-programmer can be told exactly
#: three lines to paste into ``.env``.
ENV_API_KEY = "EDU_AGENT_API_KEY"
ENV_BASE_URL = "EDU_AGENT_BASE_URL"
ENV_MODEL = "EDU_AGENT_MODEL"
ENV_JUDGE_MODEL = "EDU_AGENT_JUDGE_MODEL"
ENV_STUDENT_MODEL = "EDU_AGENT_STUDENT_MODEL"


class ProviderProfile(HarnessModel):
    """How to reach a model. Secrets come from the environment, never from here."""

    kind: str = Field(default="openai_compatible", description="openai|anthropic|openai_compatible|mock")
    base_url: str = Field(default="", description="비어 있으면 provider 기본값")
    api_key_env: str = ENV_API_KEY
    model: str = Field(default="", description="튜터 모델")
    judge_model: str = Field(default="", description="평가자 모델 (비우면 model 사용, 경고 표시)")
    student_model: str = Field(default="", description="시뮬레이션 학생 모델")
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=1024, ge=64)
    timeout_s: int = Field(default=60, ge=5)
    max_retries: int = Field(default=2, ge=0)
    max_tokens_per_session: int = Field(default=20000, ge=0, description="0 = 제한 없음")

    def resolved(self) -> ProviderProfile:
        """Overlay environment variables (env wins, so an instructor can override)."""
        data = self.model_dump()
        if os.getenv(ENV_BASE_URL):
            data["base_url"] = os.environ[ENV_BASE_URL]
        if os.getenv(ENV_MODEL):
            data["model"] = os.environ[ENV_MODEL]
        if os.getenv(ENV_JUDGE_MODEL):
            data["judge_model"] = os.environ[ENV_JUDGE_MODEL]
        if os.getenv(ENV_STUDENT_MODEL):
            data["student_model"] = os.environ[ENV_STUDENT_MODEL]
        return ProviderProfile(**data)

    def api_key(self) -> str | None:
        return os.getenv(self.api_key_env) or None

    def judge(self) -> str:
        return self.judge_model or self.model

    def student(self) -> str:
        return self.student_model or self.model


class EvalConfig(HarnessModel):
    """Defaults for ``edu-agent test``."""

    seeds: int = Field(default=2, ge=1, le=20, description="시나리오당 반복 횟수 (pass^k)")
    max_turns: int = Field(default=8, ge=2, le=50)
    judge_enabled: bool = True
    order_swap: bool = Field(default=True, description="위치 편향 상쇄를 위해 순서를 바꿔 재판정")
    calibration_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    holdout_scenarios: list[str] = Field(
        default_factory=list,
        description="improve가 사용하지 않는 시나리오 (과적합 방지). 비우면 자동 분할",
    )


class ImproveConfig(HarnessModel):
    """Guard rails for the self-improvement loop (plan v2 §16)."""

    max_rounds: int = Field(default=3, ge=1, le=10)
    min_improvement: float = Field(
        default=0.05, ge=0.0, description="종합 점수(0~5)가 이만큼은 올라야 채택"
    )
    auto_level: str = Field(
        default="off",
        description="off | prompt | params — 사람 승인 없이 자동 적용할 수 있는 편집 계층",
    )
    allow_structure_edits: bool = Field(
        default=False, description="행동 규칙 추가/삭제를 자동으로 허용할지 (기본 False)"
    )
    max_llm_calls: int = Field(default=200, ge=1, description="한 번의 improve 실행 예산")


class ProjectConfig(HarnessModel):
    """Root of ``edu-agent.yaml``."""

    name: str = "my-agent"
    title: str = ""
    language: str = "ko"
    harness_version: str = ""
    provider: ProviderProfile = Field(default_factory=ProviderProfile)
    evaluation: EvalConfig = Field(default_factory=EvalConfig)
    improve: ImproveConfig = Field(default_factory=ImproveConfig)
    sandbox: SandboxPolicy = Field(
        default_factory=SandboxPolicy,
        description="코드 실행 도구를 어떻게 격리할지. backend: disabled 로 완전히 끌 수 있습니다.",
    )

    @classmethod
    def load(cls, path: Path) -> ProjectConfig:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.model_validate(data)

    def save(self, path: Path) -> None:
        path.write_text(
            yaml.safe_dump(
                self.model_dump(mode="json"),
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            ),
            encoding="utf-8",
            newline="\n",
        )
