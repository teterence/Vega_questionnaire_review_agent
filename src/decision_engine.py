"""
Decision engine. Merges rule engine results with LLM text analysis into a
final Approve / Return / Escalate decision.

Priority order (highest to lowest):
  1. Missing required fields → Return (deterministic, no LLM needed)
  2. Rule-based escalations (e.g. not accredited) → Escalate (no LLM needed)
  3. LLM red flags → Escalate
  4. LLM ambiguity → Escalate
  5. Everything clear → Approve

This ordering means:
  - A questionnaire with missing fields is ALWAYS returned, even if it also
    has red flags (fix the form first, then review the content)
  - The LLM is only called when the rule engine finds no issues
  - The agent never approves if any component flags an issue
"""

from __future__ import annotations

import logging

from .feedback import FeedbackStore
from .llm_reviewer import analyse_text
from .rules import run_rules
from .schemas import (
    AgentOutput,
    Decision,
    LLMClassificationResult,
    Questionnaire,
    TextClassification,
)

logger = logging.getLogger(__name__)


def review_questionnaire(
    q: Questionnaire,
    feedback_store: FeedbackStore | None = None,
) -> AgentOutput:
    """Process a single questionnaire and return the agent's decision.

    This is the main entry point for the agent pipeline:
      Input → Rules → [LLM if needed] → Decision → Output
    """
    # --- Stage 1: Deterministic rule checks ---
    rule_result = run_rules(q)

    # If there are missing fields, return immediately so no LLM call is needed
    if rule_result.missing_fields:
        logger.info(
            "[%s] RETURN — missing fields: %s",
            q.questionnaire_id,
            rule_result.missing_fields,
        )
        return AgentOutput(
            questionnaire_id=q.questionnaire_id,
            decision=Decision.RETURN,
            missing_fields=rule_result.missing_fields,
            escalation_reason=None,
        )

    # If rules found escalation reasons (e.g. not accredited), escalate now
    if rule_result.escalation_reasons:
        reason = "; ".join(rule_result.escalation_reasons)
        logger.info("[%s] ESCALATE (rules) — %s", q.questionnaire_id, reason)
        return AgentOutput(
            questionnaire_id=q.questionnaire_id,
            decision=Decision.ESCALATE,
            missing_fields=None,
            escalation_reason=reason,
        )

    # --- Stage 2: LLM analysis of free-text fields ---
    llm_result: LLMClassificationResult = analyse_text(
        source_of_funds=q.source_of_funds_description,
        accreditation_details=q.accreditation_details,
        feedback_store=feedback_store,
    )

    # --- Stage 3: Merge LLM results into decision ---
    escalation_reasons: list[str] = []

    # Check source of funds
    if llm_result.source_of_funds == TextClassification.RED_FLAG:
        escalation_reasons.append(
            f"Red flag in source of funds: {llm_result.source_of_funds_reason}"
        )
    elif llm_result.source_of_funds == TextClassification.AMBIGUOUS:
        escalation_reasons.append(
            f"Ambiguous source of funds: {llm_result.source_of_funds_reason}"
        )

    # Check accreditation details
    if llm_result.accreditation_details == TextClassification.RED_FLAG:
        escalation_reasons.append(
            f"Red flag in accreditation details: {llm_result.accreditation_details_reason}"
        )
    elif llm_result.accreditation_details == TextClassification.AMBIGUOUS:
        escalation_reasons.append(
            f"Ambiguous accreditation details: {llm_result.accreditation_details_reason}"
        )

    if escalation_reasons:
        reason = "; ".join(escalation_reasons)
        logger.info("[%s] ESCALATE (LLM) — %s", q.questionnaire_id, reason)
        return AgentOutput(
            questionnaire_id=q.questionnaire_id,
            decision=Decision.ESCALATE,
            missing_fields=None,
            escalation_reason=reason,
        )

    # --- Stage 4: All checks passed ---
    logger.info("[%s] APPROVE", q.questionnaire_id)
    return AgentOutput(
        questionnaire_id=q.questionnaire_id,
        decision=Decision.APPROVE,
        missing_fields=None,
        escalation_reason=None,
    )
