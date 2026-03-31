"""
Tests for the rule engine. This is the deterministic layer — if these fail,
nothing downstream matters. Every edge case the hidden test set might contain
should be caught here.
"""

import pytest

from src.rules import run_rules
from src.schemas import Questionnaire


def _make_q(**overrides) -> Questionnaire:
    """Factory for valid questionnaires. Override specific fields to test edge cases."""
    defaults = {
        "questionnaire_id": "test-001",
        "investor_name": "Test Investor",
        "investor_type": "Natural Person",
        "investor_address": "123 Test St, Test City, TS 00000",
        "investment_amount": 100000,
        "is_accredited_investor": True,
        "accreditation_details": "Net worth over $1M.",
        "source_of_funds_description": "Personal savings.",
        "tax_id_provided": True,
        "signature_present": True,
        "submission_date": "2025-05-01",
    }
    defaults.update(overrides)
    return Questionnaire(**defaults)


# --- Missing field tests ---

class TestMissingFields:
    def test_all_present_no_missing(self):
        result = run_rules(_make_q())
        assert result.missing_fields == []
        assert result.escalation_reasons == []

    def test_missing_investor_name(self):
        result = run_rules(_make_q(investor_name=None))
        assert "investor_name" in result.missing_fields

    def test_empty_string_investor_name(self):
        result = run_rules(_make_q(investor_name=""))
        assert "investor_name" in result.missing_fields

    def test_whitespace_only_investor_name(self):
        result = run_rules(_make_q(investor_name="   "))
        assert "investor_name" in result.missing_fields

    def test_missing_address(self):
        result = run_rules(_make_q(investor_address=None))
        assert "investor_address" in result.missing_fields

    def test_missing_investment_amount(self):
        result = run_rules(_make_q(investment_amount=None))
        assert "investment_amount" in result.missing_fields

    def test_missing_accreditation(self):
        result = run_rules(_make_q(is_accredited_investor=None))
        assert "is_accredited_investor" in result.missing_fields

    def test_multiple_missing(self):
        result = run_rules(_make_q(investor_name=None, investor_address=None))
        assert "investor_name" in result.missing_fields
        assert "investor_address" in result.missing_fields


# --- Boolean field tests ---

class TestBooleanFields:
    def test_signature_false_is_missing(self):
        result = run_rules(_make_q(signature_present=False))
        assert "signature_present" in result.missing_fields

    def test_signature_true_is_ok(self):
        result = run_rules(_make_q(signature_present=True))
        assert "signature_present" not in result.missing_fields

    def test_tax_id_false_is_missing(self):
        result = run_rules(_make_q(tax_id_provided=False))
        assert "tax_id_provided" in result.missing_fields

    def test_tax_id_true_is_ok(self):
        result = run_rules(_make_q(tax_id_provided=True))
        assert "tax_id_provided" not in result.missing_fields

    def test_not_accredited_escalates(self):
        result = run_rules(_make_q(is_accredited_investor=False))
        assert "Investor is not accredited" in result.escalation_reasons
        # Not accredited should NOT be in missing fields
        assert "is_accredited_investor" not in result.missing_fields

    def test_accredited_no_escalation(self):
        result = run_rules(_make_q(is_accredited_investor=True))
        assert result.escalation_reasons == []


# --- Investment amount edge cases ---

class TestInvestmentAmount:
    def test_positive_amount_ok(self):
        result = run_rules(_make_q(investment_amount=50000))
        assert "investment_amount" not in result.missing_fields

    def test_zero_amount_flagged(self):
        result = run_rules(_make_q(investment_amount=0))
        assert "investment_amount" in result.missing_fields

    def test_negative_amount_flagged(self):
        result = run_rules(_make_q(investment_amount=-1000))
        assert "investment_amount" in result.missing_fields

    def test_very_small_positive_amount_ok(self):
        result = run_rules(_make_q(investment_amount=0.01))
        assert "investment_amount" not in result.missing_fields


# --- Sample data tests (match expected outputs from Appendix A) ---

class TestSampleData:
    def test_sample1_approve_path(self):
        """Sample 1: all fields present, accredited, clean text → rules pass"""
        result = run_rules(_make_q())
        assert result.missing_fields == []
        assert result.escalation_reasons == []

    def test_sample2_return_path(self):
        """Sample 2: missing investment_amount and tax_id false → Return"""
        result = run_rules(_make_q(investment_amount=None, tax_id_provided=False))
        assert "investment_amount" in result.missing_fields
        assert "tax_id_provided" in result.missing_fields

    def test_sample4_return_path(self):
        """Sample 4: missing address and signature false → Return"""
        result = run_rules(_make_q(investor_address=None, signature_present=False))
        assert "investor_address" in result.missing_fields
        assert "signature_present" in result.missing_fields

    def test_sample5_escalate_path(self):
        """Sample 5: not accredited → Escalate"""
        result = run_rules(_make_q(is_accredited_investor=False))
        assert "Investor is not accredited" in result.escalation_reasons
