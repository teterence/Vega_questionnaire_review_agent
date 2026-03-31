"""
Deterministic rule engine. Handles every check that doesn't require interpretation.
This layer processes ~60-70% of questionnaires without ever calling an LLM.

Priority logic:
  1. Missing required fields → Return (cheapest to detect, cheapest to fix)
  2. Boolean violations → Return or Escalate depending on field
  3. Numeric violations → Return
  4. Only questionnaires that pass ALL deterministic checks proceed to LLM analysis
"""

from __future__ import annotations

from .schemas import Questionnaire, RuleResult

# Fields the brief explicitly lists as required (non-null, non-empty)
REQUIRED_FIELDS = [
    "investor_name",
    "investor_address",
    "investment_amount",
    "is_accredited_investor",
    "signature_present",
    "tax_id_provided",
]


def _is_empty(value) -> bool:
    """Check if a value is null, empty string, or whitespace-only."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def run_rules(q: Questionnaire) -> RuleResult:
    """Execute all deterministic checks against a questionnaire.

    Returns a RuleResult containing any missing fields and escalation reasons.
    The decision engine downstream will use these to determine the final action.
    """
    missing: list[str] = []
    escalations: list[str] = []

    # --- Required field checks ---
    for field in REQUIRED_FIELDS:
        value = getattr(q, field, None)
        if _is_empty(value):
            missing.append(field)

    # --- Boolean field checks (only if not already flagged as missing) ---

    # Signature must be true (false = missing signature, not ambiguous)
    if "signature_present" not in missing and q.signature_present is False:
        missing.append("signature_present")

    # Tax ID must be true (false = not provided)
    if "tax_id_provided" not in missing and q.tax_id_provided is False:
        missing.append("tax_id_provided")

    # Accreditation: false = escalate (not a "missing field" — it's a policy decision)
    if "is_accredited_investor" not in missing and q.is_accredited_investor is False:
        escalations.append("Investor is not accredited")

    # --- Investment amount: must be positive ---
    if "investment_amount" not in missing and q.investment_amount is not None:
        if q.investment_amount <= 0:
            missing.append("investment_amount")

    return RuleResult(missing_fields=missing, escalation_reasons=escalations)
