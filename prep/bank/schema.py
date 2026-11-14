"""Question schema for the bank (data/questions/<topic>.yaml).

Every question shares the base fields; ``type`` selects the type-specific fields. Role and
difficulty follow prep/meta.py and the role rule in CLAUDE.md (role = what the question tests).
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    TypeAdapter,
    field_validator,
    model_validator,
)

from prep.meta import difficulty_band, validate_difficulty, validate_role

TOPIC_PATTERN = r"^[a-z][a-z0-9_]*$"
ID_PATTERN = r"^[a-z][a-z0-9_]*-\d{4}$"
IDENT_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"

QUESTION_TYPES = ("free_text", "multiple_choice", "short_answer", "coding_python", "coding_sql")

NonEmpty = Annotated[str, Field(min_length=1)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class _QuestionBase(_Strict):
    id: Annotated[str, Field(pattern=ID_PATTERN)]
    role: str
    difficulty: int
    topic: Annotated[str, Field(pattern=TOPIC_PATTERN)]
    subtopic: NonEmpty
    tags: Annotated[list[NonEmpty], Field(min_length=1)]
    prompt: Annotated[str, Field(min_length=10)]
    hints: Annotated[list[NonEmpty], Field(max_length=2)] = []
    follow_ups: Annotated[list[NonEmpty], Field(max_length=3)] = []
    est_minutes: Annotated[StrictInt, Field(ge=1, le=120)]
    # "generated" is reserved for Phase 4 (LLM-generated questions in data/generated/).
    source: Literal["authored", "generated"] = "authored"

    @field_validator("role", mode="before")
    @classmethod
    def _check_role(cls, v: Any) -> str:
        return validate_role(v)

    @field_validator("difficulty", mode="before")
    @classmethod
    def _check_difficulty(cls, v: Any) -> int:
        return validate_difficulty(v)

    @model_validator(mode="after")
    def _id_matches_topic(self):
        prefix = self.id.rsplit("-", 1)[0]
        if prefix != self.topic:
            raise ValueError(f"id prefix {prefix!r} must equal topic {self.topic!r}")
        return self

    @property
    def band(self) -> str:
        return difficulty_band(self.difficulty)


class FreeText(_QuestionBase):
    type: Literal["free_text"]
    model_answer: Annotated[str, Field(min_length=20)]
    rubric: Annotated[list[NonEmpty], Field(min_length=3, max_length=6)]


class MultipleChoice(_QuestionBase):
    type: Literal["multiple_choice"]
    options: Annotated[list[NonEmpty], Field(min_length=4, max_length=4)]
    answer_index: Annotated[StrictInt, Field(ge=0, le=3)]
    explanation: Annotated[str, Field(min_length=20)]

    @field_validator("options")
    @classmethod
    def _distinct(cls, v: list[str]) -> list[str]:
        if len({o.lower() for o in v}) != len(v):
            raise ValueError("options must be distinct")
        return v


class ShortAnswer(_QuestionBase):
    type: Literal["short_answer"]
    answer: Annotated[str, Field(min_length=1, max_length=200)]
    explanation: Annotated[str, Field(min_length=20)]

    @field_validator("answer")
    @classmethod
    def _one_line(cls, v: str) -> str:
        if "\n" in v:
            raise ValueError("answer must be a single line")
        return v


class TestCase(_Strict):
    """One call: function(*args, **kwargs) must equal ``expected``.

    Special values: an arg ``{"__df__": {col: [...]}}`` becomes a pandas DataFrame; an expected
    ``{"__raises__": "ValueError"}`` means the call must raise that exception type.
    """

    __test__ = False  # not a pytest test class

    args: list[Any] = []
    kwargs: dict[str, Any] = {}
    expected: Any = Field(...)


class CodingPython(_QuestionBase):
    type: Literal["coding_python"]
    function_name: Annotated[str, Field(pattern=IDENT_PATTERN)]
    starter_code: Annotated[str, Field(min_length=1)]
    reference_solution: Annotated[str, Field(min_length=1)]
    test_cases: Annotated[list[TestCase], Field(min_length=4)]
    explanation: Annotated[str, Field(min_length=20)]


class CodingSQL(_QuestionBase):
    type: Literal["coding_sql"]
    dataset: Annotated[str, Field(pattern=IDENT_PATTERN)]
    reference_query: Annotated[str, Field(min_length=1)]
    order_matters: StrictBool
    explanation: Annotated[str, Field(min_length=20)]


Question = Annotated[
    FreeText | MultipleChoice | ShortAnswer | CodingPython | CodingSQL,
    Field(discriminator="type"),
]
QUESTION_ADAPTER: TypeAdapter[Question] = TypeAdapter(Question)


def parse_question(data: Any) -> Question:
    """Validate one question dict (raises pydantic.ValidationError)."""
    return QUESTION_ADAPTER.validate_python(data)


def question_hash(q: Any) -> str:
    """Stable hash of a question's full content, so edits to a question are detectable."""
    blob = json.dumps(q.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
