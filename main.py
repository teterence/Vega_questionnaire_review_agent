"""
CLI entrypoint for the Vega Questionnaire Review Agent.

Commands:
  review   — Process questionnaires from a JSON file and output decisions
  correct  — Submit a human correction for a previous agent decision
  history  — View past corrections stored in the feedback database
  rules    — View or add learned rules derived from corrections

Usage:
  python main.py review --input data/sample_input.json --output output/results.json
  python main.py correct --id "abc123" --decision Escalate --reason "..." --category source_of_funds
  python main.py history
  python main.py rules --list
  python main.py rules --add "Descriptions mentioning 'family trust' without specifics should be escalated" --category source_of_funds
"""

from __future__ import annotations

import src.config  # noqa: F401 — loads .env before anything else

import argparse
import json
import logging
import sys
from pathlib import Path

from src.decision_engine import review_questionnaire
from src.feedback import FeedbackStore
from src.schemas import AgentOutput, Questionnaire

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def cmd_review(args: argparse.Namespace):
    """Process all questionnaires in the input file."""
    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        logger.error("Input file not found: %s", input_path)
        sys.exit(1)

    # Load and parse input
    with open(input_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # Handle both single object and list of objects
    if isinstance(raw_data, dict):
        raw_data = [raw_data]

    if not isinstance(raw_data, list):
        logger.error("Input must be a JSON array or object")
        sys.exit(1)

    logger.info("Loaded %d questionnaire(s) from %s", len(raw_data), input_path)

    # Initialise feedback store for learning context
    feedback_store = FeedbackStore()

    results: list[dict] = []
    for i, record in enumerate(raw_data):
        try:
            q = Questionnaire(**record)
        except Exception as e:
            logger.error("Failed to parse record %d: %s", i, e)
            # Graceful degradation: escalate unparseable records
            qid = record.get("questionnaire_id", f"unknown_{i}")
            results.append(
                AgentOutput(
                    questionnaire_id=qid,
                    decision="Escalate",
                    missing_fields=None,
                    escalation_reason=f"Failed to parse questionnaire: {e}",
                ).model_dump()
            )
            continue

        # Run the review pipeline
        output: AgentOutput = review_questionnaire(q, feedback_store)
        results.append(output.model_dump())

        # Log decision for audit trail
        feedback_store.log_decision(
            questionnaire_id=q.questionnaire_id,
            decision=output.decision.value,
            missing_fields=output.missing_fields,
            escalation_reason=output.escalation_reason,
            questionnaire_data=record,
        )

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    logger.info("Results written to %s", output_path)

    # Print summary
    decisions = [r["decision"] for r in results]
    print(f"\n{'='*50}")
    print(f"  REVIEW SUMMARY")
    print(f"{'='*50}")
    print(f"  Total processed:  {len(results)}")
    print(f"  Approved:         {decisions.count('Approve')}")
    print(f"  Returned:         {decisions.count('Return')}")
    print(f"  Escalated:        {decisions.count('Escalate')}")
    print(f"{'='*50}\n")

    feedback_store.close()


def cmd_correct(args: argparse.Namespace):
    """Submit a human correction for a previous decision."""
    feedback_store = FeedbackStore()

    feedback_store.add_correction(
        questionnaire_id=args.id,
        original_decision=args.original or "Unknown",
        corrected_decision=args.decision,
        correction_reason=args.reason,
        category=args.category,
        field_value=args.field_value,
    )

    print(f"Correction recorded for questionnaire {args.id}")
    print(f"  Decision: {args.decision}")
    print(f"  Category: {args.category}")
    print(f"  Reason: {args.reason}")
    print(
        "\nThis correction will influence future reviews. "
        "Re-run 'review' to see the updated behaviour."
    )
    feedback_store.close()


def cmd_history(args: argparse.Namespace):
    """View past corrections."""
    feedback_store = FeedbackStore()
    corrections = feedback_store.get_all_corrections(limit=args.limit)

    if not corrections:
        print("No corrections recorded yet.")
        feedback_store.close()
        return

    print(f"\n{'='*60}")
    print(f"  CORRECTION HISTORY (last {args.limit})")
    print(f"{'='*60}")
    for c in corrections:
        print(f"\n  ID: {c['questionnaire_id']}")
        print(f"  Original:  {c['original_decision']}")
        print(f"  Corrected: {c['corrected_decision']}")
        print(f"  Category:  {c['category']}")
        print(f"  Reason:    {c['correction_reason']}")
    print(f"\n{'='*60}\n")
    feedback_store.close()


def cmd_rules(args: argparse.Namespace):
    """View or add learned rules."""
    feedback_store = FeedbackStore()

    if args.add:
        feedback_store.add_learned_rule(args.add, args.category or "general")
        print(f"Learned rule added: {args.add}")
    else:
        rules = feedback_store.get_learned_rules()
        if not rules:
            print("No learned rules yet. Add one with: python main.py rules --add '...'")
        else:
            print(f"\nActive learned rules ({len(rules)}):")
            for i, rule in enumerate(rules, 1):
                print(f"  {i}. {rule}")
            print()

    feedback_store.close()


def main():
    parser = argparse.ArgumentParser(
        description="Vega Questionnaire Review Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- review command ---
    p_review = subparsers.add_parser("review", help="Process questionnaires")
    p_review.add_argument(
        "--input", "-i",
        default="data/sample_input.json",
        help="Path to input JSON file (default: data/sample_input.json)",
    )
    p_review.add_argument(
        "--output", "-o",
        default="output/results.json",
        help="Path to output JSON file (default: output/results.json)",
    )
    p_review.set_defaults(func=cmd_review)

    # --- correct command ---
    p_correct = subparsers.add_parser("correct", help="Submit a human correction")
    p_correct.add_argument("--id", required=True, help="Questionnaire ID")
    p_correct.add_argument(
        "--decision", required=True,
        choices=["Approve", "Return", "Escalate"],
        help="Corrected decision",
    )
    p_correct.add_argument("--reason", required=True, help="Why the correction was made")
    p_correct.add_argument(
        "--category", default="general",
        choices=["source_of_funds", "accreditation_details", "general"],
        help="Which aspect the correction relates to",
    )
    p_correct.add_argument("--original", default=None, help="Original agent decision")
    p_correct.add_argument("--field-value", default=None, help="The text value being corrected")
    p_correct.set_defaults(func=cmd_correct)

    # --- history command ---
    p_history = subparsers.add_parser("history", help="View correction history")
    p_history.add_argument("--limit", type=int, default=20, help="Max records to show")
    p_history.set_defaults(func=cmd_history)

    # --- rules command ---
    p_rules = subparsers.add_parser("rules", help="View or add learned rules")
    p_rules.add_argument("--add", default=None, help="Add a new learned rule")
    p_rules.add_argument("--category", default="general", help="Category for the rule")
    p_rules.add_argument("--list", action="store_true", help="List active rules")
    p_rules.set_defaults(func=cmd_rules)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
