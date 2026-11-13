"""Merge resume entries across documents into unique entities with de-duplicated bullets."""

from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
from typing import Any

from prep.meta import combine_roles, role_from_sources
from prep.profile.resume import ENTITY_TYPES, EntryRecord, ResumeData, slugify, split_items

NEAR_DUP_RATIO = 0.9


def normalize(text: str) -> str:
    return " ".join(text.split())


def entity_key(org: str, title: str | None) -> str:
    """Slug of org, plus title when the entry has one (experience, education, research...)."""
    return slugify(org) + (f"--{slugify(title)}" if title else "")


def _similar(a: str, b: str) -> bool:
    if a.lower() == b.lower():
        return True
    return SequenceMatcher(None, a.lower(), b.lower(), autojunk=False).ratio() > NEAR_DUP_RATIO


def dedupe_bullets(pairs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """``pairs`` is [(bullet text, source document)] in first-seen order.

    Exact and near-exact duplicates (difflib ratio > 0.9) are merged: the longest text is
    kept and sources are unioned. Each result gets a role from its sources.
    """
    clusters: list[dict[str, Any]] = []
    for raw, src in pairs:
        text = normalize(raw)
        if not text:
            continue
        for c in clusters:
            if any(_similar(text, v) for v in c["variants"]):
                c["variants"].append(text)
                if src not in c["sources"]:
                    c["sources"].append(src)
                if len(text) > len(c["text"]):
                    c["text"] = text
                break
        else:
            clusters.append({"text": text, "variants": [text], "sources": [src]})
    return [
        {"text": c["text"], "sources": c["sources"], "role": role_from_sources(c["sources"])}
        for c in clusters
    ]


def _majority(values: list[str | None], order: tuple[str, ...] | None = None) -> str | None:
    vals = [v for v in values if v]
    if not vals:
        return None
    counts = Counter(vals)
    first_seen = {v: i for i, v in reversed(list(enumerate(vals)))}

    def rank(v: str) -> tuple:
        tie = order.index(v) if order and v in order else first_seen[v]
        return (-counts[v], tie)

    return min(counts, key=rank)


def merge_entities(
    records: list[EntryRecord], aliases: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    aliases = aliases or {}
    groups: dict[str, list[EntryRecord]] = {}
    for r in records:
        key = entity_key(r.org, r.title)
        key = aliases.get(key, key)
        groups.setdefault(key, []).append(r)

    entities = []
    for key, recs in groups.items():
        bullets = dedupe_bullets([(b, r.document) for r in recs for b in r.bullets])
        sources = list(dict.fromkeys(r.document for r in recs))
        etype = _majority([r.type for r in recs], ENTITY_TYPES)
        entities.append(
            {
                "id": key,
                "type": etype,
                "org": _majority([r.org for r in recs]),
                "title": _majority([r.title for r in recs]),
                "date": _majority([r.date for r in recs]),
                "loc": _majority([r.loc for r in recs]),
                "role": combine_roles([b["role"] for b in bullets]),
                "sources": sources,
                "bullets": bullets,
            }
        )
    entities.sort(key=lambda e: ENTITY_TYPES.index(e["type"]))  # stable: keeps first-seen order
    return entities


def merge_skill_rows(rows: list[tuple[str, str, str]]) -> dict[str, list[str]]:
    """Union of items grouped by label, de-duplicated case-insensitively, first-seen order."""
    grouped: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for _doc, label, items in rows:
        label = normalize(label)
        bucket = grouped.setdefault(label, [])
        seen_l = seen.setdefault(label, set())
        for item in split_items(items):
            if item.lower() not in seen_l:
                seen_l.add(item.lower())
                bucket.append(item)
    return grouped


def merge_extras(extras: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for x in extras:
        m = merged.setdefault(x["title"], {"title": x["title"], "sources": []})
        m["sources"].append(x["document"])
        if "items" in x:
            items = m.setdefault("items", [])
            items.extend(normalize(i) for i in x["items"] if normalize(i) not in items)
        else:
            m.setdefault("text", normalize(x["text"]))
    return list(merged.values())


def build_profile_core(data: ResumeData, aliases: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "documents": data.documents,
        "entities": merge_entities(data.entries, aliases),
        "skills": merge_skill_rows(data.skills),
        "coursework": merge_skill_rows(data.coursework),
        "extras": merge_extras(data.extras),
    }
