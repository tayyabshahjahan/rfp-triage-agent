from types import SimpleNamespace

import groq
import pytest
from pydantic import BaseModel

from rfp_agent import llm
from rfp_agent.llm import (
    LlmError,
    _compact_groq_prompt,
    _provider_schema,
    _strict_provider_schema,
)
from rfp_agent.schemas import Extraction, RecallResult


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
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "")
    monkeypatch.setattr(llm, "_GROQ_LAST_COMPLETED", 0.0)
    monkeypatch.setattr(llm.time, "sleep", lambda _: None)
    monkeypatch.setattr(llm.random, "random", lambda: 0.0)


def test_provider_schema_removes_unsupported_additional_properties():
    provider_schema = _provider_schema(Extraction)
    assert "additionalProperties" not in str(provider_schema)
    assert provider_schema["type"] == "object"


def test_groq_schema_keeps_numeric_constraints_and_is_strict():
    groq_schema = _strict_provider_schema(Extraction)

    assert groq_schema["additionalProperties"] is False
    assert set(groq_schema["required"]) == set(groq_schema["properties"])
    assert "minItems" in str(groq_schema)
    assert '"default"' not in str(groq_schema)
    assert '"description"' not in str(groq_schema)
    assert '"verified"' not in str(groq_schema)


def test_groq_uses_json_schema_with_code_validation(monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"answer":"ok"}')
                    )
                ]
            )

    class FakeGroq:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(groq, "Groq", FakeGroq)

    result = llm._call_groq("prompt", FakeResponse, "openai/gpt-oss-120b", "key")

    assert result.answer == "ok"
    assert captured["client"]["max_retries"] == 0
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert captured["reasoning_effort"] == "low"


def test_groq_fills_missing_gate_title():
    payload = {
        "gate_candidates": [
            {"title": "", "requirement": "Attend the mandatory site visit."}
        ]
    }

    normalized = llm._normalize_provider_payload(payload)

    assert normalized["gate_candidates"][0]["title"] == "Attend the mandatory site visit."


def test_groq_maps_unknown_requirement_category_to_other():
    payload = {
        "requirements": [
            {
                "category": "DELIVERABLE",
                "text": "Provide a project plan.",
                "mandatory": "YES",
            }
        ],
        "dates": [],
    }

    normalized = llm._normalize_provider_payload(payload, RecallResult)

    assert normalized["requirements"][0]["category"] == "OTHER"


def test_groq_recall_prompt_uses_page_numbered_cues_without_full_document():
    prompt = (
        'LIKELY_UNCOVERED_OBLIGATION_CUES\n["p2: uptime", "p4: insurance"]\n'
        "BEGIN_UNTRUSTED_DATA\n"
        "[[PAGE 1]]\nintro\n\n[[PAGE 2]]\nuptime\n\n"
        "[[PAGE 3]]\nbackground\n\n[[PAGE 4]]\ninsurance\n"
        "END_UNTRUSTED_DATA"
    )

    compacted = _compact_groq_prompt(prompt, RecallResult)

    assert '"p2: uptime"' in compacted
    assert '"p4: insurance"' in compacted
    assert "[[PAGE" not in compacted


def test_groq_extraction_drops_toc_page_and_repeated_footers_only_for_fallback():
    prompt = (
        "BEGIN_UNTRUSTED_DATA\n"
        "[[PAGE 1]]\nImportant requirement.\nRFP 123 Page 1 of 2\n\n"
        "[[PAGE 2]]\nTABLE OF CONTENTS\n1. Scope\nRFP 123 Page 2 of 2\n"
        "END_UNTRUSTED_DATA"
    )

    compacted = _compact_groq_prompt(prompt, Extraction)

    assert "Important requirement." in compacted
    assert "TABLE OF CONTENTS" not in compacted
    assert "Page 1 of 2" not in compacted


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
    monkeypatch.setenv("LLM_PROVIDER_ORDER", "gemini,groq")
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
    assert fake_llm.calls == ["gemini", "gemini", "gemini", "gemini", "groq"]
    assert metadata is not None
    assert metadata["provider"] == "groq"
    assert metadata["retries"] == 3


def test_all_providers_fail_with_friendly_error(monkeypatch, provider_env):
    monkeypatch.setenv("LLM_PROVIDER_ORDER", "gemini,groq")
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
