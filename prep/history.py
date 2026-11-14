"""Practice history in SQLite (default data/local/history.db, which is gitignored)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from prep.meta import difficulty_band

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    mode TEXT NOT NULL,
    filters_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id),
    question_id TEXT NOT NULL,
    question_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    topic TEXT NOT NULL,
    difficulty INTEGER NOT NULL,
    type TEXT NOT NULL,
    started_at TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    duration_sec REAL NOT NULL,
    answer_text TEXT,
    score REAL NOT NULL CHECK (score >= 0 AND score <= 1),
    outcome TEXT NOT NULL CHECK (outcome IN ('correct', 'partial', 'incorrect')),
    hints_used INTEGER NOT NULL DEFAULT 0,
    grading_method TEXT NOT NULL CHECK (grading_method IN ('auto', 'self', 'rubric_self')),
    followup_answers_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_attempts_question ON attempts(question_id);
CREATE INDEX IF NOT EXISTS idx_attempts_session ON attempts(session_id);
"""

ATTEMPT_COLUMNS = [
    "id",
    "session_id",
    "question_id",
    "question_hash",
    "role",
    "topic",
    "difficulty",
    "type",
    "started_at",
    "submitted_at",
    "duration_sec",
    "answer_text",
    "score",
    "outcome",
    "hints_used",
    "grading_method",
    "followup_answers_json",
]


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class History:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # --- writes ------------------------------------------------------------------------------

    def start_session(self, mode: str, filters: dict[str, Any] | None = None) -> int:
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO sessions (started_at, mode, filters_json) VALUES (?, ?, ?)",
                (now_iso(), mode, json.dumps(filters or {}, sort_keys=True, default=str)),
            )
            return int(cur.lastrowid)

    def end_session(self, session_id: int) -> None:
        with self._connect() as con:
            con.execute("UPDATE sessions SET ended_at = ? WHERE id = ?", (now_iso(), session_id))

    def record_attempt(
        self,
        *,
        session_id: int | None,
        question: Any,
        question_hash: str,
        started_at: str,
        submitted_at: str,
        duration_sec: float,
        answer_text: str | None,
        score: float,
        outcome: str,
        hints_used: int,
        grading_method: str,
        followup_answers: dict[str, str] | None = None,
    ) -> int:
        with self._connect() as con:
            cur = con.execute(
                """INSERT INTO attempts (session_id, question_id, question_hash, role, topic,
                   difficulty, type, started_at, submitted_at, duration_sec, answer_text, score,
                   outcome, hints_used, grading_method, followup_answers_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    question.id,
                    question_hash,
                    question.role,
                    question.topic,
                    question.difficulty,
                    question.type,
                    started_at,
                    submitted_at,
                    float(duration_sec),
                    answer_text,
                    float(score),
                    outcome,
                    int(hints_used),
                    grading_method,
                    json.dumps(followup_answers or {}),
                ),
            )
            return int(cur.lastrowid)

    def save_followups(self, attempt_id: int, answers: dict[str, str]) -> None:
        cleaned = {k: v for k, v in answers.items() if v and v.strip()}
        with self._connect() as con:
            con.execute(
                "UPDATE attempts SET followup_answers_json = ? WHERE id = ?",
                (json.dumps(cleaned), attempt_id),
            )

    # --- reads -------------------------------------------------------------------------------

    def attempts(self, session_id: int | None = None) -> pd.DataFrame:
        query = "SELECT * FROM attempts"
        params: tuple = ()
        if session_id is not None:
            query += " WHERE session_id = ?"
            params = (session_id,)
        with self._connect() as con:
            df = pd.read_sql_query(query + " ORDER BY id", con, params=params)
        if df.empty:
            df = pd.DataFrame(columns=ATTEMPT_COLUMNS)
        df["band"] = [difficulty_band(int(d)) for d in df["difficulty"]] if len(df) else []
        return df

    def sessions(self) -> pd.DataFrame:
        with self._connect() as con:
            return pd.read_sql_query("SELECT * FROM sessions ORDER BY id", con)

    def accuracy_by(self, column: str) -> pd.DataFrame:
        """Attempts, mean score and share correct grouped by topic / band / role / type."""
        if column not in {"topic", "band", "role", "type", "question_id"}:
            raise ValueError(f"cannot group by {column!r}")
        df = self.attempts()
        if df.empty:
            return pd.DataFrame(columns=[column, "attempts", "mean_score", "pct_correct"])
        g = df.groupby(column)
        out = pd.DataFrame(
            {
                "attempts": g.size(),
                "mean_score": g["score"].mean(),
                "pct_correct": g["outcome"].apply(lambda s: (s == "correct").mean()),
            }
        ).reset_index()
        return out.sort_values(column).reset_index(drop=True)

    def last_attempts(self) -> pd.DataFrame:
        """The most recent attempt for each question."""
        with self._connect() as con:
            df = pd.read_sql_query(
                """SELECT a.* FROM attempts a
                   JOIN (SELECT question_id, MAX(id) AS max_id FROM attempts
                         GROUP BY question_id) last ON a.id = last.max_id
                   ORDER BY a.question_id""",
                con,
            )
        return df

    def last_outcomes(self) -> dict[str, str]:
        df = self.last_attempts()
        return dict(zip(df["question_id"], df["outcome"], strict=True))

    def attempt_counts(self) -> dict[str, int]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT question_id, COUNT(*) FROM attempts GROUP BY question_id"
            ).fetchall()
        return {r[0]: int(r[1]) for r in rows}

    def missed_questions(self) -> pd.DataFrame:
        """Questions whose most recent attempt was incorrect or partial."""
        df = self.last_attempts()
        return df[df["outcome"].isin(["incorrect", "partial"])].reset_index(drop=True)
