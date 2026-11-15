"""LLMClient: JSON completions validated against pydantic models, with a disk cache, a usage
log, and one repair retry on invalid output."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from prep.config import PROJECT_ROOT, Settings, load_settings
from prep.llm.errors import LLMResponseError, LLMUnavailableError
from prep.llm.providers import AnthropicProvider, Completion, OpenAIProvider, Provider

T = TypeVar("T", bound=BaseModel)

DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "local" / "llm_cache"
DEFAULT_USAGE_LOG = PROJECT_ROOT / "data" / "local" / "llm_usage.jsonl"

REPAIR_INSTRUCTION = (
    "Your previous response could not be used because it was not valid JSON for the required "
    "schema.\nError: {error}\n\nPrevious response (truncated):\n{previous}\n\n"
    "Return the corrected, complete JSON object only."
)


def json_schema_for(model: type[BaseModel]) -> dict[str, Any]:
    """Provider-ready JSON schema. Uses the Anthropic SDK's transform when available (it maps
    pydantic output onto the structured-output subset), else plain pydantic JSON schema."""
    try:
        from anthropic import transform_schema

        return transform_schema(model)
    except ImportError:  # pragma: no cover
        return model.model_json_schema()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


class LLMClient:
    def __init__(
        self,
        provider: Provider,
        cache_dir: Path | None = DEFAULT_CACHE_DIR,
        usage_log: Path | None = DEFAULT_USAGE_LOG,
    ):
        self.provider = provider
        self.cache_dir = cache_dir
        self.usage_log = usage_log

    # --- cache and usage ---------------------------------------------------------------------

    def cache_key(
        self, system: str, user: str, model: str, max_tokens: int, schema: dict[str, Any]
    ) -> str:
        blob = json.dumps(
            {
                "provider": self.provider.name,
                "model": model,
                "system": system,
                "user": user,
                "max_tokens": max_tokens,
                "schema": schema,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> dict[str, Any] | None:
        if self.cache_dir is None:
            return None
        path = self.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def _cache_put(self, key: str, completion: Completion) -> None:
        if self.cache_dir is None:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / f"{key}.json").write_text(
            json.dumps(
                {
                    "text": completion.text,
                    "model": completion.model,
                    "input_tokens": completion.input_tokens,
                    "output_tokens": completion.output_tokens,
                    "created_at": _now(),
                }
            ),
            encoding="utf-8",
        )

    def _log_usage(
        self, model: str, input_tokens: int, output_tokens: int, cached: bool, purpose: str
    ) -> None:
        if self.usage_log is None:
            return
        self.usage_log.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": _now(),
            "provider": self.provider.name,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached": cached,
            "purpose": purpose,
        }
        with self.usage_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    # --- main API ----------------------------------------------------------------------------

    def _call(
        self,
        system: str,
        user: str,
        model: str,
        max_tokens: int,
        schema: dict[str, Any],
        purpose: str,
    ) -> tuple[str, str, Completion | None]:
        """Return (text, cache_key, fresh completion or None if it came from the cache)."""
        key = self.cache_key(system, user, model, max_tokens, schema)
        hit = self._cache_get(key)
        if hit is not None:
            self._log_usage(
                model, hit.get("input_tokens", 0), hit.get("output_tokens", 0), True, purpose
            )
            return hit["text"], key, None
        completion = self.provider.complete(
            system=system, user=user, model=model, max_tokens=max_tokens, schema=schema
        )
        self._log_usage(model, completion.input_tokens, completion.output_tokens, False, purpose)
        return completion.text, key, completion

    @staticmethod
    def _validate(text: str, response_model: type[T]) -> T:
        data = json.loads(_strip_fences(text))
        return response_model.model_validate(data)

    def complete_json(
        self,
        system: str,
        user: str,
        model: str,
        max_tokens: int,
        response_model: type[T],
        purpose: str = "",
    ) -> T:
        """Return the model's JSON output validated as ``response_model``.

        Invalid JSON or a schema failure triggers exactly one repair request; if that also
        fails, LLMResponseError is raised. Only validated outputs are cached.
        """
        schema = json_schema_for(response_model)
        text, key, fresh = self._call(system, user, model, max_tokens, schema, purpose)
        try:
            result = self._validate(text, response_model)
        except (json.JSONDecodeError, ValidationError) as first_error:
            if self.cache_dir is not None:
                (self.cache_dir / f"{key}.json").unlink(missing_ok=True)
            repair_user = (
                user
                + "\n\n"
                + REPAIR_INSTRUCTION.format(error=str(first_error)[:2000], previous=text[:8000])
            )
            text2, key2, fresh2 = self._call(
                system, repair_user, model, max_tokens, schema, purpose + ":repair"
            )
            try:
                result = self._validate(text2, response_model)
            except (json.JSONDecodeError, ValidationError) as second_error:
                if self.cache_dir is not None:
                    (self.cache_dir / f"{key2}.json").unlink(missing_ok=True)
                raise LLMResponseError(
                    f"Model output failed validation after one repair retry: "
                    f"{str(second_error)[:500]}"
                ) from second_error
            if fresh2 is not None:
                self._cache_put(key2, fresh2)
            return result
        if fresh is not None:
            self._cache_put(key, fresh)
        return result


def make_provider(settings: Settings) -> Provider:
    if settings.llm_provider == "none":
        raise LLMUnavailableError(
            "Question generation needs an LLM provider. Set LLM_PROVIDER=anthropic (default) or "
            "openai in .env. Everything else in the app works with LLM_PROVIDER=none."
        )
    if settings.llm_provider == "anthropic":
        return AnthropicProvider(api_key=settings.anthropic_api_key)
    if settings.llm_provider == "openai":
        return OpenAIProvider(api_key=settings.openai_api_key)
    raise LLMUnavailableError(f"Unknown LLM_PROVIDER {settings.llm_provider!r}")


def get_llm_client(settings: Settings | None = None, provider: Provider | None = None) -> LLMClient:
    settings = settings or load_settings()
    return LLMClient(provider or make_provider(settings))
