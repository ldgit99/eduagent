"""Anthropic Messages backend (optional extra).

Kept separate because the Messages API differs from chat-completions in two ways
the harness cares about: the system prompt is a top-level parameter, and there is
no ``response_format``. Structured output is requested by instruction and recovered
by the lenient parser.
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


class AnthropicProvider:
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
    ) -> None:
        try:
            from anthropic import Anthropic
        except ImportError as exc:  # pragma: no cover
            raise ProviderUnavailable(
                "anthropic 패키지가 설치되어 있지 않습니다.",
                hint="uv tool install 'edu-agent-harness[anthropic]'",
            ) from exc
        if not api_key:
            raise ProviderUnavailable(
                "API 키가 없습니다.",
                hint="프로젝트 폴더의 .env 파일에 EDU_AGENT_API_KEY 를 설정하세요.",
            )
        self.name = "anthropic"
        self.model = model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self._client = Anthropic(
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
        system_parts = [m.content for m in messages if m.role == "system"]
        turns = [m.as_dict() for m in messages if m.role != "system"]
        if response_schema:
            system_parts.append(
                "Reply with a single JSON object matching this schema and nothing else:\n"
                + str(response_schema.get("schema", response_schema))
            )
        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "messages": turns or [{"role": "user", "content": "(빈 입력)"}],
            "max_tokens": max_tokens or self.max_output_tokens,
            "temperature": self.temperature if temperature is None else temperature,
        }
        if system_parts:
            kwargs["system"] = "\n\n".join(system_parts)
        if stop:
            kwargs["stop_sequences"] = stop
        try:
            resp = self._client.messages.create(**kwargs)
        except Exception as exc:
            raise ProviderError(f"모델 호출에 실패했습니다: {str(exc)[:200]}", retryable=True) from exc

        text = "".join(getattr(b, "text", "") for b in resp.content)
        usage = Usage(
            input_tokens=getattr(resp.usage, "input_tokens", 0) or 0,
            output_tokens=getattr(resp.usage, "output_tokens", 0) or 0,
        )
        return Completion(
            text=text.strip(),
            usage=usage,
            model=getattr(resp, "model", kwargs["model"]),
            finish_reason=getattr(resp, "stop_reason", "") or "",
            raw=resp,
        )

    def ping(self) -> float:
        start = time.perf_counter()
        self.complete([ChatMessage("user", "ping")], max_tokens=5, temperature=0.0)
        return (time.perf_counter() - start) * 1000
