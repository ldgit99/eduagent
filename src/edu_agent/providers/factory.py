"""Choosing a provider from project config + environment."""

from __future__ import annotations

import importlib.util

from edu_agent.project.config import ProviderProfile
from edu_agent.providers.base import Provider, ProviderUnavailable
from edu_agent.providers.mock import MockProvider


def available_providers() -> dict[str, bool]:
    """Which backends can actually be constructed in this environment."""
    return {
        "openai": importlib.util.find_spec("openai") is not None,
        "anthropic": importlib.util.find_spec("anthropic") is not None,
        "mock": True,
    }


def get_provider(
    profile: ProviderProfile,
    *,
    role: str = "tutor",
    mock: bool = False,
    mock_behavior: str = "good",
) -> Provider:
    """Build the provider for a role.

    Roles exist because the tutor, the judge and the simulated student should not
    be the same model (ADR-09): a model grading its own tutoring inherits its own
    blind spots, and a strong model makes an implausibly capable student.
    """
    profile = profile.resolved()
    model = {"tutor": profile.model, "judge": profile.judge(), "student": profile.student()}.get(
        role, profile.model
    )

    if mock or profile.kind == "mock":
        return MockProvider(model=model or "mock", behavior=mock_behavior)

    if not model:
        raise ProviderUnavailable(
            "사용할 모델이 지정되지 않았습니다.",
            hint="edu-agent.yaml 의 provider.model 또는 .env 의 EDU_AGENT_MODEL 을 설정하세요.",
        )

    common = {
        "api_key": profile.api_key(),
        "base_url": profile.base_url,
        "timeout_s": profile.timeout_s,
        "max_retries": profile.max_retries,
        "temperature": profile.temperature,
        "max_output_tokens": profile.max_output_tokens,
    }

    if profile.kind == "anthropic":
        from edu_agent.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(model, **common)

    from edu_agent.providers.openai_compat import OpenAICompatProvider

    return OpenAICompatProvider(model, name=profile.kind, **common)
