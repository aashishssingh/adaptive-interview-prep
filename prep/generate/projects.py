"""Generate project questions from data/profile.json.

Usage:
  python -m prep.generate.projects [--entity ID ...] [--changed-only] [--dry-run] [--yes]

Step A (deep model, one call per entity): group bullets and website text into distinct facts.
Step B (deep model, one call per entity): write questions per fact at four depths.
Step C (deterministic): schema validation, near-duplicate removal, fact_id checks, grounding
checks, and a report. Output goes to data/generated/facts/ and data/generated/projects/.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from prep.config import PROJECT_ROOT, load_settings
from prep.generate import prompts
from prep.generate.checks import check_questions
from prep.generate.models import FactsOut, QuestionsOut
from prep.generate.store import load_entity_file, merge_questions, retire_all, save_entity_file
from prep.llm.client import LLMClient, get_llm_client
from prep.llm.errors import LLMError
from prep.llm.pricing import estimate_cost, estimate_tokens
from prep.meta import combine_roles
from prep.profile.redact import load_names

GENERATED_DIR = PROJECT_ROOT / "data" / "generated"
PROFILE_PATH = PROJECT_ROOT / "data" / "profile.json"
LOCAL_DIR = PROJECT_ROOT / "data" / "local"

TECHNICAL_TYPES = ("experience", "research", "project")
BEHAVIORAL_TYPES = ("additional_experience", "service")
FACTS_MAX_TOKENS = 16_000
QUESTIONS_MAX_TOKENS = 64_000
PER_FACT = {"high": (6, 8), "normal": (4, 5)}
DOC_LABELS_SUFFIX = {
    "Data_Scientist": "DS resume",
    "ML_AI_Engineer": "MLE resume",
    "Data_Engineer": "DE resume",
    "CV": "CV",
}


@dataclass
class Paths:
    profile: Path = PROFILE_PATH
    generated: Path = GENERATED_DIR
    local: Path = LOCAL_DIR

    @property
    def facts(self) -> Path:
        return self.generated / "facts"

    @property
    def projects(self) -> Path:
        return self.generated / "projects"

    @property
    def entities_config(self) -> Path:
        return self.generated / "entities.yaml"


@dataclass
class PlannedCall:
    entity_id: str
    step: str
    model: str
    input_tokens: int
    output_tokens: int

    @property
    def cost(self) -> float | None:
        return estimate_cost(self.model, self.input_tokens, self.output_tokens)


@dataclass
class EntityResult:
    entity_id: str
    facts: int = 0
    report: dict[str, Any] = field(default_factory=dict)
    merge: dict[str, int] = field(default_factory=dict)
    error: str | None = None


# --- helpers ---------------------------------------------------------------------------------


def doc_labels(documents: list[str]) -> dict[str, str]:
    labels = {}
    for d in documents:
        labels[d] = next((v for k, v in DOC_LABELS_SUFFIX.items() if d.endswith(k)), d)
    return labels


def load_entity_config(paths: Paths) -> dict[str, dict[str, str]]:
    if not paths.entities_config.exists():
        return {}
    data = yaml.safe_load(paths.entities_config.read_text(encoding="utf-8")) or {}
    return data.get("entities") or {}


def auto_slug(entity_id: str) -> str:
    stop = {"the", "of", "and", "for", "with", "at", "a", "an", "in", "on"}
    words = [w for w in re.split(r"[^a-z0-9]+", entity_id.split("--")[0]) if w]
    words = [w for w in words if w not in stop and not w.isdigit()] or words
    return "-".join(words[:2])


def slug_for(entity_id: str, config: dict[str, dict[str, str]]) -> str:
    return (config.get(entity_id) or {}).get("slug") or auto_slug(entity_id)


def priority_for(entity_id: str, config: dict[str, dict[str, str]]) -> str:
    return (config.get(entity_id) or {}).get("priority", "normal")


def eligible(entity: dict[str, Any]) -> bool:
    return entity["type"] in TECHNICAL_TYPES + BEHAVIORAL_TYPES


def select_entities(
    profile: dict[str, Any], requested: list[str] | None, config: dict[str, dict[str, str]]
) -> list[dict[str, Any]]:
    entities = [e for e in profile["entities"] if eligible(e)]
    if not requested:
        return entities
    by_key = {}
    for e in entities:
        by_key[e["id"]] = e
        by_key[slug_for(e["id"], config)] = e
    unknown = [r for r in requested if r not in by_key]
    if unknown:
        raise SystemExit(f"Unknown or ineligible entity: {', '.join(unknown)}")
    seen, out = set(), []
    for r in requested:
        e = by_key[r]
        if e["id"] not in seen:
            seen.add(e["id"])
            out.append(e)
    return out


def changed_entities(paths: Paths, profile: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(added + changed ids, removed ids) from data/local/profile_changes.json."""
    path = paths.local / "profile_changes.json"
    if not path.exists():
        raise SystemExit(f"{path} not found. Run `python -m prep.profile.sync` first.")
    changes = json.loads(path.read_text(encoding="utf-8"))
    ids = {e["id"] for e in profile["entities"] if eligible(e)}
    return (
        [i for i in changes.get("added", []) + changes.get("changed", []) if i in ids],
        list(changes.get("removed", [])),
    )


def source_text(entity: dict[str, Any]) -> str:
    parts = [b["text"] for b in entity["bullets"]]
    if entity.get("website"):
        parts.append(entity["website"]["text"])
    parts += [entity.get("org") or "", entity.get("title") or "", entity.get("date") or ""]
    return "\n".join(parts)


# --- planning --------------------------------------------------------------------------------


def plan(
    entities: list[dict[str, Any]],
    model: str,
    labels: dict[str, str],
    config: dict[str, dict[str, str]],
) -> list[PlannedCall]:
    calls = []
    for e in entities:
        behavioral = e["type"] in BEHAVIORAL_TYPES
        facts_in = estimate_tokens(prompts.FACTS_SYSTEM + prompts.facts_user(e, labels))
        n_bullets = len(e["bullets"]) + (2 if e.get("website") else 0)
        est_facts = max(1, math.ceil(n_bullets * 0.6))
        facts_out = est_facts * 70 + 400  # JSON plus some thinking
        calls.append(PlannedCall(e["id"], "facts", model, facts_in, facts_out))
        if behavioral:
            est_questions = 4
        else:
            lo, hi = PER_FACT[priority_for(e["id"], config)]
            est_questions = est_facts * (lo + hi) // 2
        q_in = (
            estimate_tokens(prompts.QUESTIONS_SYSTEM + prompts.entity_block(e, labels))
            + est_facts * 60
        )
        q_out = int(est_questions * 420 * 1.3)  # ~420 tokens per question, +30% for thinking
        calls.append(PlannedCall(e["id"], "questions", model, q_in, q_out))
    return calls


def format_plan(calls: list[PlannedCall]) -> str:
    lines = [f"{'entity':<62} {'step':<10} {'model':<18} {'in':>7} {'out':>7} {'~USD':>7}"]
    total_in = total_out = 0
    total_cost = 0.0
    unknown_price = False
    for c in calls:
        cost = c.cost
        total_in += c.input_tokens
        total_out += c.output_tokens
        if cost is None:
            unknown_price = True
        else:
            total_cost += cost
        cost_s = f"{cost:.3f}" if cost is not None else "?"
        lines.append(
            f"{c.entity_id[:62]:<62} {c.step:<10} {c.model:<18} "
            f"{c.input_tokens:>7} {c.output_tokens:>7} {cost_s:>7}"
        )
    lines.append(
        f"{'TOTAL':<62} {'':<10} {'':<18} {total_in:>7} {total_out:>7} "
        f"{total_cost:>7.2f}" + (" (+ unknown-price calls)" if unknown_price else "")
    )
    lines.append(
        f"{len(calls)} planned call(s). Estimates are rough (about 4 characters per "
        "token, output sized by bullet count, +30% for thinking). Cached calls cost "
        "nothing."
    )
    return "\n".join(lines)


# --- steps -----------------------------------------------------------------------------------


def run_facts(
    client: LLMClient, entity: dict[str, Any], labels: dict[str, str], model: str, slug: str
) -> list[dict[str, Any]]:
    out = client.complete_json(
        prompts.FACTS_SYSTEM,
        prompts.facts_user(entity, labels),
        model,
        FACTS_MAX_TOKENS,
        FactsOut,
        purpose=f"facts:{entity['id']}",
    )
    n = len(entity["bullets"])
    facts = []
    for i, f in enumerate(out.facts, start=1):
        idx = sorted({b for b in f.source_bullets if 0 <= b < n})
        if not idx and not f.uses_website_text:
            continue  # no traceable source: drop rather than keep an ungrounded fact
        role_hint = combine_roles([entity["bullets"][b]["role"] for b in idx]) if idx else "both"
        facts.append(
            {
                "fact_id": f"{slug}-f{i:02d}",
                "statement": f.statement.strip(),
                "source_bullets": idx,
                "uses_website_text": f.uses_website_text,
                "role_hint": role_hint,
                "substantive": f.substantive,
            }
        )
    return facts


def save_facts(
    paths: Paths, entity: dict[str, Any], facts: list[dict[str, Any]], model: str, now: str
) -> Path:
    paths.facts.mkdir(parents=True, exist_ok=True)
    path = paths.facts / f"{entity['id']}.json"
    path.write_text(
        json.dumps(
            {
                "entity_id": entity["id"],
                "profile_hash": entity.get("content_hash"),
                "generated_by": model,
                "generated_at": now,
                "facts": facts,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def run_questions(
    client: LLMClient,
    entity: dict[str, Any],
    facts: list[dict[str, Any]],
    labels: dict[str, str],
    model: str,
    priority: str,
) -> QuestionsOut:
    behavioral = entity["type"] in BEHAVIORAL_TYPES
    system = prompts.BEHAVIORAL_SYSTEM if behavioral else prompts.QUESTIONS_SYSTEM
    user = prompts.questions_user(entity, facts, labels, PER_FACT[priority], behavioral)
    return client.complete_json(
        system, user, model, QUESTIONS_MAX_TOKENS, QuestionsOut, purpose=f"questions:{entity['id']}"
    )


def generate_entity(
    client: LLMClient,
    entity: dict[str, Any],
    *,
    paths: Paths,
    labels: dict[str, str],
    model: str,
    config: dict[str, dict[str, str]],
    name_list: list[str],
    now: str,
) -> EntityResult:
    res = EntityResult(entity["id"])
    slug = slug_for(entity["id"], config)
    facts = run_facts(client, entity, labels, model, slug)
    save_facts(paths, entity, facts, model, now)
    res.facts = len(facts)
    out = run_questions(client, entity, facts, labels, model, priority_for(entity["id"], config))
    behavioral = entity["type"] in BEHAVIORAL_TYPES
    questions, report = check_questions(
        out.questions,
        entity_id=entity["id"],
        topic="behavioral" if behavioral else "projects",
        fact_ids={f["fact_id"] for f in facts},
        source_text=source_text(entity),
        meta={
            "generated_by": model,
            "generated_at": now,
            "profile_hash": entity.get("content_hash"),
        },
        name_list=name_list,
    )
    path = paths.projects / f"{entity['id']}.yaml"
    data = load_entity_file(path)
    merged, merge_stats = merge_questions(data["questions"], questions, slug)
    save_entity_file(
        path,
        {
            "entity_id": entity["id"],
            "profile_hash": entity.get("content_hash"),
            "questions": merged,
        },
    )
    res.report, res.merge = report, merge_stats
    return res


def format_result(r: EntityResult) -> str:
    if r.error:
        return f"{r.entity_id}: FAILED: {r.error}"
    rep = r.report
    lines = [
        f"{r.entity_id}: {r.facts} facts; {rep['kept']} questions kept of {rep['received']} "
        f"(duplicates dropped {rep['duplicates_dropped']}, schema errors "
        f"{len(rep['schema_errors'])}, unknown fact_ids {len(rep['unknown_fact_ids'])}, "
        f"difficulty clamped {rep['difficulty_clamped']})",
        f"  by depth: {rep['by_depth']}",
        f"  by role:  {rep['by_role']}",
        f"  by band:  {rep['by_band']}",
        f"  needs your input: {rep['needs_user_input']}; flagged numbers: {len(rep['ungrounded'])}",
        f"  file: added {r.merge.get('added', 0)}, updated {r.merge.get('updated', 0)}, "
        f"kept {r.merge.get('kept', 0)}, retired {r.merge.get('retired', 0)}",
    ]
    for i, err in rep["schema_errors"][:5]:
        lines.append(f"  schema error in item {i}: {' '.join(err)[:200]}")
    return "\n".join(lines)


# --- CLI -------------------------------------------------------------------------------------


def main(
    argv: list[str] | None = None,
    *,
    paths: Paths | None = None,
    client_factory: Callable[[], LLMClient] | None = None,
    confirm: Callable[[str], str] = input,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--entity", nargs="+", help="entity id(s) or short slug(s)")
    parser.add_argument(
        "--changed-only",
        action="store_true",
        help="only entities added or changed in data/local/profile_changes.json",
    )
    parser.add_argument("--dry-run", action="store_true", help="estimate cost; no API calls")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args(argv)
    paths = paths or Paths()

    settings = load_settings()
    model = settings.llm_model_deep
    profile = json.loads(paths.profile.read_text(encoding="utf-8"))
    config = load_entity_config(paths)
    labels = doc_labels(profile["documents"])

    removed: list[str] = []
    if args.changed_only:
        ids, removed = changed_entities(paths, profile)
        if args.entity:
            ids = [
                i
                for i in ids
                if i in {e["id"] for e in select_entities(profile, args.entity, config)}
            ]
        entities = [e for e in profile["entities"] if e["id"] in set(ids)]
    else:
        entities = select_entities(profile, args.entity, config)

    calls = plan(entities, model, labels, config)
    print(
        f"Provider: {settings.llm_provider}; model: {model}; "
        f"credentials: {settings.credential_source}"
    )
    print(format_plan(calls))
    if removed:
        print(f"Removed entities whose questions will be retired: {', '.join(removed)}")
    if args.dry_run:
        print("Dry run: no API calls made.")
        return 0
    if not entities and not removed:
        print("Nothing to do.")
        return 0
    if not args.yes:
        if not sys.stdin.isatty() and confirm is input:
            print("Not running interactively; re-run with --yes to proceed.")
            return 1
        answer = confirm("Proceed and spend the estimated amount? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Cancelled.")
            return 1

    for entity_id in removed:
        n = retire_all(paths.projects / f"{entity_id}.yaml")
        print(f"{entity_id}: removed from profile; retired {n} question(s)")
    if not entities:
        return 0

    try:
        client = (client_factory or get_llm_client)()
    except LLMError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    name_list = load_names(paths.local / "redact_names.txt")
    now = datetime.now(UTC).isoformat(timespec="seconds")
    failures = 0
    for e in entities:
        try:
            res = generate_entity(
                client,
                e,
                paths=paths,
                labels=labels,
                model=model,
                config=config,
                name_list=name_list,
                now=now,
            )
        except LLMError as err:
            res = EntityResult(e["id"], error=str(err))
            failures += 1
        print(format_result(res))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
