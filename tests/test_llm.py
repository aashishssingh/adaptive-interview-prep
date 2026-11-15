"""LLM gateway tests. FakeProvider / stub clients only; nothing here touches the network."""

import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from prep.config import load_settings
from prep.llm import (
    AnthropicProvider,
    FakeProvider,
    LLMClient,
    LLMRefusalError,
    LLMResponseError,
    LLMTruncatedError,
    LLMUnavailableError,
    make_provider,
)
from prep.llm.credentials import detect_anthropic_credential_source
from prep.llm.pricing import estimate_cost


class Pair(BaseModel):
    a: int
    b: str


@pytest.fixture
def client_factory(tmp_path):
    def make(responses):
        fake = FakeProvider(responses=list(responses) if isinstance(responses, list) else responses)
        return LLMClient(
            fake, cache_dir=tmp_path / "cache", usage_log=tmp_path / "usage.jsonl"
        ), fake

    return make


def usage(tmp_path):
    return [json.loads(line) for line in (tmp_path / "usage.jsonl").read_text().splitlines()]


def test_parses_and_validates(client_factory):
    client, fake = client_factory([{"a": 1, "b": "x"}])
    out = client.complete_json("sys", "user", "m", 100, Pair)
    assert out == Pair(a=1, b="x")
    assert fake.calls[0]["schema"]["properties"].keys() == {"a", "b"}


def test_accepts_fenced_json(client_factory):
    client, _ = client_factory(['```json\n{"a": 2, "b": "y"}\n```'])
    assert client.complete_json("s", "u", "m", 100, Pair).a == 2


def test_one_repair_retry_then_success(client_factory, tmp_path):
    client, fake = client_factory(["not json", {"a": 3, "b": "z"}])
    assert client.complete_json("s", "u", "m", 100, Pair).a == 3
    assert len(fake.calls) == 2
    assert "could not be used" in fake.calls[1]["user"] and "not json" in fake.calls[1]["user"]
    assert [r["purpose"] for r in usage(tmp_path)] == ["", ":repair"]


def test_schema_failure_triggers_repair_then_raises(client_factory):
    client, fake = client_factory([{"a": "nope", "b": "x"}, {"a": "still nope"}])
    with pytest.raises(LLMResponseError):
        client.complete_json("s", "u", "m", 100, Pair)
    assert len(fake.calls) == 2  # exactly one repair


def test_cache_makes_identical_rerun_free(client_factory, tmp_path):
    client, fake = client_factory([{"a": 1, "b": "x"}])
    system, user = "You are a careful assistant.", "Return a pair with a=1 and b=x please."
    client.complete_json(system, user, "m", 100, Pair)
    again = client.complete_json(system, user, "m", 100, Pair)
    assert again.a == 1 and len(fake.calls) == 1
    log = usage(tmp_path)
    assert [r["cached"] for r in log] == [False, True]
    assert log[0]["input_tokens"] > 0 and log[1]["output_tokens"] == log[0]["output_tokens"]
    assert {"timestamp", "model", "input_tokens", "output_tokens", "cached"} <= set(log[0])


def test_cache_key_depends_on_inputs(client_factory):
    client, fake = client_factory([{"a": 1, "b": "x"}] * 4)
    client.complete_json("s", "u", "m", 100, Pair)
    client.complete_json("s", "u", "other-model", 100, Pair)
    client.complete_json("s", "u2", "m", 100, Pair)
    client.complete_json("s2", "u", "m", 100, Pair)
    assert len(fake.calls) == 4


def test_invalid_output_is_not_cached(client_factory, tmp_path):
    client, fake = client_factory(["bad", "bad again"])
    with pytest.raises(LLMResponseError):
        client.complete_json("s", "u", "m", 100, Pair)
    assert not list((tmp_path / "cache").glob("*.json"))


def test_provider_none_raises_clear_error(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "none")
    env = tmp_path / "e.env"
    env.write_text("")
    with pytest.raises(LLMUnavailableError, match="needs an LLM provider"):
        make_provider(load_settings(env))


# --- credentials ----------------------------------------------------------------------------


def test_credential_source_api_key(tmp_path):
    assert detect_anthropic_credential_source({"ANTHROPIC_API_KEY": "k"}, tmp_path) == "api key"


def test_credential_source_cli_sign_in(tmp_path):
    (tmp_path / "credentials").mkdir()
    (tmp_path / "credentials" / "default.json").write_text("{}")
    assert detect_anthropic_credential_source({}, tmp_path) == "CLI sign-in"
    # an empty key is treated as unset, so the CLI profile is used
    assert detect_anthropic_credential_source({"ANTHROPIC_API_KEY": ""}, tmp_path) == "CLI sign-in"
    assert (
        detect_anthropic_credential_source({"ANTHROPIC_PROFILE": "work"}, tmp_path / "empty")
        == "CLI sign-in"
    )
    assert (
        detect_anthropic_credential_source({"ANTHROPIC_AUTH_TOKEN": "t"}, tmp_path / "empty")
        == "CLI sign-in"
    )


def test_credential_source_none_and_config_dir_env(tmp_path):
    assert detect_anthropic_credential_source({}, tmp_path / "nothing") == "none"
    (tmp_path / "cfg" / "credentials").mkdir(parents=True)
    (tmp_path / "cfg" / "credentials" / "p.json").write_text("{}")
    assert (
        detect_anthropic_credential_source({"ANTHROPIC_CONFIG_DIR": str(tmp_path / "cfg")})
        == "CLI sign-in"
    )


def test_settings_report_source_without_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key-123")
    env = tmp_path / "e.env"
    env.write_text("")
    s = load_settings(env)
    assert s.credential_source == "api key"
    assert "sk-test" not in repr(s) and "credential_source='api key'" in repr(s)


def test_anthropic_client_built_without_api_key_when_unset(monkeypatch):
    import anthropic

    captured = {}

    class Recorder:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(anthropic, "Anthropic", Recorder)
    AnthropicProvider(api_key=None)
    assert "api_key" not in captured and captured["max_retries"] >= 3
    AnthropicProvider(api_key="")
    assert "api_key" not in captured
    AnthropicProvider(api_key="sk-test-not-a-real-key-123")
    assert captured["api_key"] == "sk-test-not-a-real-key-123"


# --- Anthropic provider response handling (stub client, no network) --------------------------


class StubStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


def stub_client(message, record):
    def stream(**kwargs):
        record.append(kwargs)
        return StubStream(message)

    return SimpleNamespace(
        messages=SimpleNamespace(stream=stream),
        beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)),
    )


def message(stop_reason="end_turn", text='{"a": 1, "b": "x"}'):
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category="cyber"),
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=text),
        ],
        usage=SimpleNamespace(input_tokens=11, output_tokens=7),
        model="claude-sonnet-5-5",
    )


def test_anthropic_provider_extracts_text_and_usage():
    calls = []
    p = AnthropicProvider(client=stub_client(message(), calls))
    c = p.complete(system="s", user="u", model="claude-haiku-5-5", max_tokens=50, schema={"x": 1})
    assert c.text == '{"a": 1, "b": "x"}' and (c.input_tokens, c.output_tokens) == (11, 7)
    assert calls[0]["output_config"] == {"format": {"type": "json_schema", "schema": {"x": 1}}}
    assert "fallbacks" not in calls[0]  # Haiku: no server-side fallback


def test_anthropic_provider_uses_fallbacks_for_sonnet():
    calls = []
    AnthropicProvider(client=stub_client(message(), calls)).complete(
        system="s", user="u", model="claude-sonnet-5-5", max_tokens=50, schema={}
    )
    assert calls[0]["fallbacks"] == "default" and calls[0]["betas"]


def test_anthropic_provider_refusal_and_truncation():
    with pytest.raises(LLMRefusalError, match="cyber"):
        AnthropicProvider(client=stub_client(message("refusal"), [])).complete(
            system="s", user="u", model="claude-haiku-5-5", max_tokens=5, schema={}
        )
    with pytest.raises(LLMTruncatedError):
        AnthropicProvider(client=stub_client(message("max_tokens"), [])).complete(
            system="s", user="u", model="claude-haiku-5-5", max_tokens=5, schema={}
        )


def test_pricing():
    assert estimate_cost("claude-sonnet-5-5", 1_000_000, 100_000) == pytest.approx(3.0)
    assert estimate_cost("unknown-model", 10, 10) is None
