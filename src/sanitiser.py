"""
Input sanitisation for free-text fields before LLM analysis.

PE subscription questionnaires contain user-supplied text (source of funds,
accreditation details) that flows directly into LLM prompts. Without sanitisation,
an adversarial or accidental instruction in the text could manipulate the LLM's
classification. This module strips obvious injection patterns.
"""

from __future__ import annotations

import re

# Patterns that look like prompt manipulation
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(above|prior|previous)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+a", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"<\s*/?\s*(?:system|instruction|prompt)", re.IGNORECASE),
    re.compile(r"\[INST\]", re.IGNORECASE),
]


def sanitise_text(text: str | None) -> str | None:
    """Clean user-supplied text for safe LLM consumption.

    If injection patterns are detected, the text is flagged but NOT silently
    cleaned — the presence of injection-like content is itself a red flag
    that should trigger escalation.

    Returns the original text if clean, or a sanitised marker if suspicious.
    """
    if text is None:
        return None

    text = text.strip()
    if not text:
        return None

    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            return "[SUSPICIOUS INPUT DETECTED - REQUIRES HUMAN REVIEW]"

    return text


def contains_injection(text: str | None) -> bool:
    """Check if text contains prompt injection patterns."""
    if text is None:
        return False
    return any(p.search(text) for p in _INJECTION_PATTERNS)
