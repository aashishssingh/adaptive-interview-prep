"""Strip phone numbers and email addresses from text before anything is written publicly."""

from __future__ import annotations

import re
from typing import Any

EMAIL_RE = re.compile(
    r"(?:mailto:)?[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
)
# North American style numbers: (555) 010-0199, 555-010-0199, 555.010.0199, +1 555 010 0199,
# 5550100199. Separators are limited to space/dot/dash so figures like "839,613" or
# "0.010 to 0.022" never match.
PHONE_RE = re.compile(
    r"(?<![\w.])(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-]?)\d{3}[\s.-]?\d{4}(?![\w.]?\d)"
)


def find_pii(text: str) -> list[str]:
    return EMAIL_RE.findall(text) + PHONE_RE.findall(text)


def strip_pii(text: str) -> tuple[str, int]:
    """Return (cleaned text, number of redactions)."""
    text, n_email = EMAIL_RE.subn("", text)
    text, n_phone = PHONE_RE.subn("", text)
    if n_email or n_phone:
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\s+([,.;:)])", r"\1", text)
        text = re.sub(r"\(\s*\)", "", text).strip()
    return text, n_email + n_phone


def scrub(obj: Any) -> tuple[Any, int]:
    """Recursively strip PII from every string in a JSON-like structure (keys included)."""
    if isinstance(obj, str):
        return strip_pii(obj)
    if isinstance(obj, list):
        out, total = [], 0
        for item in obj:
            clean, n = scrub(item)
            out.append(clean)
            total += n
        return out, total
    if isinstance(obj, dict):
        out_d, total = {}, 0
        for k, v in obj.items():
            ck, nk = scrub(k)
            cv, nv = scrub(v)
            out_d[ck] = cv
            total += nk + nv
        return out_d, total
    return obj, 0
