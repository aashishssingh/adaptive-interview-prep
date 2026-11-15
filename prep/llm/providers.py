"""LLM providers. Each returns raw JSON text for a request constrained to a JSON schema.

Only prep/llm/ talks to provider SDKs, so the provider can be swapped (CLAUDE.md).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from prep.llm.errors import (
    ANTHROPIC_AUTH_HELP,
    LLMAuthError,
    LLMError,
    LLMRefusalError,
    LLMTruncatedError,
    LLMUnavailableError,
)

MAX_RETRIES = 5  # SDK-level retries with exponential backoff (429, 408/409, 5xx, timeouts)
TIMEOUT_SECONDS = 600.0


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    model: str


class Provider(Protocol):
    name: str

    def complete(
        self, *, system: str, user: str, model: str, max_tokens: int, schema: dict[str, Any]
    ) -> Completion: ...


# --- Anthropic ------------------------------------------------------------------------------

# Models that accept the server-side refusal fallback (beta). Haiku has no server-side fallback.
FALLBACK_MODELS = {
    "claude-sonnet-5-5",
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-fable-5-1",
    "claude-fable-5-2",
}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    """Claude via the official SDK.

    Authentication: if ANTHROPIC_API_KEY is set it is used; otherwise the client is built with
    no api_key so the SDK resolves `ant auth login` (CLI sign-in) credentials itself.
    """

    name = "anthropic"

    def __init__(self, api_key: str | None = None, client: Any | None = None):
        if client is not None:
            self._client = client
            return
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover - dependency is required
            raise LLMUnavailableError("The anthropic package is not installed.") from e
        kwargs: dict[str, Any] = {"max_retries": MAX_RETRIES, "timeout": TIMEOUT_SECONDS}
        if api_key:
            kwargs["api_key"] = api_key
        try:
            self._client = anthropic.Anthropic(**kwargs)
        except anthropic.AnthropicError as e:
            raise LLMAuthError(ANTHROPIC_AUTH_HELP) from e

    def complete(
        self, *, system: str, user: str, model: str, max_tokens: int, schema: dict[str, Any]
    ) -> Completion:
        import anthropic

        request: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": {"format": {"type": "json_schema", "schema": schema}},
        }
        try:
            if model in FALLBACK_MODELS:
                stream_ctx = self._client.beta.messages.stream(
                    betas=[FALLBACK_BETA], fallbacks="default", **request
                )
            else:
                stream_ctx = self._client.messages.stream(**request)
            with stream_ctx as stream:
                message = stream.get_final_message()
        except anthropic.AuthenticationError as e:
            raise LLMAuthError(ANTHROPIC_AUTH_HELP) from e
        except anthropic.PermissionDeniedError as e:
            raise LLMAuthError(f"Anthropic denied the request (permission): {e.message}") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Anthropic API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"Could not reach the Anthropic API: {e}") from e
        except TypeError as e:  # raised when no authentication method could be resolved
            if "auth" in str(e).lower() or "api_key" in str(e).lower():
                raise LLMAuthError(ANTHROPIC_AUTH_HELP) from e
            raise

        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise LLMRefusalError(f"The model declined the request (category: {category}).")
        if message.stop_reason == "max_tokens":
            raise LLMTruncatedError(
                f"Output hit max_tokens={max_tokens} before finishing; raise max_tokens."
            )
        text = "".join(b.text for b in message.content if getattr(b, "type", "") == "text")
        return Completion(
            text=text,
            input_tokens=int(message.usage.input_tokens or 0),
            output_tokens=int(message.usage.output_tokens or 0),
            model=getattr(message, "model", model),
        )


# --- OpenAI ---------------------------------------------------------------------------------


class OpenAIProvider:
    """OpenAI chat completions in JSON mode; the gateway validates the result against the schema."""

    name = "openai"

    def __init__(self, api_key: str | None = None, client: Any | None = None):
        if client is not None:
            self._client = client
            return
        try:
            import openai
        except ImportError as e:  # pragma: no cover
            raise LLMUnavailableError("The openai package is not installed.") from e
        if not (api_key or os.environ.get("OPENAI_API_KEY")):
            raise LLMAuthError("LLM_PROVIDER=openai needs OPENAI_API_KEY in .env.")
        self._client = openai.OpenAI(
            api_key=api_key or None, max_retries=MAX_RETRIES, timeout=TIMEOUT_SECONDS
        )

    def complete(
        self, *, system: str, user: str, model: str, max_tokens: int, schema: dict[str, Any]
    ) -> Completion:
        import openai

        schema_note = "\n\nReturn only a JSON object that matches this JSON schema:\n" + json.dumps(
            schema, separators=(",", ":")
        )
        try:
            resp = self._client.chat.completions.create(
                model=model,
                max_completion_tokens=max_tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system + schema_note},
                    {"role": "user", "content": user},
                ],
            )
        except openai.AuthenticationError as e:
            raise LLMAuthError("OpenAI rejected the credentials; check OPENAI_API_KEY.") from e
        except openai.APIStatusError as e:
            raise LLMError(f"OpenAI API error {e.status_code}") from e
        except openai.APIConnectionError as e:
            raise LLMError(f"Could not reach the OpenAI API: {e}") from e
        choice = resp.choices[0]
        if choice.finish_reason == "length":
            raise LLMTruncatedError(f"Output hit max_tokens={max_tokens}; raise max_tokens.")
        usage = resp.usage
        return Completion(
            text=choice.message.content or "",
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            model=getattr(resp, "model", model),
        )


# --- Fake (tests) ----------------------------------------------------------------------------


@dataclass
class FakeProvider:
    """Returns fixture JSON. ``responses`` is a list consumed in order, or a callable
    (system, user, model, schema) -> str. Records every call; never touches the network."""

    responses: list[str | dict] | Callable[..., str | dict] = field(default_factory=list)
    name: str = "fake"
    calls: list[dict[str, Any]] = field(default_factory=list)

    def complete(
        self, *, system: str, user: str, model: str, max_tokens: int, schema: dict[str, Any]
    ) -> Completion:
        self.calls.append(
            {
                "system": system,
                "user": user,
                "model": model,
                "max_tokens": max_tokens,
                "schema": schema,
            }
        )
        if callable(self.responses):
            out = self.responses(system=system, user=user, model=model, schema=schema)
        else:
            if not self.responses:
                raise AssertionError("FakeProvider ran out of responses")
            out = self.responses.pop(0)
        text = out if isinstance(out, str) else json.dumps(out)
        return Completion(
            text=text,
            input_tokens=len(system + user) // 4,
            output_tokens=len(text) // 4,
            model=model,
        )
