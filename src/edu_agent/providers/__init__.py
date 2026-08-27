"""Thin LLM provider abstraction (plan v2 §3, ADR-10).

Roughly 200 lines of protocol over the official SDKs, rather than a framework.
Rationale:

* One ``openai`` SDK covers OpenAI, Ollama (``/v1``), Gemini's OpenAI-compatible
  endpoint and any instructor-run gateway — by swapping ``base_url`` alone.
* ``litellm`` imports every provider SDK at import time (seconds of startup); a
  student running ``edu-agent status`` should not pay that.
* ``pydantic-ai`` would own the agent loop, and this harness needs the loop to be
  its own (policy gates run between the model call and the learner).

Everything the harness needs is :class:`Provider.complete`. Structured output uses
the native ``json_schema`` response format where available, with a text-parsing
fallback so local models still work.
"""

from edu_agent.providers.base import (
    ChatMessage,
    Completion,
    Provider,
    ProviderError,
    ProviderUnavailable,
    Usage,
)
from edu_agent.providers.factory import available_providers, get_provider
from edu_agent.providers.mock import MockProvider, ScriptedProvider

__all__ = [
    "ChatMessage",
    "Completion",
    "MockProvider",
    "Provider",
    "ProviderError",
    "ProviderUnavailable",
    "ScriptedProvider",
    "Usage",
    "available_providers",
    "get_provider",
]
