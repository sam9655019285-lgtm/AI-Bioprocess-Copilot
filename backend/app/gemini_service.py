"""The only module that talks to the Gemini API (google-genai SDK).

- The API key is read from the GEMINI_API_KEY environment variable on the server;
  it is never returned, logged or included in error messages.
- The model defaults to DEFAULT_MODEL and can be changed with GEMINI_MODEL.
- The raw call is a small replaceable function (`Generator`) so tests never reach Gemini.
- Responses must be JSON matching `AIAnalysis`; anything else raises GeminiResponseError
  instead of being passed on or "repaired".
"""

import json
import logging
import os
from collections.abc import Callable
from functools import lru_cache, partial

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

API_KEY_ENV = "GEMINI_API_KEY"
MODEL_ENV = "GEMINI_MODEL"
DEFAULT_MODEL = "gemini-3.8-flash"
TIMEOUT_MS = 90_000
# 503 (model overloaded) was observed intermittently and is retried by the SDK. 429 is not retried:
# on the free tier it is usually the daily per-model request quota, and retries would only use more requests.
RETRY_ATTEMPTS = 3
RETRY_STATUS_CODES = [503]

# (system_instruction, user_prompt) -> raw response text
Generator = Callable[[str, str], str]


class GeminiNotConfigured(Exception):
    pass


class GeminiProviderError(Exception):
    """Carries only the provider's HTTP code and status name (e.g. 429 RESOURCE_EXHAUSTED) - never raw text."""

    def __init__(self, message: str, code: int | None = None, status: str | None = None):
        super().__init__(message)
        self.code, self.status = code, status


class GeminiResponseError(Exception):
    pass


# --- Response schema (sent to Gemini as the required JSON structure, then validated) ---

_TEXT = 4000
EVIDENCE_REFS_HELP = "Application-generated evidence IDs (F-###, P-###) from the context that support this item."


class ObservedPattern(BaseModel):
    title: str = Field(max_length=300)
    observation: str = Field(max_length=_TEXT)
    evidence: str = Field(max_length=_TEXT)
    evidence_refs: list[str] = Field(default_factory=list, max_length=12, description=EVIDENCE_REFS_HELP)


class PossibleInterpretation(BaseModel):
    title: str = Field(max_length=300)
    interpretation: str = Field(max_length=_TEXT)
    supporting_evidence: str = Field(max_length=_TEXT)
    uncertainty: str = Field(max_length=_TEXT)
    evidence_refs: list[str] = Field(default_factory=list, max_length=12, description=EVIDENCE_REFS_HELP)


class AttentionPoint(BaseModel):
    title: str = Field(max_length=300)
    finding_type: str = Field(max_length=100)
    explanation: str = Field(max_length=_TEXT)
    evidence_refs: list[str] = Field(default_factory=list, max_length=12, description=EVIDENCE_REFS_HELP)


class ScaleUpConsideration(BaseModel):
    title: str = Field(max_length=300)
    consideration: str = Field(max_length=_TEXT)
    basis: str = Field(max_length=_TEXT)


class AIAnalysis(BaseModel):
    """All arrays are required but may be empty."""

    overview: str = Field(min_length=1, max_length=_TEXT)
    observed_patterns: list[ObservedPattern] = Field(max_length=20)
    possible_interpretations: list[PossibleInterpretation] = Field(max_length=20)
    attention_points: list[AttentionPoint] = Field(max_length=20)
    scale_up_considerations: list[ScaleUpConsideration] = Field(max_length=20)
    questions_for_investigation: list[str] = Field(max_length=20)


# --- Configuration ------------------------------------------------------------------

def _api_key() -> str:
    return os.environ.get(API_KEY_ENV, "").strip()


def is_configured() -> bool:
    return bool(_api_key())


def model_name() -> str:
    return os.environ.get(MODEL_ENV, "").strip() or DEFAULT_MODEL


def _redact(text: str) -> str:
    key = _api_key()
    return text.replace(key, "[redacted]") if key else text


def _drop_keyword(node, keyword: str):
    if isinstance(node, dict):
        return {k: _drop_keyword(v, keyword) for k, v in node.items() if k != keyword}
    if isinstance(node, list):
        return [_drop_keyword(v, keyword) for v in node]
    return node


@lru_cache(maxsize=None)
def gemini_schema(response_model: type[BaseModel]) -> dict:
    """JSON schema sent to Gemini for a response model.

    Gemini rejects `maxItems` in response_json_schema with 400 INVALID_ARGUMENT, so it is
    removed here only; the list-length limits are still enforced when the response is
    validated against the Pydantic model. `default` (optional Phase 21 evidence_refs) is
    removed too, keeping the schema to the plain keyword subset.
    """
    return _drop_keyword(_drop_keyword(response_model.model_json_schema(), "maxItems"), "default")


def response_schema() -> dict:
    """Schema sent for the Phase 8 AI process analysis."""
    return gemini_schema(AIAnalysis)


# --- Real Gemini call (the only place the SDK is used) ------------------------------

@lru_cache(maxsize=1)
def _client(api_key: str):
    from google import genai  # imported lazily so the app starts without touching the SDK

    return genai.Client(api_key=api_key)


def gemini_generate(system_instruction: str, prompt: str, response_model: type[BaseModel] = AIAnalysis) -> str:
    key = _api_key()
    if not key:
        raise GeminiNotConfigured("Gemini is not configured.")
    from google.genai import types

    response = _client(key).models.generate_content(
        model=model_name(),
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_json_schema=gemini_schema(response_model),
            temperature=0.2,
            http_options=types.HttpOptions(
                timeout=TIMEOUT_MS,
                retry_options=types.HttpRetryOptions(attempts=RETRY_ATTEMPTS, http_status_codes=RETRY_STATUS_CODES),
            ),
        ),
    )
    return response.text or ""


# --- Public entry points ------------------------------------------------------------

def generate_structured[M: BaseModel](
    system_instruction: str, prompt: str, response_model: type[M], generate: Generator | None = None
) -> M:
    """Call Gemini and return a validated `response_model`, or raise a controlled error.

    `generate` defaults to the real Gemini call for this response model; tests pass a fake.
    """
    if generate is None:
        generate = partial(gemini_generate, response_model=response_model)
    if not is_configured():
        raise GeminiNotConfigured("Gemini is not configured.")
    try:
        text = generate(system_instruction, prompt)
    except GeminiNotConfigured:
        raise
    except Exception as exc:  # SDK/network errors: log type + redacted text, never the key
        code = getattr(exc, "code", None)
        status = getattr(exc, "status", None)
        logger.warning("Gemini request failed: %s: %s", type(exc).__name__, _redact(str(exc))[:500])
        raise GeminiProviderError(
            "The Gemini request failed.",
            code=code if isinstance(code, int) else None,
            status=status if isinstance(status, str) and status.replace("_", "").isalpha() else None,
        ) from None
    try:
        return response_model.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        logger.warning("Gemini returned an invalid %s structure: %s", response_model.__name__, type(exc).__name__)
        raise GeminiResponseError("Gemini returned a response that does not match the expected structure.") from None


def generate_analysis(system_instruction: str, prompt: str, generate: Generator = gemini_generate) -> AIAnalysis:
    """Phase 8: call Gemini and return a validated AIAnalysis, or raise a controlled error."""
    return generate_structured(system_instruction, prompt, AIAnalysis, generate)
