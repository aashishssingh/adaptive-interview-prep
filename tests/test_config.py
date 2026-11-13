from pathlib import Path

import pytest

from prep import config

ENV_VARS = [
    "RESUME_CONTENT_PATH",
    "SITE_PATH",
    "LLM_PROVIDER",
    "LLM_MODEL_FAST",
    "LLM_MODEL_DEEP",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
]


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    empty = tmp_path / "empty.env"
    empty.write_text("")
    return empty


def test_defaults(clean_env):
    s = config.load_settings(clean_env)
    assert s.resume_content_path == Path.home() / "Documents/Resumes/source/content.yaml"
    assert s.site_path == Path.home() / "Documents/portfolio-website"
    assert s.llm_provider == "anthropic"
    assert s.llm_model_fast == "claude-haiku-5-5"
    assert s.llm_model_deep == "claude-sonnet-5-5"
    assert s.anthropic_api_key is None
    assert s.openai_api_key is None


def test_env_file_and_tilde_expansion(clean_env, tmp_path):
    env = tmp_path / "test.env"
    env.write_text("SITE_PATH=~/somewhere\nLLM_PROVIDER=none\n")
    s = config.load_settings(env)
    assert s.site_path == Path.home() / "somewhere"
    assert s.llm_provider == "none"


def test_invalid_provider(clean_env, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    with pytest.raises(ValueError):
        config.load_settings(clean_env)


def test_repr_masks_keys(clean_env, monkeypatch):
    fake = "sk-test-not-a-real-key-123"
    monkeypatch.setenv("ANTHROPIC_API_KEY", fake)
    s = config.load_settings(clean_env)
    assert s.anthropic_api_key == fake
    assert fake not in repr(s)
    assert fake not in str(s)
    assert "anthropic_api_key=<set>" in repr(s)
    assert "openai_api_key=<unset>" in repr(s)
