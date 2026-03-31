"""Tests for input validation and schema edge cases."""

import pytest

from src.schemas import AgentOutput, Decision, Questionnaire


class TestQuestionnaireValidation:
    def test_valid_record_parses(self):
        q = Questionnaire(
            questionnaire_id="test-001",
            investor_name="Test",
            submission_date="2025-05-01",
        )
        assert q.questionnaire_id == "test-001"

    def test_string_investment_amount_coerced(self):
        """Hidden test set might have amounts as strings."""
        q = Questionnaire(
            questionnaire_id="test-001",
            investment_amount="50000",
            submission_date="2025-05-01",
        )
        assert q.investment_amount == 50000.0

    def test_unparseable_investment_amount_becomes_none(self):
        """Garbage values become None (missing), not crash."""
        q = Questionnaire(
            questionnaire_id="test-001",
            investment_amount="not_a_number",
            submission_date="2025-05-01",
        )
        assert q.investment_amount is None

    def test_minimal_record_parses(self):
        """Only questionnaire_id is truly required at parse time."""
        q = Questionnaire(questionnaire_id="minimal-001", submission_date="2025-01-01")
        assert q.investor_name is None
        assert q.investment_amount is None


class TestAgentOutput:
    def test_approve_output_format(self):
        out = AgentOutput(
            questionnaire_id="test-001",
            decision=Decision.APPROVE,
        )
        d = out.model_dump()
        assert d["decision"] == "Approve"
        assert d["missing_fields"] is None
        assert d["escalation_reason"] is None

    def test_return_output_format(self):
        out = AgentOutput(
            questionnaire_id="test-001",
            decision=Decision.RETURN,
            missing_fields=["investor_name", "tax_id_provided"],
        )
        d = out.model_dump()
        assert d["decision"] == "Return"
        assert d["missing_fields"] == ["investor_name", "tax_id_provided"]

    def test_escalate_output_format(self):
        out = AgentOutput(
            questionnaire_id="test-001",
            decision=Decision.ESCALATE,
            escalation_reason="Investor is not accredited",
        )
        d = out.model_dump()
        assert d["decision"] == "Escalate"
        assert d["escalation_reason"] == "Investor is not accredited"
