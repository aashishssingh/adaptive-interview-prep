"""Build data/profile.json from the resume source YAML and the portfolio website.

Usage:  python -m prep.profile.sync
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from prep.config import PROJECT_ROOT, load_settings
from prep.profile import changes as ch
from prep.profile import site as site_mod
from prep.profile.merge import build_profile_core
from prep.profile.pii import find_pii, scrub
from prep.profile.resume import extract, load_yaml

log = logging.getLogger("prep.profile.sync")

SCHEMA_VERSION = 1
DEFAULT_OUT = PROJECT_ROOT / "data" / "profile.json"
DEFAULT_LOCAL = PROJECT_ROOT / "data" / "local"
DEFAULT_ALIASES = PROJECT_ROOT / "data" / "profile_aliases.yaml"


class SourceMissingError(RuntimeError):
    pass


@dataclass
class SyncReport:
    profile: dict[str, Any]
    changes: dict[str, Any]
    snapshot: Path | None
    redactions: int
    skipped_archived: list[str]
    unmatched_pages: list[str] = field(default_factory=list)
    projects_without_page: list[str] = field(default_factory=list)
    site_cards_without_entity: list[str] = field(default_factory=list)


def check_sources(resume_path: Path, site_path: Path) -> None:
    if not resume_path.is_file():
        raise SourceMissingError(
            f"Resume content file not found: {resume_path}\n"
            "Set RESUME_CONTENT_PATH in .env to your content.yaml (see .env.example)."
        )
    if not site_path.is_dir():
        raise SourceMissingError(
            f"Website folder not found: {site_path}\n"
            "Set SITE_PATH in .env to your portfolio website folder (see .env.example)."
        )


def load_aliases(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in (data.get("aliases") or {}).items()}


def build_profile(
    resume_path: Path, site_path: Path, aliases_path: Path | None = None
) -> tuple[dict[str, Any], SyncReport]:
    check_sources(resume_path, site_path)
    data = extract(load_yaml(resume_path))
    core = build_profile_core(data, load_aliases(aliases_path))

    pages = site_mod.detail_pages(site_path)
    matched, unmatched_pages, no_page = site_mod.match_pages(core["entities"], pages)
    for ent in core["entities"]:
        page = matched.get(ent["id"])
        ent["website"] = (
            {
                "page": page.name,
                "heading": site_mod.page_heading(page),
                "text": site_mod.visible_main_text(page),
            }
            if page
            else None
        )

    site_pages = {}
    for name in site_mod.GENERAL_PAGES:
        p = site_path / f"{name}.html"
        if p.exists():
            site_pages[name] = site_mod.visible_main_text(p)
        else:
            log.warning("site page %s.html not found", name)

    profile: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "documents": core["documents"],
        "entities": core["entities"],
        "skills": core["skills"],
        "coursework": core["coursework"],
        "extras": core["extras"],
        "site_pages": site_pages,
    }
    profile, redactions = scrub(profile)
    for ent in profile["entities"]:
        ent["content_hash"] = ch.content_hash(ent)

    leftover = find_pii(json.dumps(profile, ensure_ascii=False))
    if leftover:  # defensive: scrub() should make this impossible
        raise RuntimeError(f"PII survived scrubbing ({len(leftover)} matches); not writing")

    report = SyncReport(
        profile=profile,
        changes={},
        snapshot=None,
        redactions=redactions,
        skipped_archived=data.skipped_archived,
        unmatched_pages=[p.name for p in unmatched_pages],
        projects_without_page=no_page,
        site_cards_without_entity=site_mod.unmatched_cards(
            profile["entities"], site_mod.project_cards(site_path)
        ),
    )
    return profile, report


def run_sync(
    resume_path: Path,
    site_path: Path,
    out_path: Path = DEFAULT_OUT,
    local_dir: Path = DEFAULT_LOCAL,
    aliases_path: Path | None = DEFAULT_ALIASES,
    now: datetime | None = None,
) -> SyncReport:
    now = now or datetime.now()
    profile, report = build_profile(resume_path, site_path, aliases_path)
    old = ch.load_profile(out_path)
    changes = ch.diff_profiles(old, profile)
    new_text = json.dumps(profile, indent=2, ensure_ascii=False) + "\n"

    if old is not None and out_path.read_text(encoding="utf-8") != new_text:
        report.snapshot = ch.snapshot(out_path, local_dir / "snapshots", now)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(new_text, encoding="utf-8")

    changes_record = {
        "generated_at": now.isoformat(timespec="seconds"),
        **changes,
        "snapshot": str(report.snapshot) if report.snapshot else None,
    }
    local_dir.mkdir(parents=True, exist_ok=True)
    (local_dir / "profile_changes.json").write_text(
        json.dumps(changes_record, indent=2) + "\n", encoding="utf-8"
    )
    report.changes = changes
    return report


def format_report(report: SyncReport) -> str:
    p = report.profile
    lines = [ch.format_summary(report.changes, len(p["entities"]))]
    if report.snapshot:
        lines.append(f"Previous profile saved to {report.snapshot}")
    lines += [
        "",
        f"Documents used: {', '.join(p['documents'])}",
        f"Archived documents skipped: {', '.join(report.skipped_archived) or 'none'}",
        f"PII redactions: {report.redactions}",
        "",
        f"{'id':<72} {'type':<22} {'role':<5} {'bullets':>7}  website",
    ]
    for e in p["entities"]:
        site = e["website"]["page"] if e["website"] else "-"
        lines.append(f"{e['id']:<72} {e['type']:<22} {e['role']:<5} {len(e['bullets']):>7}  {site}")
    lines += [
        "",
        f"Skills: {sum(map(len, p['skills'].values()))} items in {len(p['skills'])} groups",
    ]
    lines.append("")
    lines.append("Unmatched:")
    lines.append(f"  detail pages with no project entity: {report.unmatched_pages or 'none'}")
    lines.append(
        f"  project entities with no detail page: {report.projects_without_page or 'none'}"
    )
    lines.append(
        f"  projects.html cards with no resume entity: {report.site_cards_without_entity or 'none'}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    try:
        report = run_sync(settings.resume_content_path, settings.site_path)
    except SourceMissingError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
