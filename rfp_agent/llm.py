"""Validated structured output with provider retries and automatic failover."""

from __future__ import annotations

import json
import logging
import os
import random
import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from .config import (
    GEMINI_FALLBACK_MODEL,
    GEMINI_MODEL,
    GROQ_MAX_OUTPUT_TOKENS,
    GROQ_MIN_CALL_INTERVAL_SECONDS,
    GROQ_MODEL,
    LLM_MAX_OUTPUT_TOKENS,
    LLM_MAX_RETRIES,
    LLM_PROVIDER_ORDER,
    LLM_TIMEOUT_SECONDS,
)

T = TypeVar("T", bound=BaseModel)
ProviderProgress = Callable[[str], None]
LOGGER = logging.getLogger(__name__)
_CODE_COMPUTED_FIELDS = {
    "verified",
    "match",
    "page_corrected",
    "date_check",
    "days_remaining",
    "timing",
}
_GROQ_NON_STRICT_SCHEMAS = {"Extraction", "RecallResult"}
_UNTRUSTED_BEGIN = "BEGIN_UNTRUSTED_DATA\n"
_UNTRUSTED_END = "\nEND_UNTRUSTED_DATA"

_LAST_CALL_METADATA: ContextVar[dict[str, object] | None] = ContextVar(
    "last_llm_call_metadata", default=None
)
_PROGRESS_CALLBACK: ContextVar[ProviderProgress | None] = ContextVar(
    "llm_progress_callback", default=None
)
_GROQ_RATE_LOCK = threading.Lock()
_GROQ_LAST_COMPLETED = 0.0


class LlmError(RuntimeError):
    """A sanitized model error safe to display in the UI."""


def get_api_key(provider: str = "gemini") -> str | None:
    variables = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY"}
    variable = variables.get(provider)
    if variable is None:
        return None
    key = os.getenv(variable)
    if key:
        return key
    try:
        import streamlit as st

        return st.secrets.get(variable)
    except Exception:
        return None


def configured_provider_order() -> list[str]:
    raw = os.getenv("LLM_PROVIDER_ORDER", LLM_PROVIDER_ORDER)
    providers: list[str] = []
    for item in raw.split(","):
        provider = item.strip().casefold()
        if provider in {"gemini", "groq"} and provider not in providers:
            providers.append(provider)
    return providers


def provider_model(provider: str) -> str:
    if provider == "gemini":
        return os.getenv("GEMINI_MODEL", GEMINI_MODEL)
    if provider == "groq":
        return os.getenv("GROQ_MODEL", GROQ_MODEL)
    raise ValueError(f"Unsupported LLM provider: {provider}")


def configured_model_signature() -> str:
    parts: list[str] = []
    for provider in configured_provider_order():
        models = _provider_models(provider)
        parts.append(f"{provider}:{'|'.join(models)}")
    return ",".join(parts)


def clear_call_metadata() -> None:
    _LAST_CALL_METADATA.set(None)


def consume_call_metadata() -> dict[str, object] | None:
    metadata = _LAST_CALL_METADATA.get()
    _LAST_CALL_METADATA.set(None)
    return dict(metadata) if metadata else None


@contextmanager
def llm_progress(callback: ProviderProgress | None) -> Iterator[None]:
    token = _PROGRESS_CALLBACK.set(callback)
    try:
        yield
    finally:
        _PROGRESS_CALLBACK.reset(token)


def _notify_busy() -> None:
    callback = _PROGRESS_CALLBACK.get()
    if callback:
        callback("The AI service is busy, retrying...")


def _status_code(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    values = (
        getattr(exc, "status_code", None),
        getattr(response, "status_code", None),
        getattr(exc, "code", None),
    )
    for value in values:
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _provider_schema(schema: type[T]) -> dict[str, object]:
    """Remove JSON Schema keywords unsupported by Gemini's response schema API."""

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, child in value.items():
                if key == "additionalProperties":
                    continue
                if key == "properties" and isinstance(child, dict):
                    result[key] = {
                        name: clean(item)
                        for name, item in child.items()
                        if name not in _CODE_COMPUTED_FIELDS
                    }
                    continue
                if key == "required" and isinstance(child, list):
                    result[key] = [
                        item for item in child if item not in _CODE_COMPUTED_FIELDS
                    ]
                    continue
                result[key] = clean(child)
            return result
        if isinstance(value, list):
            return [clean(child) for child in value]
        return value

    return clean(schema.model_json_schema())


def _strict_provider_schema(schema: type[T]) -> dict[str, object]:
    """Make every object strict without dropping numeric schema constraints."""

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            result = {
                key: clean(child)
                for key, child in value.items()
                if key not in {"default", "description", "title"}
            }
            if result.get("type") == "object":
                properties = result.get("properties", {})
                if isinstance(properties, dict):
                    properties = {
                        key: child
                        for key, child in properties.items()
                        if key not in _CODE_COMPUTED_FIELDS
                    }
                    result["properties"] = properties
                result["additionalProperties"] = False
                result["required"] = list(properties)
            return result
        if isinstance(value, list):
            return [clean(child) for child in value]
        return value

    return clean(schema.model_json_schema())


def _normalize_provider_payload(payload: object, schema: type[BaseModel] | None = None) -> object:
    if not isinstance(payload, dict):
        return payload

    def scrub(value: object) -> object:
        if isinstance(value, dict):
            return {
                key: scrub(child)
                for key, child in value.items()
                if key not in _CODE_COMPUTED_FIELDS
            }
        if isinstance(value, list):
            return [scrub(child) for child in value]
        return value

    payload = scrub(payload)
    if not isinstance(payload, dict):
        return payload

    schema_name = schema.__name__ if schema is not None else ""
    if schema_name == "Extraction":
        fact_names = {
            "agency",
            "rfp_number_and_title",
            "scope_summary",
            "contract_type",
            "contract_value_or_budget",
            "term",
            "place_of_performance",
            "submission_method",
            "evaluation_method",
        }
        facts = payload.get("facts")
        if not isinstance(facts, dict):
            facts = {}
            payload["facts"] = facts
        for name in fact_names:
            fact = facts.get(name)
            if not isinstance(fact, dict):
                facts[name] = {"value": "Not stated", "evidence": None}
                continue
            if fact.get("value") != "Not stated" and not fact.get("evidence"):
                fact["value"] = "Not stated"
                fact["evidence"] = None

    if schema_name in {"Extraction", "RecallResult"}:
        valid_requirement_categories = {
            "CERTIFICATION",
            "SET_ASIDE",
            "CLEARANCE",
            "PAST_PERFORMANCE",
            "STAFFING",
            "TECHNICAL_SKILL",
            "SECURITY_COMPLIANCE",
            "INSURANCE_BONDING",
            "REGISTRATION_LICENSE",
            "SUBMISSION_FORMAT",
            "COMMERCIAL",
            "OTHER",
        }
        requirements = payload.get("requirements")
        if isinstance(requirements, list):
            for item in requirements:
                if (
                    isinstance(item, dict)
                    and item.get("category") not in valid_requirement_categories
                ):
                    item["category"] = "OTHER"

        valid_date_kinds = {
            "PROPOSAL_DUE",
            "QUESTIONS_DUE",
            "PRE_PROPOSAL_MEETING",
            "SITE_VISIT",
            "WORK_START",
            "AWARD",
            "ISSUE_DATE",
            "ADDENDUM",
            "OTHER",
        }
        dates = payload.get("dates")
        if isinstance(dates, list):
            normalized_dates: list[object] = []
            for item in dates:
                if not isinstance(item, dict):
                    continue
                try:
                    date.fromisoformat(str(item.get("date")))
                except ValueError:
                    continue
                if item.get("kind") not in valid_date_kinds:
                    item["kind"] = "OTHER"
                normalized_dates.append(item)
            payload["dates"] = normalized_dates

    gates = payload.get("gate_candidates")
    if isinstance(gates, list):
        for gate in gates:
            if isinstance(gate, dict) and not gate.get("title"):
                gate["title"] = gate.get("requirement") or gate.get("action") or "Requirement"
    return payload


def _compact_groq_prompt(prompt: str, schema: type[BaseModel]) -> str:
    if schema.__name__ not in {"Extraction", "RecallResult", "RepairResult"}:
        return prompt
    if _UNTRUSTED_BEGIN not in prompt or _UNTRUSTED_END not in prompt:
        return prompt

    prefix, remainder = prompt.split(_UNTRUSTED_BEGIN, 1)
    document, suffix = remainder.split(_UNTRUSTED_END, 1)
    if schema.__name__ == "Extraction":
        matches = list(re.finditer(r"(?m)^\[\[PAGE (\d+)\]\]\n", document))
        blocks: list[str] = []
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(document)
            block = document[match.start() : end].strip()
            if "\nTABLE OF CONTENTS\n" in f"\n{block}\n":
                continue
            lines = [
                line
                for line in block.splitlines()
                if not (
                    re.search(r"(?i)\bpage\s+\d+\s+of\s+\d+\s*$", line)
                    and ("rfp" in line.casefold() or line.casefold().startswith("page"))
                )
            ]
            blocks.append("\n".join(lines).strip())
        selected = "\n\n".join(blocks)
        return f"{prefix}{_UNTRUSTED_BEGIN}{selected}{_UNTRUSTED_END}{suffix}"
    if schema.__name__ == "RecallResult":
        return f"{prefix}{_UNTRUSTED_BEGIN}{_UNTRUSTED_END}{suffix}"
    else:
        wanted = {int(value) for value in re.findall(r'"page"\s*:\s*(\d+)', prefix)}
    if not wanted:
        return prompt

    matches = list(re.finditer(r"(?m)^\[\[PAGE (\d+)\]\]\n", document))
    blocks: list[str] = []
    budget = max(0, 22_000 - len(prefix) - len(suffix))
    used = 0
    for index, match in enumerate(matches):
        page_number = int(match.group(1))
        if page_number not in wanted:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(document)
        block = document[match.start() : end].strip()
        if used + len(block) > budget:
            continue
        blocks.append(block)
        used += len(block)
    selected = "\n\n".join(blocks)
    return f"{prefix}{_UNTRUSTED_BEGIN}{selected}{_UNTRUSTED_END}{suffix}"


def _provider_models(provider: str) -> list[str]:
    if provider == "gemini":
        models = [provider_model("gemini")]
        fallback = os.getenv("GEMINI_FALLBACK_MODEL", GEMINI_FALLBACK_MODEL or "").strip()
        if fallback and fallback not in models:
            models.append(fallback)
        return models
    return [provider_model(provider)]


def _call_gemini(prompt: str, schema: type[T], model: str, api_key: str) -> T:
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=LLM_TIMEOUT_SECONDS * 1_000),
    )
    config = types.GenerateContentConfig(
        temperature=0,
        max_output_tokens=LLM_MAX_OUTPUT_TOKENS,
        response_mime_type="application/json",
        response_json_schema=_provider_schema(schema),
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
    )
    started = time.perf_counter()
    response = client.models.generate_content(model=model, contents=prompt, config=config)
    usage = getattr(response, "usage_metadata", None)
    LOGGER.info(
        "Gemini call model=%s seconds=%.2f input_tokens=%s output_tokens=%s",
        model,
        time.perf_counter() - started,
        getattr(usage, "prompt_token_count", None),
        getattr(usage, "candidates_token_count", None),
    )
    if isinstance(response.parsed, schema):
        return response.parsed
    return schema.model_validate_json(response.text)


def _call_groq(prompt: str, schema: type[T], model: str, api_key: str) -> T:
    global _GROQ_LAST_COMPLETED

    from groq import Groq

    prompt = _compact_groq_prompt(prompt, schema)
    with _GROQ_RATE_LOCK:
        elapsed = time.monotonic() - _GROQ_LAST_COMPLETED
        interval = max(
            GROQ_MIN_CALL_INTERVAL_SECONDS,
            60.0 if len(prompt) >= 12_000 else GROQ_MIN_CALL_INTERVAL_SECONDS,
        )
        wait_seconds = max(0.0, interval - elapsed)
        if wait_seconds:
            time.sleep(wait_seconds)
        client = Groq(
            api_key=api_key,
            timeout=LLM_TIMEOUT_SECONDS,
            max_retries=0,
        )
        started = time.perf_counter()
        try:
            strict = schema.__name__ not in _GROQ_NON_STRICT_SCHEMAS
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema.__name__,
                        "strict": strict,
                        "schema": _strict_provider_schema(schema),
                    },
                },
                temperature=0,
                max_completion_tokens=GROQ_MAX_OUTPUT_TOKENS,
                reasoning_effort="low",
            )
        finally:
            _GROQ_LAST_COMPLETED = time.monotonic()
        LOGGER.info(
            "Groq call model=%s seconds=%.2f",
            model,
            time.perf_counter() - started,
        )
        message = response.choices[0].message
        if not message.content:
            raise ValueError("Groq returned an empty structured response.")
        payload = json.loads(message.content)
        try:
            return schema.model_validate(_normalize_provider_payload(payload, schema))
        except ValidationError as exc:
            LOGGER.warning(
                "Groq validation failed schema=%s errors=%s",
                schema.__name__,
                exc.errors(include_input=False)[:12],
            )
            raise


def _call_provider(
    provider: str,
    prompt: str,
    schema: type[T],
    model: str,
    api_key: str,
) -> T:
    if provider == "gemini":
        return _call_gemini(prompt, schema, model, api_key)
    if provider == "groq":
        return _call_groq(prompt, schema, model, api_key)
    raise ValueError(f"Unsupported LLM provider: {provider}")


def _is_non_retryable_client_error(status: int | None) -> bool:
    return status is not None and 400 <= status < 500 and status != 429


def _is_transient(status: int | None) -> bool:
    return status == 429 or (status is not None and 500 <= status < 600)


def generate_json(prompt: str, schema: type[T]) -> T:
    """Return validated JSON using configured providers, retries, and failover."""

    clear_call_metadata()
    providers = configured_provider_order()
    failures: list[str] = []
    providers_tried: list[str] = []
    retries_used = 0
    total_attempts = 0

    for provider in providers:
        api_key = get_api_key(provider)
        if not api_key:
            failures.append(f"{provider}: API key is missing")
            continue
        providers_tried.append(provider)

        for model in _provider_models(provider):
            current_prompt = prompt
            validation_repair_used = False
            for attempt in range(LLM_MAX_RETRIES + 1):
                total_attempts += 1
                try:
                    result = _call_provider(provider, current_prompt, schema, model, api_key)
                    if not isinstance(result, schema):
                        result = schema.model_validate(result)
                    _LAST_CALL_METADATA.set(
                        {
                            "provider": provider,
                            "model": model,
                            "retries": retries_used,
                            "attempts": total_attempts,
                            "providers_tried": providers_tried.copy(),
                        }
                    )
                    return result
                except (ValidationError, ValueError) as exc:
                    if not validation_repair_used and attempt < LLM_MAX_RETRIES:
                        validation_repair_used = True
                        retries_used += 1
                        validation_note = str(exc)
                        if len(validation_note) > 400:
                            validation_note = validation_note[:400] + "..."
                        current_prompt = (
                            f"{prompt}\n\nYour previous JSON failed validation: {validation_note}. "
                            "Return corrected JSON only, matching the response schema exactly."
                        )
                        continue
                    failures.append(f"{provider}/{model}: invalid structured output")
                    break
                except Exception as exc:
                    status = _status_code(exc)
                    if _is_non_retryable_client_error(status):
                        failures.append(f"{provider}/{model}: HTTP {status}")
                        break
                    if _is_transient(status) and attempt < LLM_MAX_RETRIES:
                        retries_used += 1
                        _notify_busy()
                        time.sleep((2**attempt) + random.random())
                        continue
                    label = f"HTTP {status}" if status is not None else type(exc).__name__
                    failures.append(f"{provider}/{model}: {label}")
                    break
    LOGGER.warning("All LLM providers failed: %s", "; ".join(failures))
    raise LlmError("All configured AI services failed. Please try again in a few minutes.")
