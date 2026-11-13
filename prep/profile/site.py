"""Extract visible text from the portfolio website and match project pages to entities."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

GENERAL_PAGES = ("about", "experience", "skills", "projects")
# Pages linked from projects.html that are site navigation, not project details.
NON_DETAIL_PAGES = {
    "index",
    "about",
    "skills",
    "projects",
    "education",
    "experience",
    "contact",
    "resume",
}
STOPWORDS = {
    "a",
    "an",
    "and",
    "the",
    "of",
    "for",
    "with",
    "in",
    "on",
    "to",
    "by",
    "using",
    "from",
    "s",
    "stats",
    "project",
    "projects",
    "analysis",
    "details",
    "question",
    "llm",
}
MIN_KEYWORD_OVERLAP = 2
BLOCK_TAGS = [
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "dt",
    "dd",
    "tr",
    "div",
    "section",
    "article",
    "blockquote",
    "figcaption",
    "br",
    "table",
    "ul",
    "ol",
]


def _soup(path: Path) -> BeautifulSoup:
    return BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")


def visible_main_text(path: Path) -> str:
    """Visible text of <main> (or <body>), skipping nav, header, footer, scripts and styles."""
    soup = _soup(path)
    root = soup.find("main") or soup.body or soup
    for tag in root.find_all(
        [
            "script",
            "style",
            "noscript",
            "nav",
            "header",
            "footer",
            "svg",
            "template",
            "iframe",
            "button",
            "form",
        ]
    ):
        tag.decompose()
    for tag in root.select("[aria-live], [aria-hidden=true]"):  # slide counters, decorative bits
        tag.decompose()
    # Source line wraps are not paragraph breaks: collapse whitespace inside text nodes and
    # put line breaks only around block elements.
    for s in list(root.find_all(string=True)):
        s.replace_with(re.sub(r"\s+", " ", str(s)))
    for tag in root.find_all(BLOCK_TAGS):
        tag.insert_before("\n")
        tag.append("\n")
    lines = [" ".join(line.split()) for line in root.get_text("").splitlines()]
    return "\n".join(line for line in lines if line)


def page_heading(path: Path) -> str:
    soup = _soup(path)
    main = soup.find("main") or soup
    h1 = main.find("h1")
    if h1:
        return " ".join(h1.get_text(" ").split())
    return " ".join(soup.title.get_text(" ").split()) if soup.title else ""


def detail_pages(site: Path) -> list[Path]:
    """Local project detail pages linked from the main content of projects.html."""
    projects = site / "projects.html"
    if not projects.exists():
        log.warning("projects.html not found in %s", site)
        return []
    soup = _soup(projects)
    main = soup.find("main") or soup
    found: list[Path] = []
    for a in main.find_all("a", href=True):
        href = a["href"].split("#")[0].split("?")[0]
        if not href.endswith(".html") or "://" in href or href.startswith("/"):
            continue
        p = site / href
        if p.stem in NON_DETAIL_PAGES or p in found:
            continue
        if not p.exists():
            log.warning("projects.html links to missing page %s", href)
            continue
        found.append(p)
    return found


def project_cards(site: Path) -> list[str]:
    projects = site / "projects.html"
    if not projects.exists():
        return []
    soup = _soup(projects)
    return [" ".join(h.get_text(" ").split()) for h in soup.select("article h3")]


def keywords(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS and len(t) > 1}


def match_pages(
    entities: list[dict[str, Any]], pages: list[Path]
) -> tuple[dict[str, Path], list[Path], list[str]]:
    """Match each page to the one project entity sharing the most name keywords.

    Requires >= MIN_KEYWORD_OVERLAP shared keywords and a unique best match; anything else is
    reported as unmatched rather than guessed.
    Returns ({entity id: page}, unmatched pages, project entity ids without a page).
    """
    projects = [e for e in entities if e["type"] == "project"]
    ent_kw = {e["id"]: keywords(e["org"] or e["id"]) for e in projects}
    matched: dict[str, Path] = {}
    unmatched_pages: list[Path] = []
    for page in pages:
        page_kw = keywords(page.stem.replace("-", " ") + " " + page_heading(page))
        scores = sorted(((len(page_kw & kw), eid) for eid, kw in ent_kw.items()), reverse=True)
        best = scores[0] if scores else (0, None)
        tied = len(scores) > 1 and scores[1][0] == best[0]
        if best[0] < MIN_KEYWORD_OVERLAP or tied or best[1] in matched:
            unmatched_pages.append(page)
            continue
        matched[best[1]] = page
    no_page = [e["id"] for e in projects if e["id"] not in matched]
    return matched, unmatched_pages, no_page


def unmatched_cards(entities: list[dict[str, Any]], cards: list[str]) -> list[str]:
    """Project cards on projects.html that share too few keywords with any resume entity."""
    kws = [keywords(e["org"] or "") for e in entities]
    return [
        c
        for c in cards
        if max((len(keywords(c) & k) for k in kws), default=0) < MIN_KEYWORD_OVERLAP
    ]
