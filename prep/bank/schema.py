"""Question schema for the bank (data/questions/<topic>.yaml) and for generated project
questions (data/generated/projects/<entity_id>.yaml).

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
GENERATED_ID_PATTERN = r"^proj-[a-z0-9]+(?:-[a-z0-9]+)*-\d{4}$"
GENERATED_TOPICS = ("projects", "behavioral")
STATUSES = ("draft", "approved", "rejected", "retired")
DEPTHS = ("explain", "justify", "challenge", "extend")
DEPTH_DIFFICULTY = {"explain": (2, 4), "justify": (4, 6), "challenge": (6, 9), "extend": (6, 10)}
IDENT_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"

QUESTION_TYPES = ("free_text", "multiple_choice", "short_answer", "coding_python", "coding_sql")

NonEmpty = Annotated[str, Field(min_length=1)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class _QuestionBase(_Strict):
    id: str
    role: str
    difficulty: int
    topic: Annotated[str, Field(pattern=TOPIC_PATTERN)]
    subtopic: NonEmpty
    tags: Annotated[list[NonEmpty], Field(min_length=1)]
    prompt: Annotated[str, Field(min_length=10)]
    hints: Annotated[list[NonEmpty], Field(max_length=2)] = []
    follow_ups: Annotated[list[NonEmpty], Field(max_length=3)] = []
    est_minutes: Annotated[StrictInt, Field(ge=1, le=120)]
    source: Literal["authored", "generated"] = "authored"
    # Review status. Authored questions are approved; generated ones start as draft.
    status: Literal["draft", "approved", "rejected", "retired"] = "approved"
    # Generated-question metadata (all optional, so authored files are unchanged).
    entity_id: str | None = None
    fact_ids: list[NonEmpty] = []
    depth: Literal["explain", "justify", "challenge", "extend"] | None = None
    needs_user_input: StrictBool = False
    answer_guidance: str | None = None
    generated_by: str | None = None
    generated_at: str | None = None
    profile_hash: str | None = None
    review_notes: list[NonEmpty] = []

    @field_validator("role", mode="before")
    @classmethod
    def _check_role(cls, v: Any) -> str:
        return validate_role(v)

    @field_validator("difficulty", mode="before")
    @classmethod
    def _check_difficulty(cls, v: Any) -> int:
        return validate_difficulty(v)

    @model_validator(mode="after")
    def _check_id_and_source(self):
        import re

        if self.source == "authored":
            if not re.match(ID_PATTERN, self.id):
                raise ValueError(f"id {self.id!r} must look like '<topic>-0001'")
            prefix = self.id.rsplit("-", 1)[0]
            if prefix != self.topic:
                raise ValueError(f"id prefix {prefix!r} must equal topic {self.topic!r}")
        else:
            if not re.match(GENERATED_ID_PATTERN, self.id):
                raise ValueError(f"generated id {self.id!r} must look like 'proj-<slug>-0001'")
            if self.topic not in GENERATED_TOPICS:
                raise ValueError(f"generated topic must be one of {GENERATED_TOPICS}")
            if not self.entity_id:
                raise ValueError("generated questions need entity_id")
        if self.needs_user_input and not (self.answer_guidance or "").strip():
            raise ValueError("needs_user_input questions need answer_guidance")
        return self

    @property
    def band(self) -> str:
        return difficulty_band(self.difficulty)


class FreeText(_QuestionBase):
    type: Literal["free_text"]
    # May be omitted only when needs_user_input is set: then answer_guidance replaces it, so no
    # answer is fabricated from information the profile does not contain.
    model_answer: Annotated[str, Field(min_length=20)] | None = None
    rubric: Annotated[list[NonEmpty], Field(min_length=3, max_length=6)]

    @model_validator(mode="after")
    def _answer_or_guidance(self):
        if self.model_answer is None and not self.needs_user_input:
            raise ValueError("model_answer is required unless needs_user_input is true")
        return self


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


HASH_EXCLUDE = {"status", "review_notes"}


def question_hash(q: Any) -> str:
    """Stable hash of a question's content, so edits are detectable. Review status is not
    content, and default-valued fields are skipped so adding optional schema fields does not
    change existing hashes."""
    data = q.model_dump(mode="json", exclude=HASH_EXCLUDE, exclude_defaults=True)
    blob = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
