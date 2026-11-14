"""Load the question bank from YAML and filter it."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from prep.bank.schema import QUESTION_TYPES, Question, parse_question
from prep.config import PROJECT_ROOT
from prep.meta import validate_role

QUESTIONS_DIR = PROJECT_ROOT / "data" / "questions"
DATASETS_DIR = QUESTIONS_DIR / "datasets"


class BankError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"{len(errors)} question bank error(s):\n" + "\n".join(errors))


def _format_validation_error(e: ValidationError) -> str:
    parts = []
    for err in e.errors():
        loc_parts = list(err["loc"])
        if loc_parts and loc_parts[0] in QUESTION_TYPES:  # drop the discriminated-union tag
            loc_parts = loc_parts[1:]
        loc = ".".join(str(x) for x in loc_parts)
        parts.append(f"{loc}: {err['msg']}" if loc else err["msg"])
    return "; ".join(parts)


def load_file(path: Path) -> tuple[list[Question], list[str]]:
    """Parse one topic file. Returns (valid questions, error messages)."""
    errors: list[str] = []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return [], [f"{path.name}: invalid YAML: {e}"]
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        return [], [f"{path.name}: expected a top-level 'questions:' list"]

    questions: list[Question] = []
    for i, item in enumerate(data["questions"]):
        qid = item.get("id", f"#{i}") if isinstance(item, dict) else f"#{i}"
        try:
            q = parse_question(item)
        except ValidationError as e:
            errors.append(f"{path.name}: {qid}: {_format_validation_error(e)}")
            continue
        if q.topic != path.stem:
            errors.append(f"{path.name}: {q.id}: topic {q.topic!r} does not match file name")
            continue
        questions.append(q)
    return questions, errors


def question_files(directory: Path = QUESTIONS_DIR) -> list[Path]:
    return sorted(p for p in directory.glob("*.yaml") if not p.name.startswith("."))


def load_bank_with_errors(directory: Path = QUESTIONS_DIR) -> tuple[list[Question], list[str]]:
    questions: list[Question] = []
    errors: list[str] = []
    seen: dict[str, str] = {}
    for path in question_files(directory):
        qs, errs = load_file(path)
        errors.extend(errs)
        for q in qs:
            if q.id in seen:
                errors.append(f"{path.name}: duplicate id {q.id} (also in {seen[q.id]})")
                continue
            seen[q.id] = path.name
            questions.append(q)
    return questions, errors


def load_bank(directory: Path = QUESTIONS_DIR) -> list[Question]:
    """Load every topic file. Raises BankError if any question is invalid or duplicated."""
    questions, errors = load_bank_with_errors(directory)
    if errors:
        raise BankError(errors)
    return questions


def _as_set(v: str | Iterable[str] | None) -> set[str] | None:
    if v is None:
        return None
    return {v} if isinstance(v, str) else set(v)


def filter_questions(
    questions: Iterable[Question],
    role: str | None = None,
    topic: str | Iterable[str] | None = None,
    difficulty: tuple[int, int] | None = None,
    type: str | Iterable[str] | None = None,  # noqa: A002 - mirrors the schema field
    include_both: bool = True,
) -> list[Question]:
    """Filter questions.

    role: "ds" or "mle" also returns "both" questions unless include_both=False;
          role="both" returns only "both" questions.
    difficulty: inclusive (low, high) range, e.g. (4, 6).
    """
    roles: set[str] | None = None
    if role is not None:
        validate_role(role)
        roles = {role, "both"} if include_both and role != "both" else {role}
    topics, types = _as_set(topic), _as_set(type)
    if difficulty is not None:
        lo, hi = difficulty
        if lo > hi:
            raise ValueError(f"difficulty range low {lo} > high {hi}")

    out = []
    for q in questions:
        if roles is not None and q.role not in roles:
            continue
        if topics is not None and q.topic not in topics:
            continue
        if types is not None and q.type not in types:
            continue
        if difficulty is not None and not (difficulty[0] <= q.difficulty <= difficulty[1]):
            continue
        out.append(q)
    return out


def by_id(questions: Iterable[Question]) -> dict[str, Any]:
    return {q.id: q for q in questions}
