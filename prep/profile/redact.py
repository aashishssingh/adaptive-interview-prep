"""Remove other people's names (teammates, advisors, co-authors) from public output.

The names to remove live in a private, gitignored file (default
``data/local/redact_names.txt``) so the list itself is never published. One name per line;
``#`` starts a comment. Two forms are accepted:

- ``First Last``: matches "First Last" and the citation form "Last, F."
- ``Last, F.``:  matches "Last, F." and "F<anything> Last" (e.g. "Nora Last")

Matched names become ``[name]``; adjacent ones ("[name] and [name]") collapse to ``[names]``.
In citations ("Authors (YEAR...). Title."), a redacted author list is rewritten to the
remaining authors plus "et al.".
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

PLACEHOLDER = "[name]"
_CITATION_AUTHOR_RE = re.compile(r"[A-Z][\w'-]+,\s*(?:[A-Z]\.\s*)+")
_CITATION_SPLIT_RE = re.compile(r"^(?P<authors>.+?)\s(?P<rest>\(\d{4}[^)]*\)\..*)$", re.S)
_COLLAPSE_RE = re.compile(r"\[names?\](?:(?:,\s*(?:and\s+)?|\s+and\s+)\[names?\])+")


def load_names(path: Path | None) -> list[str]:
    if path is None or not path.exists():
        return []
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.append(line)
    return names


def name_patterns(names: list[str]) -> list[re.Pattern[str]]:
    pats: list[str] = []
    for name in names:
        if "," in name:  # "Last, F."
            last, initial = (p.strip() for p in name.split(",", 1))
            init = initial.rstrip(".")[:1]
            pats.append(rf"\b{re.escape(last)},\s*{re.escape(init)}\.")
            pats.append(rf"\b{re.escape(init)}[\w'-]*\.?\s+{re.escape(last)}\b")
        else:  # "First [Middle] Last"
            parts = name.split()
            first, last = parts[0], parts[-1]
            pats.append(r"\b" + r"\s+".join(re.escape(p) for p in parts) + r"\b")
            if len(parts) > 1:
                pats.append(rf"\b{re.escape(last)},\s*{re.escape(first[0])}\.")
    # Longest first so "First Last" wins over shorter variants.
    return [re.compile(p) for p in sorted(set(pats), key=len, reverse=True)]


def _fix_citation(text: str) -> str:
    m = _CITATION_SPLIT_RE.match(text)
    if not m or PLACEHOLDER[:-1] not in m.group("authors"):
        return text
    kept = [a.strip().rstrip(",") for a in _CITATION_AUTHOR_RE.findall(m.group("authors"))]
    authors = (", ".join(kept) + " et al.") if kept else "Co-authored"
    return f"{authors} {m.group('rest')}"


def redact_text(text: str, patterns: list[re.Pattern[str]]) -> tuple[str, int]:
    total = 0
    for pat in patterns:
        text, n = pat.subn(PLACEHOLDER, text)
        total += n
    if total:
        text = _COLLAPSE_RE.sub("[names]", text)
        text = _fix_citation(text)
    return text, total


def redact(obj: Any, patterns: list[re.Pattern[str]]) -> tuple[Any, int]:
    """Recursively redact names in every string of a JSON-like structure."""
    if not patterns:
        return obj, 0
    if isinstance(obj, str):
        return redact_text(obj, patterns)
    if isinstance(obj, list):
        pairs = [redact(x, patterns) for x in obj]
        return [p[0] for p in pairs], sum(p[1] for p in pairs)
    if isinstance(obj, dict):
        out, total = {}, 0
        for k, v in obj.items():
            cv, n = redact(v, patterns)
            out[k] = cv
            total += n
        return out, total
    return obj, 0


def surviving_names(text: str, patterns: list[re.Pattern[str]]) -> list[str]:
    return [m.group(0) for p in patterns for m in p.finditer(text)]
