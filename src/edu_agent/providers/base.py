"""Provider protocol and shared types."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ValidationError

M = TypeVar("M", bound=BaseModel)


class ProviderError(Exception):
    """A call failed in a way the user may be able to fix."""

    def __init__(self, message: str, *, hint: str = "", retryable: bool = False) -> None:
        self.hint = hint
        self.retryable = retryable
        super().__init__(message)


class ProviderUnavailable(ProviderError):
    """The provider cannot be used at all (missing package, missing key)."""


@dataclass(slots=True)
class ChatMessage:
    role: str  # system | user | assistant
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
        )

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_dict(self) -> dict[str, int]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


@dataclass(slots=True)
class Completion:
    text: str
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    finish_reason: str = ""
    raw: Any = None

    def parse_json(self) -> Any:
        return _loads_lenient(self.text)

    def parse_model(self, model_cls: type[M]) -> M:
        data = self.parse_json()
        try:
            return model_cls.model_validate(data)
        except ValidationError as exc:
            raise ProviderError(
                "모델이 요청한 형식으로 답하지 않았습니다.",
                hint=str(exc)[:400],
                retryable=True,
            ) from exc


@runtime_checkable
class Provider(Protocol):
    """What the rest of the harness may assume about a model backend."""

    name: str
    model: str

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
        """Single chat completion. ``response_schema`` requests structured JSON."""
        ...

    def ping(self) -> float:
        """Round-trip a trivial request; return latency in ms. Raises on failure."""
        ...


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _loads_lenient(text: str) -> Any:
    """Parse JSON that a model may have wrapped in prose or a code fence.

    Local and smaller models routinely add ``Here is the JSON:`` before the object.
    Failing the whole turn over that would make the harness unusable on Ollama, so
    we recover the first balanced object instead.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = _FENCE.search(text)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            text = fenced.group(1).strip()
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if start < 0:
        raise ProviderError("모델 응답에서 JSON을 찾지 못했습니다.", hint=text[:200], retryable=True)
    opening = text[start]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opening:
            depth += 1
        elif ch == closing:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError as exc:
                    raise ProviderError(
                        "모델 응답의 JSON을 해석하지 못했습니다.",
                        hint=text[:200],
                        retryable=True,
                    ) from exc
    raise ProviderError("모델 응답의 JSON이 닫히지 않았습니다.", hint=text[:200], retryable=True)


def schema_of(model_cls: type[BaseModel], name: str = "") -> dict[str, Any]:
    """Build a strict-ish JSON schema payload for structured output."""
    schema = model_cls.model_json_schema()
    schema.setdefault("additionalProperties", False)
    return {"name": name or model_cls.__name__, "schema": schema, "strict": False}
