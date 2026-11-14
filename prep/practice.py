"""Pure practice-session logic used by the UI: track filters and session summaries."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import pandas as pd

from prep.bank.schema import Question

TRACKS: dict[str, tuple[str, ...]] = {
    "Data Scientist": ("ds", "both"),
    "ML/AI Engineer": ("mle", "both"),
    "All": ("ds", "mle", "both"),
}
MODES = ("Practice", "Flashcards")
FLASHCARD_TYPES = ("short_answer", "multiple_choice")


def roles_for(track: str, only_role_specific: bool = False) -> set[str]:
    """Roles shown for a track; "Only role-specific questions" drops "both"."""
    if track not in TRACKS:
        raise ValueError(f"unknown track {track!r}")
    roles = set(TRACKS[track])
    if only_role_specific:
        roles.discard("both")
    return roles


def matching_questions(
    questions: Iterable[Question],
    track: str = "All",
    only_role_specific: bool = False,
    topics: Sequence[str] | None = None,
    difficulty: tuple[int, int] = (1, 10),
    types: Sequence[str] | None = None,
    mode: str = "Practice",
) -> list[Question]:
    roles = roles_for(track, only_role_specific)
    allowed_types = set(types) if types else None
    if mode == "Flashcards":
        allowed_types = (allowed_types or set(FLASHCARD_TYPES)) & set(FLASHCARD_TYPES)
    lo, hi = difficulty
    return [
        q
        for q in questions
        if q.role in roles
        and (not topics or q.topic in topics)
        and lo <= q.difficulty <= hi
        and (allowed_types is None or q.type in allowed_types)
    ]


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """results: dicts with question_id, topic, role, score, outcome, duration_sec."""
    if not results:
        return {
            "n": 0,
            "total_score": 0.0,
            "mean_score": 0.0,
            "total_time_sec": 0.0,
            "by_topic": pd.DataFrame(),
            "by_role": pd.DataFrame(),
            "outcomes": {},
        }
    df = pd.DataFrame(results)

    def breakdown(col: str) -> pd.DataFrame:
        g = df.groupby(col)
        return pd.DataFrame(
            {
                "questions": g.size(),
                "score": g["score"].sum().round(2),
                "mean_score": g["score"].mean().round(2),
                "correct": g["outcome"].apply(lambda s: int((s == "correct").sum())),
            }
        ).reset_index()

    return {
        "n": len(df),
        "total_score": float(df["score"].sum()),
        "mean_score": float(df["score"].mean()),
        "total_time_sec": float(df["duration_sec"].sum()),
        "by_topic": breakdown("topic"),
        "by_role": breakdown("role"),
        "outcomes": df["outcome"].value_counts().to_dict(),
    }


def format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
