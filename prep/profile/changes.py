"""Content hashes, snapshots of the previous profile, and old-vs-new change detection."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


def content_hash(entity: dict[str, Any]) -> str:
    body = {k: v for k, v in entity.items() if k != "content_hash"}
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def load_profile(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def diff_profiles(old: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    old_h = {e["id"]: e.get("content_hash") for e in (old or {}).get("entities", [])}
    new_h = {e["id"]: e["content_hash"] for e in new["entities"]}
    return {
        "first_run": old is None,
        "added": sorted(set(new_h) - set(old_h)),
        "removed": sorted(set(old_h) - set(new_h)),
        "changed": sorted(i for i in set(new_h) & set(old_h) if new_h[i] != old_h[i]),
        "skills_changed": old is not None and old.get("skills") != new.get("skills"),
    }


def snapshot(profile_path: Path, snapshot_dir: Path, now: datetime) -> Path | None:
    if not profile_path.exists():
        return None
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    dest = snapshot_dir / f"profile-{now.strftime('%Y%m%dT%H%M%S')}.json"
    shutil.copy2(profile_path, dest)
    return dest


def has_changes(changes: dict[str, Any]) -> bool:
    return bool(
        changes["added"] or changes["removed"] or changes["changed"] or changes["skills_changed"]
    )


def format_summary(changes: dict[str, Any], n_entities: int) -> str:
    if changes["first_run"]:
        return f"No previous profile.json: all {n_entities} entities are new."
    if not has_changes(changes):
        return "No changes since the previous profile."
    lines = ["Changes since the previous profile:"]
    for kind in ("added", "removed", "changed"):
        ids = changes[kind]
        lines.append(f"  {kind} ({len(ids)})" + (":" if ids else ""))
        lines.extend(f"    - {i}" for i in ids)
    lines.append(f"  skills changed: {'yes' if changes['skills_changed'] else 'no'}")
    return "\n".join(lines)
