"""
Integration test for the full review pipeline.
Mocks the LLM call so tests run without an API key.
Validates that all 5 sample records produce the expected decisions.
"""

import json
from pathlib import Path
from unittest.mock import patch

from src.decision_engine import review_questionnaire
from src.schemas import (
    LLMClassificationResult,
    Questionnaire,
    TextClassification,
)


SAMPLE_DATA_PATH = Path("data/sample_input.json")


def _load_samples() -> list[dict]:
    with open(SAMPLE_DATA_PATH) as f:
        return json.load(f)


def _mock_analyse_text(source_of_funds, accreditation_details, feedback_store=None):
    """Simulate LLM responses matching what the real model would return."""
    result = LLMClassificationResult()

    # Classify source of funds
    if source_of_funds:
        lower = source_of_funds.lower()
        if any(w in lower for w in ["various", "multiple", "tbd", "family contributions"]):
            result.source_of_funds = TextClassification.AMBIGUOUS
            result.source_of_funds_reason = "Vague language — insufficient specificity"
        elif any(w in lower for w in ["black market", "illegal", "laundering"]):
            result.source_of_funds = TextClassification.RED_FLAG
            result.source_of_funds_reason = "References to illegal activity"

    # Classify accreditation details
    if accreditation_details:
        lower = accreditation_details.lower()
        if any(w in lower for w in ["does not meet", "not qualified", "insufficient"]):
            result.accreditation_details = TextClassification.AMBIGUOUS
            result.accreditation_details_reason = "Accreditation not substantiated"

    return result


class TestFullPipeline:
    """Validate the agent produces correct decisions for all 5 sample records."""

    @patch("src.decision_engine.analyse_text", side_effect=_mock_analyse_text)
    def test_sample1_approved(self, mock_llm):
        """Mr and Mrs Simpson — all clean → Approve"""
        samples = _load_samples()
        q = Questionnaire(**samples[0])
        result = review_questionnaire(q)
        assert result.decision.value == "Approve"
        assert result.missing_fields is None
        assert result.escalation_reason is None

    def test_sample2_return_no_llm(self):
        """Example Corp — missing investment_amount + tax_id false → Return.
        No LLM call needed (rule engine catches it)."""
        samples = _load_samples()
        q = Questionnaire(**samples[1])
        result = review_questionnaire(q)
        assert result.decision.value == "Return"
        assert "investment_amount" in result.missing_fields
        assert "tax_id_provided" in result.missing_fields

    @patch("src.decision_engine.analyse_text", side_effect=_mock_analyse_text)
    def test_sample3_escalate_ambiguous(self, mock_llm):
        """Investor Three — 'Various sources including family contributions' → Escalate"""
        samples = _load_samples()
        q = Questionnaire(**samples[2])
        result = review_questionnaire(q)
        assert result.decision.value == "Escalate"
        assert "source of funds" in result.escalation_reason.lower()

    def test_sample4_return_no_llm(self):
        """Investor Four Trust — missing address + signature false → Return.
        No LLM call needed."""
        samples = _load_samples()
        q = Questionnaire(**samples[3])
        result = review_questionnaire(q)
        assert result.decision.value == "Return"
        assert "investor_address" in result.missing_fields
        assert "signature_present" in result.missing_fields

    def test_sample5_escalate_no_llm(self):
        """Investor Five — not accredited → Escalate.
        No LLM call needed (rule engine catches it)."""
        samples = _load_samples()
        q = Questionnaire(**samples[4])
        result = review_questionnaire(q)
        assert result.decision.value == "Escalate"
        assert "not accredited" in result.escalation_reason.lower()

    def test_deterministic_samples_need_no_llm(self):
        """Samples 2, 4, 5 should be resolved by rules alone — verify no LLM called."""
        samples = _load_samples()

        # These should NOT call analyse_text at all
        with patch("src.decision_engine.analyse_text") as mock_llm:
            for idx in [1, 3, 4]:  # samples 2, 4, 5 (0-indexed)
                q = Questionnaire(**samples[idx])
                review_questionnaire(q)

            # LLM should never have been called for these three
            mock_llm.assert_not_called()
