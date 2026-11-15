"""Step C: deterministic checks on generated questions."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from pydantic import ValidationError

from prep.bank.schema import DEPTH_DIFFICULTY, parse_question
from prep.generate.models import GenQuestionOut
from prep.generate.store import similar
from prep.meta import difficulty_band
from prep.profile.pii import strip_pii
from prep.profile.redact import name_patterns, redact_text

NEAR_DUPLICATE = 0.85
SMALL_NUMBERS = {str(i) for i in range(0, 11)}
_NUM_RE = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?%?")


def numbers_in(text: str) -> set[str]:
    out = set()
    for m in _NUM_RE.findall(text or ""):
        n = m.replace("$", "").replace(",", "").rstrip("%")
        n = n.rstrip(".")
        if n.endswith(".0"):
            n = n[:-2]
        out.add(n)
    return out


def ungrounded_numbers(q: dict[str, Any], source_text: str) -> list[str]:
    """Numbers in the answer-bearing fields that do not appear anywhere in the sources.

    Integers 0-10 are ignored (counts, list markers). For multiple choice only the correct
    option is checked strictly: distractors are meant to be wrong, and the explanation may
    mention them.
    """
    allowed = numbers_in(source_text)
    options = q.get("options") or []
    correct = (
        options[q["answer_index"]]
        if options and q.get("answer_index") is not None and 0 <= q["answer_index"] < len(options)
        else ""
    )
    strict = [
        q.get("model_answer") or "",
        q.get("answer") or "",
        " ".join(q.get("rubric") or []),
        correct,
        q["prompt"],
    ]
    found = numbers_in(" ".join(strict))
    found |= numbers_in(q.get("explanation") or "") - numbers_in(" ".join(options))
    return sorted(n for n in found - allowed if n not in SMALL_NUMBERS)


def clamp_difficulty(depth: str | None, difficulty: int) -> tuple[int, bool]:
    if depth is None:
        return max(1, min(10, difficulty)), False
    lo, hi = DEPTH_DIFFICULTY[depth]
    clamped = max(lo, min(hi, difficulty))
    return clamped, clamped != difficulty


def _scrub(value: Any, patterns: list) -> tuple[Any, int]:
    if isinstance(value, str):
        text, n_pii = strip_pii(value)
        text, n_names = redact_text(text, patterns)
        return text, n_pii + n_names
    if isinstance(value, list):
        pairs = [_scrub(v, patterns) for v in value]
        return [p[0] for p in pairs], sum(p[1] for p in pairs)
    return value, 0


def to_bank_dict(
    g: GenQuestionOut,
    *,
    entity_id: str,
    topic: str,
    meta: dict[str, Any],
    name_list: list[str],
) -> tuple[dict[str, Any], list[str]]:
    """Convert a model question into a bank-schema dict (id assigned later). Returns
    (question, notes)."""
    notes: list[str] = []
    difficulty, clamped = clamp_difficulty(g.depth, g.difficulty)
    if clamped:
        notes.append(f"difficulty {g.difficulty} clamped to {difficulty} for depth {g.depth}")
    q: dict[str, Any] = {
        "id": "proj-tmp-0001",
        "type": g.type,
        "role": g.role,
        "difficulty": difficulty,
        "topic": topic,
        "subtopic": entity_id,
        "tags": [t.strip().lower() for t in g.tags if t.strip()][:6] or [topic],
        "prompt": g.prompt.strip(),
        "hints": [h for h in g.hints if h.strip()][:2],
        "follow_ups": [f for f in g.follow_ups if f.strip()][:3],
        "est_minutes": max(1, min(30, int(g.est_minutes))),
        "source": "generated",
        "status": "draft",
        "entity_id": entity_id,
        "fact_ids": g.fact_ids,
        "depth": g.depth,
        "needs_user_input": bool(g.needs_user_input),
        **meta,
    }
    if g.answer_guidance:
        q["answer_guidance"] = g.answer_guidance.strip()
    if g.type == "free_text":
        if g.model_answer and not g.needs_user_input:
            q["model_answer"] = g.model_answer.strip()
        q["rubric"] = [r for r in g.rubric if r.strip()][:6]
    elif g.type == "multiple_choice":
        q.update(
            options=g.options,
            answer_index=g.answer_index,
            explanation=(g.explanation or "").strip(),
        )
    else:
        q.update(answer=(g.answer or "").strip(), explanation=(g.explanation or "").strip())
    if q["depth"] is None:
        del q["depth"]
    patterns = name_patterns(name_list)
    redactions = 0
    for key, value in list(q.items()):
        if isinstance(value, (str, list)) and key not in ("id", "fact_ids", "entity_id"):
            q[key], n = _scrub(value, patterns)
            redactions += n
    if redactions:
        notes.append(f"{redactions} name/contact detail(s) removed")
    return q, notes


def check_questions(
    generated: list[GenQuestionOut],
    *,
    entity_id: str,
    topic: str,
    fact_ids: set[str],
    source_text: str,
    meta: dict[str, Any],
    name_list: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Validate, normalize and de-duplicate. Returns (questions, report)."""
    report: dict[str, Any] = {
        "received": len(generated),
        "schema_errors": [],
        "unknown_fact_ids": [],
        "duplicates_dropped": 0,
        "difficulty_clamped": 0,
        "ungrounded": [],
    }
    kept: list[dict[str, Any]] = []
    for i, g in enumerate(generated):
        unknown = [f for f in g.fact_ids if f not in fact_ids]
        if unknown or not g.fact_ids:
            report["unknown_fact_ids"].append((i, unknown or ["(none)"]))
            continue
        q, notes = to_bank_dict(g, entity_id=entity_id, topic=topic, meta=meta, name_list=name_list)
        if any("clamped" in n for n in notes):
            report["difficulty_clamped"] += 1
        bad_numbers = ungrounded_numbers(q, source_text)
        if bad_numbers:
            notes.append(
                "Numbers not found in your profile: "
                + ", ".join(bad_numbers)
                + ". Check them before approving."
            )
            report["ungrounded"].append((i, bad_numbers))
        if notes:
            q["review_notes"] = notes
        try:
            parse_question(q)
        except ValidationError as e:
            report["schema_errors"].append((i, str(e).splitlines()[0:3]))
            continue
        if any(similar(q["prompt"], k["prompt"]) > NEAR_DUPLICATE for k in kept):
            report["duplicates_dropped"] += 1
            continue
        kept.append(q)
    report["kept"] = len(kept)
    report["by_depth"] = dict(Counter(q.get("depth", "behavioral") for q in kept))
    report["by_role"] = dict(Counter(q["role"] for q in kept))
    report["by_band"] = dict(Counter(difficulty_band(q["difficulty"]) for q in kept))
    report["needs_user_input"] = sum(1 for q in kept if q["needs_user_input"])
    return kept, report
