"""Pydantic models for the structured JSON the model returns. Kept permissive (no length limits)
so the provider schema stays simple; the strict question schema is applied in Step C."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FactOut(BaseModel):
    statement: str = Field(description="One sentence using only details present in the sources.")
    source_bullets: list[int] = Field(description="Indices of the bullets this fact comes from.")
    uses_website_text: bool = Field(description="True if the fact uses the website page text.")
    substantive: bool = Field(
        description="True if the fact can support substantive technical interview questions."
    )


class FactsOut(BaseModel):
    facts: list[FactOut]


class GenQuestionOut(BaseModel):
    """Every field is required (nullable where it does not apply to the question type), so the
    model cannot silently drop answer_guidance or a rubric."""

    fact_ids: list[str]
    depth: Literal["explain", "justify", "challenge", "extend"] | None
    type: Literal["free_text", "short_answer", "multiple_choice"]
    role: Literal["ds", "mle", "both"]
    difficulty: int
    prompt: str
    tags: list[str]
    hints: list[str]
    follow_ups: list[str]
    est_minutes: int
    needs_user_input: bool
    answer_guidance: str | None
    model_answer: str | None
    rubric: list[str]
    options: list[str]
    answer_index: int | None
    answer: str | None
    explanation: str | None


class QuestionsOut(BaseModel):
    questions: list[GenQuestionOut]
