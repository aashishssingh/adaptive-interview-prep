"""LLM gateway. All model calls go through here so the provider can be swapped."""

from prep.llm.client import LLMClient, get_llm_client, make_provider
from prep.llm.errors import (
    LLMAuthError,
    LLMError,
    LLMRefusalError,
    LLMResponseError,
    LLMTruncatedError,
    LLMUnavailableError,
)
from prep.llm.providers import AnthropicProvider, Completion, FakeProvider, OpenAIProvider

__all__ = [
    "AnthropicProvider",
    "Completion",
    "FakeProvider",
    "LLMAuthError",
    "LLMClient",
    "LLMError",
    "LLMRefusalError",
    "LLMResponseError",
    "LLMTruncatedError",
    "LLMUnavailableError",
    "OpenAIProvider",
    "get_llm_client",
    "make_provider",
]
