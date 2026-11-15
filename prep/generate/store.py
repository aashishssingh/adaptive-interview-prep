"""Read and write generated question files; merge regenerated questions and retire old ones.

Question files are never deleted: questions that are no longer produced become "retired", so
practice history keeps resolving.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import yaml

SIMILAR_PROMPT = 0.85
VOLATILE = {"id", "status", "generated_by", "generated_at", "profile_hash", "review_notes"}


def load_entity_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"entity_id": path.stem, "questions": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.setdefault("entity_id", path.stem)
    data.setdefault("questions", [])
    return data


def save_entity_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def similar(a: str, b: str) -> float:
    return SequenceMatcher(
        None, " ".join(a.lower().split()), " ".join(b.lower().split()), autojunk=False
    ).ratio()


def _content(q: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in q.items() if k not in VOLATILE}


def next_number(questions: list[dict[str, Any]], slug: str) -> int:
    nums = [
        int(q["id"].rsplit("-", 1)[1])
        for q in questions
        if q.get("id", "").startswith(f"proj-{slug}-")
    ]
    return max(nums, default=0) + 1


def merge_questions(
    old: list[dict[str, Any]], new: list[dict[str, Any]], slug: str
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Merge a regenerated set into the existing file.

    - A new question whose prompt matches an existing one (ratio > 0.85) keeps the old id. If its
      content is unchanged the old entry (and its review status) is kept; if it changed, the new
      content replaces it and status resets to draft for re-review.
    - Existing questions with no match are retired (kept in the file).
    - Unmatched new questions get fresh ids.
    """
    merged = [dict(q) for q in old]
    matched_old: set[int] = set()
    stats = {"kept": 0, "updated": 0, "added": 0, "retired": 0}
    counter = next_number(old, slug)
    for q in new:
        best, best_score = None, SIMILAR_PROMPT
        for i, o in enumerate(merged):
            if i in matched_old:
                continue
            score = similar(q["prompt"], o["prompt"])
            if score > best_score:
                best, best_score = i, score
        if best is not None:
            matched_old.add(best)
            o = merged[best]
            if _content(o) == _content(q) and o.get("status") != "retired":
                stats["kept"] += 1
                continue
            merged[best] = {**q, "id": o["id"], "status": "draft"}
            stats["updated"] += 1
        else:
            merged.append({**q, "id": f"proj-{slug}-{counter:04d}", "status": "draft"})
            matched_old.add(len(merged) - 1)
            counter += 1
            stats["added"] += 1
    for i, o in enumerate(merged):
        if i not in matched_old and i < len(old) and o.get("status") != "retired":
            o["status"] = "retired"
            stats["retired"] += 1
    return merged, stats


def retire_all(path: Path) -> int:
    data = load_entity_file(path)
    n = 0
    for q in data["questions"]:
        if q.get("status") != "retired":
            q["status"] = "retired"
            n += 1
    if n:
        save_entity_file(path, data)
    return n


def set_status(path: Path, question_ids: list[str] | str, status: str) -> int:
    """Write review decisions back to the YAML file. Returns how many questions changed."""
    if status not in ("draft", "approved", "rejected", "retired"):
        raise ValueError(f"bad status {status!r}")
    ids = {question_ids} if isinstance(question_ids, str) else set(question_ids)
    data = load_entity_file(path)
    n = 0
    for q in data["questions"]:
        if q.get("id") in ids and q.get("status") != status:
            q["status"] = status
            n += 1
    if n:
        save_entity_file(path, data)
    return n
