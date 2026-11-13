"""Read the resume source YAML (anchors and ``<<:`` merge keys) into flat records."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

ENTITY_TYPES = (
    "experience",
    "research",
    "project",
    "education",
    "service",
    "additional_experience",
)

SECTION_TYPES: dict[str, str] = {
    "EDUCATION": "education",
    "EXPERIENCE": "experience",
    "PROFESSIONAL EXPERIENCE": "experience",
    "RESEARCH EXPERIENCE": "research",
    "PROJECTS": "project",
    "ADDITIONAL EXPERIENCE": "additional_experience",
    "TEACHING, MENTORING AND SERVICE": "service",
    "SERVICE": "service",
}


@dataclass
class EntryRecord:
    document: str
    type: str
    org: str
    title: str | None
    date: str | None
    loc: str | None
    bullets: list[str] = field(default_factory=list)


@dataclass
class ResumeData:
    documents: list[str]
    entries: list[EntryRecord]
    skills: list[tuple[str, str, str]]  # (document, label, comma-separated items)
    coursework: list[tuple[str, str, str]]
    extras: list[dict[str, Any]]  # {document, title, items | text}
    skipped_archived: list[str]


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or not isinstance(data.get("documents"), dict):
        raise ValueError(f"{path}: expected a top-level 'documents:' mapping")
    return data


def classify_section(title: str) -> str | None:
    return SECTION_TYPES.get(" ".join(title.upper().split()))


def split_items(s: str) -> list[str]:
    """Split a comma-separated skills string, ignoring commas inside parentheses."""
    items, depth, buf = [], 0, []
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            items.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    items.append("".join(buf))
    return [" ".join(i.split()) for i in items if i.strip()]


def _str_or_none(v: Any) -> str | None:
    return None if v is None else " ".join(str(v).split())


def extract(data: dict[str, Any]) -> ResumeData:
    """Walk every non-archived document. ``header`` blocks are never read."""
    out = ResumeData([], [], [], [], [], [])
    for doc_name, doc in data["documents"].items():
        if not isinstance(doc, dict):
            continue
        if doc.get("archived"):
            out.skipped_archived.append(doc_name)
            continue
        out.documents.append(doc_name)
        for section in doc.get("sections") or []:
            title = str(section.get("title", "")).strip()
            if "entries" in section:
                etype = classify_section(title)
                if etype is None:
                    log.warning("%s: unknown entry section %r skipped", doc_name, title)
                    continue
                for entry in section["entries"] or []:
                    out.entries.append(
                        EntryRecord(
                            document=doc_name,
                            type=etype,
                            org=_str_or_none(entry.get("org")) or "",
                            title=_str_or_none(entry.get("title")),
                            date=_str_or_none(entry.get("date")),
                            loc=_str_or_none(entry.get("loc")),
                            bullets=[str(b) for b in entry.get("bullets") or []],
                        )
                    )
            elif "skills" in section:
                bucket = out.skills if title.upper() == "SKILLS" else out.coursework
                for label, items in section["skills"] or []:
                    bucket.append((doc_name, str(label), str(items)))
            elif "items" in section:
                out.extras.append(
                    {
                        "document": doc_name,
                        "title": title,
                        "items": [str(i) for i in section["items"]],
                    }
                )
            elif "text" in section:
                out.extras.append(
                    {"document": doc_name, "title": title, "text": str(section["text"])}
                )
    return out


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
