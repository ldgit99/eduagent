"""OpenAI-compatible backend.

One class covers OpenAI, Ollama (``http://localhost:11434/v1``), Gemini's
OpenAI-compatible endpoint and any instructor-run gateway. Only ``base_url`` and
the model name change.
"""

from __future__ import annotations

import time
from typing import Any

from edu_agent.providers.base import (
    ChatMessage,
    Completion,
    ProviderError,
    ProviderUnavailable,
    Usage,
)


class OpenAICompatProvider:
    """Chat-completions backend using the official ``openai`` SDK."""

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str = "",
        timeout_s: int = 60,
        max_retries: int = 2,
        temperature: float = 0.3,
        max_output_tokens: int = 1024,
        name: str = "openai",
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise ProviderUnavailable(
                "openai 패키지가 설치되어 있지 않습니다.",
                hint="uv tool install 'edu-agent-harness[openai]' 또는 pip install openai",
            ) from exc

        if not api_key:
            # Ollama and some gateways ignore the key but the SDK requires a string.
            api_key = "not-needed" if base_url else ""
        if not api_key:
            raise ProviderUnavailable(
                "API 키가 없습니다.",
                hint="프로젝트 폴더의 .env 파일에 EDU_AGENT_API_KEY 를 설정하세요.",
            )

        self.name = name
        self.model = model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url or None,
            timeout=timeout_s,
            max_retries=max_retries,
        )

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_schema: dict[str, Any] | None = None,
        stop: list[str] | None = None,
    ) -> Completion:
        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "messages": [m.as_dict() for m in messages],
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self.max_output_tokens,
        }
        if stop:
            kwargs["stop"] = stop
        if response_schema:
            kwargs["response_format"] = {"type": "json_schema", "json_schema": response_schema}

        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            if response_schema and _is_schema_unsupported(exc):
                # Ollama and older gateways reject json_schema; fall back to
                # json_object and let the lenient parser handle the rest.
                kwargs["response_format"] = {"type": "json_object"}
                try:
                    resp = self._client.chat.completions.create(**kwargs)
                except Exception as exc2:
                    raise _translate(exc2) from exc2
            else:
                raise _translate(exc) from exc

        choice = resp.choices[0] if resp.choices else None
        text = (choice.message.content if choice and choice.message else "") or ""
        usage = Usage(
            input_tokens=getattr(resp.usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(resp.usage, "completion_tokens", 0) or 0,
        ) if resp.usage else Usage()
        return Completion(
            text=text.strip(),
            usage=usage,
            model=getattr(resp, "model", kwargs["model"]),
            finish_reason=getattr(choice, "finish_reason", "") or "",
            raw=resp,
        )

    def ping(self) -> float:
        start = time.perf_counter()
        self.complete([ChatMessage("user", "ping")], max_tokens=5, temperature=0.0)
        return (time.perf_counter() - start) * 1000


def _is_schema_unsupported(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(k in text for k in ("json_schema", "response_format", "unsupported", "invalid_type"))


def _translate(exc: Exception) -> ProviderError:
    """Turn SDK errors into messages a non-programmer can act on."""
    text = str(exc)
    low = text.lower()
    if "api key" in low or "401" in low or "unauthorized" in low:
        return ProviderUnavailable(
            "API 키가 올바르지 않습니다.",
            hint=".env 의 EDU_AGENT_API_KEY 를 확인하세요. 교수자에게 새 키를 요청할 수도 있습니다.",
        )
    if "429" in low or "rate limit" in low:
        return ProviderError(
            "요청이 너무 많습니다. 잠시 후 다시 시도하세요.", retryable=True
        )
    if "connection" in low or "timeout" in low or "getaddrinfo" in low:
        return ProviderError(
            "모델 서버에 연결하지 못했습니다.",
            hint="인터넷 연결과 EDU_AGENT_BASE_URL 을 확인하세요. (edu-agent doctor)",
            retryable=True,
        )
    if "model" in low and ("not found" in low or "does not exist" in low or "404" in low):
        return ProviderUnavailable(
            "모델 이름을 찾을 수 없습니다.",
            hint="edu-agent.yaml 의 provider.model 또는 .env 의 EDU_AGENT_MODEL 을 확인하세요.",
        )
    return ProviderError(f"모델 호출에 실패했습니다: {text[:200]}", retryable=True)
