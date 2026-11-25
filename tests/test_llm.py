import pytest
from pydantic import BaseModel

from rfp_agent import llm
from rfp_agent.llm import LlmError, _mistral_schema, _provider_schema
from rfp_agent.schemas import Extraction


class FakeResponse(BaseModel):
    answer: str


class FakeProviderError(Exception):
    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


class FakeLLM:
    def __init__(self, response_for_call):
        self.response_for_call = response_for_call
        self.calls = []

    def __call__(self, provider, prompt, schema, model, api_key):
        self.calls.append(provider)
        result = self.response_for_call(provider, len(self.calls))
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def provider_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("MISTRAL_API_KEY", "test-mistral-key")
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "")
    monkeypatch.setattr(llm.time, "sleep", lambda _: None)
    monkeypatch.setattr(llm.random, "random", lambda: 0.0)


def test_provider_schema_removes_unsupported_additional_properties():
    provider_schema = _provider_schema(Extraction)
    assert "additionalProperties" not in str(provider_schema)
    assert provider_schema["type"] == "object"


def test_mistral_schema_keeps_numeric_constraints_and_is_strict():
    mistral_schema = _mistral_schema(Extraction)

    assert mistral_schema["additionalProperties"] is False
    assert "minItems" in str(mistral_schema)


def test_transient_error_retries_then_succeeds(monkeypatch, provider_env):
    monkeypatch.setenv("LLM_PROVIDER_ORDER", "gemini")
    fake_llm = FakeLLM(
        lambda provider, call: (
            FakeProviderError(429) if call == 1 else FakeResponse(answer="ok")
        )
    )
    monkeypatch.setattr(llm, "_call_provider", fake_llm)

    result = llm.generate_json("prompt", FakeResponse)
    metadata = llm.consume_call_metadata()

    assert result.answer == "ok"
    assert fake_llm.calls == ["gemini", "gemini"]
    assert metadata is not None
    assert metadata["retries"] == 1


def test_primary_exhausts_retries_then_second_provider_answers(
    monkeypatch, provider_env
):
    monkeypatch.setenv("LLM_PROVIDER_ORDER", "gemini,mistral")
    fake_llm = FakeLLM(
        lambda provider, call: (
            FakeProviderError(503)
            if provider == "gemini"
            else FakeResponse(answer="fallback")
        )
    )
    monkeypatch.setattr(llm, "_call_provider", fake_llm)

    result = llm.generate_json("prompt", FakeResponse)
    metadata = llm.consume_call_metadata()

    assert result.answer == "fallback"
    assert fake_llm.calls == ["gemini", "gemini", "gemini", "gemini", "mistral"]
    assert metadata is not None
    assert metadata["provider"] == "mistral"
    assert metadata["retries"] == 3


def test_all_providers_fail_with_friendly_error(monkeypatch, provider_env):
    monkeypatch.setenv("LLM_PROVIDER_ORDER", "gemini,mistral")
    monkeypatch.setattr(
        llm, "_call_provider", FakeLLM(lambda provider, call: FakeProviderError(500))
    )

    with pytest.raises(
        LlmError,
        match="All configured AI services failed. Please try again in a few minutes.",
    ):
        llm.generate_json("prompt", FakeResponse)


def test_non_retryable_4xx_is_not_retried(monkeypatch, provider_env):
    monkeypatch.setenv("LLM_PROVIDER_ORDER", "gemini")
    fake_llm = FakeLLM(lambda provider, call: FakeProviderError(400))
    monkeypatch.setattr(llm, "_call_provider", fake_llm)

    with pytest.raises(LlmError):
        llm.generate_json("prompt", FakeResponse)

    assert fake_llm.calls == ["gemini"]
