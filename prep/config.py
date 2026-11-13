"""Runtime configuration loaded from environment variables and an optional .env file.

API key values are never printed: ``Settings.__repr__`` masks them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

LLM_PROVIDERS = ("anthropic", "openai", "none")

DEFAULTS = {
    "RESUME_CONTENT_PATH": "~/Documents/Resumes/source/content.yaml",
    "SITE_PATH": "~/Documents/portfolio-website",
    "LLM_PROVIDER": "anthropic",
    "LLM_MODEL_FAST": "claude-haiku-5-5",
    "LLM_MODEL_DEEP": "claude-sonnet-5-5",
}


def _expand(path: str) -> Path:
    return Path(os.path.expandvars(path)).expanduser()


def _mask(value: str | None) -> str:
    return "<set>" if value else "<unset>"


@dataclass(frozen=True)
class Settings:
    resume_content_path: Path
    site_path: Path
    llm_provider: str
    llm_model_fast: str
    llm_model_deep: str
    anthropic_api_key: str | None = field(default=None, repr=False)
    openai_api_key: str | None = field(default=None, repr=False)

    def __repr__(self) -> str:  # never expose key values
        return (
            f"Settings(resume_content_path={self.resume_content_path!s}, "
            f"site_path={self.site_path!s}, llm_provider={self.llm_provider!r}, "
            f"llm_model_fast={self.llm_model_fast!r}, llm_model_deep={self.llm_model_deep!r}, "
            f"anthropic_api_key={_mask(self.anthropic_api_key)}, "
            f"openai_api_key={_mask(self.openai_api_key)})"
        )

    __str__ = __repr__


def load_settings(env_file: Path | str | None = None) -> Settings:
    """Load settings from the environment, after reading ``env_file`` (default: repo .env).

    Existing environment variables take precedence over values in the .env file.
    """
    load_dotenv(env_file if env_file is not None else PROJECT_ROOT / ".env", override=False)

    def get(name: str) -> str:
        value = os.getenv(name, "").strip()
        return value or DEFAULTS[name]

    provider = get("LLM_PROVIDER").lower()
    if provider not in LLM_PROVIDERS:
        raise ValueError(f"LLM_PROVIDER must be one of {LLM_PROVIDERS}, got {provider!r}")

    return Settings(
        resume_content_path=_expand(get("RESUME_CONTENT_PATH")),
        site_path=_expand(get("SITE_PATH")),
        llm_provider=provider,
        llm_model_fast=get("LLM_MODEL_FAST"),
        llm_model_deep=get("LLM_MODEL_DEEP"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip() or None,
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip() or None,
    )
