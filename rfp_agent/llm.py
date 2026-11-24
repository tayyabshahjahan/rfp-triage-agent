"""The only provider-specific module: validated Gemini structured output."""

from __future__ import annotations

import logging
import os
import random
import time
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .config import (
    GEMINI_MODEL,
    LLM_MAX_OUTPUT_TOKENS,
    LLM_MAX_RETRIES,
    LLM_TIMEOUT_SECONDS,
)

T = TypeVar("T", bound=BaseModel)
LOGGER = logging.getLogger(__name__)


class LlmError(RuntimeError):
    """A sanitized model error safe to display in the UI."""


def get_api_key() -> str | None:
    key = os.getenv("GEMINI_API_KEY")
    if key:
        return key
    try:
        import streamlit as st

        return st.secrets.get("GEMINI_API_KEY")
    except Exception:
        return None


def _status_code(exc: Exception) -> int | None:
    return getattr(exc, "status_code", None) or getattr(exc, "code", None)


def _provider_schema(schema: type[T]) -> dict[str, object]:
    """Remove JSON Schema keywords unsupported by Gemini's response schema API."""

    def clean(value):
        if isinstance(value, dict):
            return {
                key: clean(child)
                for key, child in value.items()
                if key != "additionalProperties"
            }
        if isinstance(value, list):
            return [clean(child) for child in value]
        return value

    return clean(schema.model_json_schema())


def generate_json(prompt: str, schema: type[T]) -> T:
    """Call Gemini, retry transient failures, and return a validated Pydantic object."""

    api_key = get_api_key()
    if not api_key:
        raise LlmError("GEMINI_API_KEY is missing. Add it to the environment or Streamlit secrets.")

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
        thinking_config=types.ThinkingConfig(
            thinking_level=types.ThinkingLevel.MINIMAL
        ),
    )

    validation_repair_used = False
    current_prompt = prompt
    for attempt in range(LLM_MAX_RETRIES):
        started = time.perf_counter()
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=current_prompt,
                config=config,
            )
            usage = getattr(response, "usage_metadata", None)
            LOGGER.info(
                "Gemini call model=%s seconds=%.2f input_tokens=%s output_tokens=%s",
                GEMINI_MODEL,
                time.perf_counter() - started,
                getattr(usage, "prompt_token_count", None),
                getattr(usage, "candidates_token_count", None),
            )
            try:
                if isinstance(response.parsed, schema):
                    return response.parsed
                return schema.model_validate_json(response.text)
            except (ValidationError, ValueError) as exc:
                if validation_repair_used:
                    raise LlmError("Gemini returned invalid structured output twice.") from exc
                validation_repair_used = True
                current_prompt = (
                    f"{prompt}\n\nYour previous JSON failed validation: {exc}. "
                    "Return corrected JSON only, matching the response schema exactly."
                )
                continue
        except LlmError:
            raise
        except Exception as exc:
            status = _status_code(exc)
            transient = status == 429 or (isinstance(status, int) and status >= 500)
            if transient and attempt < LLM_MAX_RETRIES - 1:
                time.sleep((2**attempt) + random.random())
                continue
            if status == 429:
                raise LlmError(
                    "Gemini free-tier rate limit reached. Wait briefly or use a cached result."
                ) from exc
            if status in {500, 502, 503, 504}:
                raise LlmError(
                    "Gemini is temporarily unavailable or overloaded. "
                    "Wait a few minutes and try again."
                ) from exc
            raise LlmError("Gemini could not complete the analysis. Please try again.") from exc
    raise LlmError("Gemini could not produce valid structured output.")
