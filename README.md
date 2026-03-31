# Vega Questionnaire Review Agent

An AI agent that reviews PE fund subscription questionnaires and decides whether to **Approve**, **Return to Subscriber**, or **Escalate to Human Review**.

Built with a deterministic-first architecture: the rule engine handles ~60% of cases without any LLM call. The LLM is invoked only for free-text ambiguity analysis — minimising cost, latency, and non-determinism.

---

## Quick Start

### Prerequisites

- Python 3.11+
- A free Groq API key ([console.groq.com](https://console.groq.com))

### Setup

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/vega-questionnaire-agent.git
cd vega-questionnaire-agent

# Install dependencies
pip install -r requirements.txt

# Configure API key
cp .env.example .env
# Edit .env and add your GROQ_API_KEY
```

### Run the Agent

```bash
# Review the sample questionnaires
python main.py review --input data/sample_input.json --output output/results.json

# Review a custom file
python main.py review --input path/to/your/questionnaires.json --output output/results.json
```

### Run Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

---

## Architecture

```
Input JSON
  │
  ▼
┌─────────────────────────────────┐
│  Pydantic Validation            │  Malformed records → Escalate
│  (schemas.py)                   │  Type coercion (e.g. string → float)
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│  Rule Engine                    │  Missing required fields → Return
│  (rules.py)                     │  signature_present=false → Return
│                                 │  tax_id_provided=false → Return
│  100% deterministic             │  is_accredited=false → Escalate
│  Zero LLM calls                 │  investment_amount ≤ 0 → Return
│  Handles ~60% of cases          │
└──────────────┬──────────────────┘
               │ (only if all rules pass)
               ▼
┌─────────────────────────────────┐
│  Input Sanitisation             │  Prompt injection patterns → Escalate
│  (sanitiser.py)                 │  Protects LLM from adversarial input
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│  LLM Text Analysis              │  Classifies free-text fields as:
│  (llm_reviewer.py)              │    clear / ambiguous / red_flag
│                                 │
│  Llama 3.3 70B via Groq         │  Temperature: 0 (deterministic)
│  JSON mode enforced             │  Retries once, then → Escalate
│  Called ONLY for free-text       │  Includes few-shot corrections
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│  Decision Engine                │  Merges rule + LLM results
│  (decision_engine.py)           │  Priority: Return > Escalate > Approve
│                                 │  Conservative: never approves on doubt
└──────────────┬──────────────────┘
               │
               ▼
           Output JSON + Audit Log (SQLite)
```

### Design Principles

1. **Rules first, LLM last.** Every deterministic check that can be done without an LLM, is. The LLM is expensive, slow, and non-deterministic — it should only handle what rules cannot: interpreting natural language.

2. **Conservative by default.** The cost of a false escalation (a human reviews something unnecessarily) is trivially low. The cost of a false approval (regulatory exposure) is severe. The agent defaults to escalation on any uncertainty, including LLM failures.

3. **Minimal dependencies.** Three production dependencies: `openai` (Groq-compatible SDK), `pydantic` (strict validation), `python-dotenv` (config). No frameworks, no chains, no orchestrators. Every line of code is justified.

4. **Sanitisation before LLM.** User-supplied text flows directly into LLM prompts. The sanitiser detects prompt injection patterns and flags them as red flags before the text reaches the model.

---

## Decision Logic

### Return to Subscriber

Triggered when required information is missing or invalid. These checks are purely deterministic:

- Any of `investor_name`, `investor_address`, `investment_amount`, `is_accredited_investor`, `signature_present`, `tax_id_provided` is null or empty
- `signature_present` is `false` (signature not completed)
- `tax_id_provided` is `false` (no tax ID on file)
- `investment_amount` is zero or negative

Missing fields are always resolved before content review — there's no point analysing the source of funds if the form is incomplete.

### Escalate to Human Review

Triggered by policy violations or ambiguity that requires human judgment:

- **Rule-based:** `is_accredited_investor` is `false` (regulatory requirement — non-accredited investors in PE funds require special handling)
- **Rule-based:** Prompt injection detected in free-text fields
- **LLM-based:** `source_of_funds_description` is vague (e.g., "various sources", "TBD"), suspicious (references to illegal activity), or insufficiently specific
- **LLM-based:** `accreditation_details` are ambiguous, contradictory, or unsubstantiated
- **Fallback:** LLM call fails after retry — escalate rather than risk approving

### Approve

Only when ALL of the following are true:

- All required fields present and valid
- `is_accredited_investor` is `true`
- `signature_present` is `true`
- `tax_id_provided` is `true`
- `investment_amount` is positive
- Source of funds classified as "clear" by LLM
- Accreditation details classified as "clear" by LLM
- No prompt injection detected

---

## Handling Ambiguity

Free-text fields (`source_of_funds_description`, `accreditation_details`) require interpretation that rules cannot provide. The agent uses Llama 3.3 70B via Groq with:

- **Temperature 0:** Same input produces the same output. Critical for compliance — two identical submissions must receive identical treatment.
- **JSON mode enforced:** The model returns structured classifications, not free-form text. Pydantic validates the response schema.
- **Conservative system prompt:** The model is instructed to classify as "ambiguous" when in doubt. Specific rules are embedded for common patterns (e.g., "the word 'various' without further detail is ALWAYS ambiguous").
- **Externalised prompt:** The system prompt lives in `prompts/reviewer_system.txt`, not hardcoded. This makes it auditable, version-controllable, and easy to iterate on without code changes.
- **Retry with fallback:** If the LLM returns malformed output or times out, the agent retries once. If the second attempt fails, the questionnaire is escalated — never approved on a failed analysis.

---

## Learning Mechanism

The agent improves over time through a three-tier feedback system:

### Tier 1: Correction Capture (Immediate)

Human reviewers can correct any agent decision:

```bash
python main.py correct \
  --id "3c78912e-2cgh-6d8f-0123-437e66e1ec8c" \
  --decision Escalate \
  --reason "Family contributions without specifics should always be escalated" \
  --category source_of_funds \
  --field-value "Various sources including family contributions." \
  --original Approve
```

Corrections are stored in a SQLite database (`feedback_store/feedback.db`) with the original decision, corrected decision, reason, and category.

### Tier 2: Selective Retrieval (Per-Review)

When the agent reviews a new questionnaire, the prompt builder queries the correction store for **relevant** past corrections — not all corrections, only those matching the current review context (e.g., corrections categorised as `source_of_funds` when the current questionnaire has a source-of-funds field to analyse).

These corrections are injected into the LLM's user prompt as precedents:

```
RELEVANT PRECEDENTS FROM HUMAN REVIEWERS:
- Text: "Various sources including family contributions."
  → Corrected to: Escalate
  | Reason: Family contributions without specifics should always be escalated

Apply these precedents to the classification below...
```

The LLM now has direct access to the institution's accumulated compliance judgment, not just its training data.

### Tier 3: Rule Extraction (Durable Knowledge)

When patterns emerge from multiple corrections, they can be promoted into standing rules:

```bash
python main.py rules --add \
  "Source of funds descriptions referencing family contributions without specifying the exact nature, amount, or legal relationship should be classified as ambiguous." \
  --category source_of_funds
```

Learned rules are injected into the **system prompt** (not the user prompt), making them permanent policy rather than case-specific context. This mirrors how human compliance teams work: individual case reviews build institutional knowledge that becomes standing procedure.

### Viewing Feedback State

```bash
# View correction history
python main.py history

# View active learned rules
python main.py rules --list
```

### Demo: Before and After

1. Run the agent: `python main.py review -i data/sample_input.json -o output/results.json`
2. Submit a correction: `python main.py correct --id "1a59843c..." --decision Escalate --reason "Need more detail on employment income source" --category source_of_funds --original Approve`
3. Re-run the agent: `python main.py review -i data/sample_input.json -o output/results.json`
4. Observe the corrected decision reflected in the new output

---

## Production Evolution

In production, a PE fund might onboard hundreds of investors per year across multiple fund vintages. While each subscription is reviewed once, the language investors use to describe their funding sources clusters into recognisable patterns — "personal savings and salary", "sale of prior business", "trust distributions", and so on.

A production evolution of this agent would capture that institutional knowledge explicitly: each time a human corrects or confirms a decision, the associated text is embedded and stored in a similarity bank. Over time, the agent becomes a reflection of the fund's own compliance judgment — not just generic LLM reasoning, but the specific standards and interpretations that firm's reviewers have established. New submissions that resemble previously-adjudicated cases are handled instantly and consistently, while genuinely novel cases are still routed to the LLM and ultimately to a human if needed. The result is an agent that gets cheaper, faster, and more aligned with the firm's risk posture the longer it operates.

Further production considerations:

- **Fine-tuned classifier:** With sufficient labelled corrections (200-500+ per class), the LLM could be replaced with a fine-tuned lightweight model (e.g., DistilBERT with LoRA) for common classifications — reducing cost and latency to near-zero for known patterns.
- **Batch processing:** Groq's rate limits (free tier: ~30 req/min) would require batching or a paid tier at production volume. The architecture already isolates LLM calls to a single module, making this a configuration change, not a redesign.
- **Audit trail:** The SQLite decision log provides a complete audit trail. In production, this would be replaced with a proper database (PostgreSQL) with retention policies aligned to the fund's regulatory requirements.
- **Model versioning:** The feedback store schema includes space for tracking which model version made each decision, enabling A/B testing and rollback.

---

## Project Structure

```
vega-questionnaire-agent/
├── main.py                    # CLI entrypoint (review, correct, history, rules)
├── src/
│   ├── schemas.py             # Pydantic models — input, output, internal types
│   ├── rules.py               # Deterministic rule engine
│   ├── sanitiser.py           # Prompt injection detection
│   ├── llm_reviewer.py        # LLM text analysis (Groq / Llama 3.3 70B)
│   ├── prompt_builder.py      # System + user prompt assembly with feedback
│   ├── decision_engine.py     # Merges rules + LLM into final decision
│   ├── feedback.py            # SQLite-backed correction and rule store
│   └── config.py              # Environment variable loader
├── prompts/
│   └── reviewer_system.txt    # Externalised system prompt
├── data/
│   └── sample_input.json      # 5 sample questionnaires from the brief
├── output/
│   └── results.json           # Agent output (generated on run)
├── feedback_store/
│   └── feedback.db            # SQLite database (generated on run)
├── tests/
│   ├── test_rules.py          # Rule engine unit tests
│   ├── test_sanitiser.py      # Sanitisation tests
│   ├── test_schemas.py        # Validation and schema tests
│   └── test_integration.py    # Full pipeline tests (mocked LLM)
├── pyproject.toml             # Project metadata and dependencies
├── requirements.txt           # Pip-compatible dependency list
├── .env.example               # API key template
├── .gitignore
└── README.md
```

## Assumptions and Limitations

### Assumptions

- The input file is valid JSON containing an array (or single object) of questionnaire records
- Field names match the schema in Appendix A exactly
- `submission_date` is not validated (not listed as a review criterion)
- `investor_type` is informational — no business rules are applied to it in this prototype
- The Groq free tier rate limits are sufficient for the evaluation test set

### Limitations

- **LLM non-determinism:** Despite temperature 0, LLM outputs can vary slightly across API calls. The retry + fallback mechanism mitigates this but doesn't eliminate it.
- **Correction volume:** The few-shot learning mechanism is most effective with 5-20 corrections. Beyond ~50, a retrieval or summarisation strategy would be needed to stay within context limits.
- **Single-language support:** The system prompt and keyword detection are English-only. International PE funds would need localisation.
- **No document verification:** The agent trusts the structured data as provided. It does not cross-reference against external databases (e.g., OFAC sanctions lists, SEC EDGAR filings). A production system would integrate these.

---

## Libraries and Tools

| Dependency | Purpose | Justification |
|---|---|---|
| `openai` | LLM API client | Groq is OpenAI-compatible. One SDK, multiple providers. |
| `pydantic` | Data validation | Strict typing catches malformed input at parse time. |
| `python-dotenv` | Config management | Loads API key from `.env` without hardcoding secrets. |
| `sqlite3` (stdlib) | Feedback persistence | Zero-dependency storage. Ships with Python. |
| `argparse` (stdlib) | CLI interface | No external dependency needed for simple subcommands. |
| `pytest` (dev only) | Testing | 45 tests covering rules, sanitisation, schemas, and integration. |
