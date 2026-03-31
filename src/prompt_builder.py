"""
Prompt builder. Assembles the LLM prompt from three sources:

1. Base system prompt (static rules from prompts/reviewer_system.txt)
2. Learned rules (distilled from accumulated corrections — durable knowledge)
3. Relevant corrections as few-shot examples (case-specific context)

Separation matters:
  - System prompt = standing policy (what a reviewer always knows)
  - User prompt = this specific case + relevant precedents
"""

from __future__ import annotations

from pathlib import Path

from .feedback import FeedbackStore

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_system_prompt() -> str:
    """Load the base system prompt from file."""
    prompt_path = _PROMPTS_DIR / "reviewer_system.txt"
    return prompt_path.read_text(encoding="utf-8").strip()


def build_system_prompt(feedback_store: FeedbackStore | None = None) -> str:
    """Assemble the full system prompt with any learned rules appended."""
    base = load_system_prompt()

    if feedback_store is None:
        return base

    learned_rules = feedback_store.get_learned_rules()
    if not learned_rules:
        return base

    rules_block = "\n\nADDITIONAL LEARNED RULES (from human reviewer feedback):\n"
    for i, rule in enumerate(learned_rules, 1):
        rules_block += f"{i}. {rule}\n"

    return base + rules_block


def build_user_prompt(
    source_of_funds: str | None,
    accreditation_details: str | None,
    feedback_store: FeedbackStore | None = None,
) -> str:
    """Build the user prompt for a specific questionnaire review.

    Includes the text fields to classify and any relevant past corrections.
    """
    parts: list[str] = []

    # Inject relevant corrections as few-shot examples
    if feedback_store is not None:
        corrections: list[dict] = []

        if source_of_funds:
            corrections.extend(
                feedback_store.get_corrections_by_category("source_of_funds", limit=3)
            )
        if accreditation_details:
            corrections.extend(
                feedback_store.get_corrections_by_category(
                    "accreditation_details", limit=3
                )
            )

        if corrections:
            parts.append("RELEVANT PRECEDENTS FROM HUMAN REVIEWERS:")
            for c in corrections:
                parts.append(
                    f'- Text: "{c.get("field_value", "N/A")}" '
                    f'→ Corrected to: {c["corrected_decision"]} '
                    f'| Reason: {c["correction_reason"]}'
                )
            parts.append("")
            parts.append(
                "Apply these precedents to the classification below. "
                "If the current text is similar to a precedent, follow the "
                "human reviewer's judgment.\n"
            )

    # The actual fields to classify
    parts.append("Classify the following fields from an investor questionnaire:\n")
    parts.append(
        f"source_of_funds_description: "
        f'"{source_of_funds if source_of_funds else "[NOT PROVIDED]"}"'
    )
    parts.append(
        f"accreditation_details: "
        f'"{accreditation_details if accreditation_details else "[NOT PROVIDED]"}"'
    )

    return "\n".join(parts)
