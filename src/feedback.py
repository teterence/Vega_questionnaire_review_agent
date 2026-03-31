"""
SQLite-backed feedback store for human corrections and learned rules.

Three responsibilities:
  1. Log every agent decision for audit trail
  2. Store human corrections when they disagree with the agent
  3. Retrieve relevant corrections to inject as few-shot examples into future LLM calls

The schema is deliberately designed to double as future ML training data —
every correction is a labelled example waiting to be used for fine-tuning.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_DEFAULT_DB_PATH = Path("feedback_store/feedback.db")


class FeedbackStore:
    def __init__(self, db_path: Path = _DEFAULT_DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                questionnaire_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                missing_fields TEXT,
                escalation_reason TEXT,
                questionnaire_data TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                questionnaire_id TEXT NOT NULL,
                original_decision TEXT NOT NULL,
                corrected_decision TEXT NOT NULL,
                correction_reason TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                field_value TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS learned_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_text TEXT NOT NULL,
                source_category TEXT NOT NULL,
                created_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            );
        """)
        self._conn.commit()

    def log_decision(
        self,
        questionnaire_id: str,
        decision: str,
        missing_fields: Optional[list[str]],
        escalation_reason: Optional[str],
        questionnaire_data: dict,
    ):
        """Log every agent decision for audit trail."""
        self._conn.execute(
            """INSERT INTO decisions
               (questionnaire_id, decision, missing_fields, escalation_reason,
                questionnaire_data, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                questionnaire_id,
                decision,
                json.dumps(missing_fields) if missing_fields else None,
                escalation_reason,
                json.dumps(questionnaire_data),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()

    def add_correction(
        self,
        questionnaire_id: str,
        original_decision: str,
        corrected_decision: str,
        correction_reason: str,
        category: str = "general",
        field_value: Optional[str] = None,
    ):
        """Store a human correction. This is the core learning input."""
        self._conn.execute(
            """INSERT INTO corrections
               (questionnaire_id, original_decision, corrected_decision,
                correction_reason, category, field_value, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                questionnaire_id,
                original_decision,
                corrected_decision,
                correction_reason,
                category,
                field_value,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()

    def get_corrections_by_category(self, category: str, limit: int = 5) -> list[dict]:
        """Retrieve relevant past corrections for few-shot injection.
        Only pulls corrections matching the category, most recent first."""
        rows = self._conn.execute(
            """SELECT corrected_decision, correction_reason, field_value
               FROM corrections
               WHERE category = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (category, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_corrections(self, limit: int = 10) -> list[dict]:
        """Retrieve all recent corrections for general context."""
        rows = self._conn.execute(
            """SELECT questionnaire_id, original_decision, corrected_decision,
                      correction_reason, category
               FROM corrections
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_learned_rules(self) -> list[str]:
        """Retrieve active learned rules for system prompt injection."""
        rows = self._conn.execute(
            "SELECT rule_text FROM learned_rules WHERE active = 1"
        ).fetchall()
        return [r["rule_text"] for r in rows]

    def add_learned_rule(self, rule_text: str, category: str):
        """Promote a pattern from corrections into a standing rule."""
        self._conn.execute(
            """INSERT INTO learned_rules (rule_text, source_category, created_at)
               VALUES (?, ?, ?)""",
            (rule_text, category, datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    def close(self):
        self._conn.close()
