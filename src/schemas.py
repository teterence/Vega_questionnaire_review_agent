"""
Strict data models for questionnaire input and agent output.
Pydantic enforces types at parse time — malformed input fails fast with clear errors.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class Decision(str, Enum):
    APPROVE = "Approve"
    RETURN = "Return"
    ESCALATE = "Escalate"


class TextClassification(str, Enum):
    CLEAR = "clear"
    AMBIGUOUS = "ambiguous"
    RED_FLAG = "red_flag"


class Questionnaire(BaseModel):
    """Input model — mirrors Appendix A exactly. Strict validation catches
    malformed records from the hidden test set before they reach the agent."""

    questionnaire_id: str
    investor_name: Optional[str] = None
    investor_type: Optional[str] = None
    investor_address: Optional[str] = None
    investment_amount: Optional[float] = None
    is_accredited_investor: Optional[bool] = None
    accreditation_details: Optional[str] = None
    source_of_funds_description: Optional[str] = None
    tax_id_provided: Optional[bool] = None
    signature_present: Optional[bool] = None
    submission_date: str = ""

    @field_validator("investment_amount", mode="before")
    @classmethod
    def coerce_investment_amount(cls, v):
        """Handle edge cases: string amounts, negative, zero."""
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None


class AgentOutput(BaseModel):
    """Output model — matches the exact JSON schema from the brief."""

    questionnaire_id: str
    decision: Decision
    missing_fields: Optional[list[str]] = None
    escalation_reason: Optional[str] = None


class RuleResult(BaseModel):
    """Internal model passed between rule engine and decision engine."""

    missing_fields: list[str] = Field(default_factory=list)
    escalation_reasons: list[str] = Field(default_factory=list)


class LLMClassificationResult(BaseModel):
    """Structured response expected from the LLM for free-text analysis."""

    source_of_funds: TextClassification = TextClassification.CLEAR
    source_of_funds_reason: str = ""
    accreditation_details: TextClassification = TextClassification.CLEAR
    accreditation_details_reason: str = ""
