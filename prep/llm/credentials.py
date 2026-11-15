"""Report where Anthropic credentials would come from, without reading or printing secrets.

Mirrors the Anthropic SDK's resolution order: ANTHROPIC_API_KEY, then ANTHROPIC_AUTH_TOKEN, then
an `ant auth login` profile (ANTHROPIC_PROFILE, or a profile stored under ANTHROPIC_CONFIG_DIR,
default ~/.config/anthropic). Only file *existence* is checked; nothing is opened.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

API_KEY = "api key"
CLI_SIGN_IN = "CLI sign-in"
NONE = "none"


def anthropic_config_dir(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    override = env.get("ANTHROPIC_CONFIG_DIR", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".config" / "anthropic"


def _has_profile_on_disk(config_dir: Path) -> bool:
    creds = config_dir / "credentials"
    return creds.is_dir() and any(creds.glob("*.json"))


def detect_anthropic_credential_source(
    env: Mapping[str, str] | None = None, config_dir: Path | None = None
) -> str:
    """Return "api key", "CLI sign-in" or "none". An empty ANTHROPIC_API_KEY counts as unset."""
    env = os.environ if env is None else env
    if env.get("ANTHROPIC_API_KEY", "").strip():
        return API_KEY
    if env.get("ANTHROPIC_AUTH_TOKEN", "").strip() or env.get("ANTHROPIC_PROFILE", "").strip():
        return CLI_SIGN_IN
    if _has_profile_on_disk(config_dir or anthropic_config_dir(env)):
        return CLI_SIGN_IN
    return NONE
