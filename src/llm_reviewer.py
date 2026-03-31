"""
LLM-based text analyser for free-text fields.

Called ONLY when the rule engine cannot make a deterministic decision —
specifically for source_of_funds_description and accreditation_details
where interpretation is required.

Uses Groq (OpenAI-compatible API) with llama-3.3-70b-versatile.
Temperature 0 for determinism. JSON mode enforced. Retry once on failure,
then default to escalation (conservative fallback).
"""

from __future__ import annotations

import json
import logging
import os

from openai import OpenAI

from .feedback import FeedbackStore
from .prompt_builder import build_system_prompt, build_user_prompt
from .sanitiser import contains_injection
from .schemas import LLMClassificationResult, TextClassification

logger = logging.getLogger(__name__)

_MODEL = "llama-3.3-70b-versatile"
_MAX_RETRIES = 2


def _get_client() -> OpenAI:
    """Initialise Groq client. Fails fast if API key is missing."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY not set. Get a free key at https://console.groq.com"
        )
    return OpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=api_key,
    )


def _parse_llm_response(content: str) -> LLMClassificationResult:
    """Parse and validate the LLM's JSON response.
    Strips markdown fences if present (some models wrap JSON in ```).
    """
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()

    data = json.loads(cleaned)
    return LLMClassificationResult(**data)


def analyse_text(
    source_of_funds: str | None,
    accreditation_details: str | None,
    feedback_store: FeedbackStore | None = None,
) -> LLMClassificationResult:
    """Classify free-text fields using the LLM.

    Returns conservative defaults (ambiguous/red_flag) on any failure.
    The agent should never approve based on a failed LLM call.
    """
    # Short-circuit: if either field contains injection attempts, red-flag immediately
    if contains_injection(source_of_funds) or contains_injection(accreditation_details):
        logger.warning("Prompt injection detected — escalating immediately")
        return LLMClassificationResult(
            source_of_funds=TextClassification.RED_FLAG,
            source_of_funds_reason="Suspicious input detected in text field",
            accreditation_details=TextClassification.RED_FLAG,
            accreditation_details_reason="Suspicious input detected in text field",
        )

    # Short-circuit: if both fields are None/empty, nothing to classify
    if not source_of_funds and not accreditation_details:
        return LLMClassificationResult()

    client = _get_client()
    system_prompt = build_system_prompt(feedback_store)
    user_prompt = build_user_prompt(source_of_funds, accreditation_details, feedback_store)

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=_MODEL,
                temperature=0,
                max_completion_tokens=800,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty response from LLM")

            result = _parse_llm_response(content)
            logger.info("LLM classification successful on attempt %d", attempt)
            return result

        except Exception as e:
            logger.warning("LLM attempt %d failed: %s", attempt, e)
            if attempt == _MAX_RETRIES:
                logger.error(
                    "All LLM attempts failed — defaulting to conservative escalation"
                )
                return LLMClassificationResult(
                    source_of_funds=TextClassification.AMBIGUOUS,
                    source_of_funds_reason="LLM analysis failed — requires human review",
                    accreditation_details=TextClassification.AMBIGUOUS,
                    accreditation_details_reason="LLM analysis failed — requires human review",
                )

    # Unreachable, but satisfies type checker
    return LLMClassificationResult()
