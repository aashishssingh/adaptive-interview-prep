"""Validate the question bank and print coverage.

Usage:  python -m prep.bank.validate [--questions DIR] [--datasets DIR]
Exits 1 on any failure.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from prep.bank.loader import DATASETS_DIR, QUESTIONS_DIR, generated_dir_for, load_bank_with_errors
from prep.bank.runner import check_datasets, run_python_question, run_sql_question
from prep.bank.schema import QUESTION_TYPES, CodingPython, CodingSQL, Question
from prep.meta import DIFFICULTY_BANDS, ROLES

BANDS = [label for _lo, _hi, label in DIFFICULTY_BANDS]
MIN_PER_BAND = 2


@dataclass
class ValidationReport:
    questions: list[Question]
    errors: list[str] = field(default_factory=list)
    dataset_sizes: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate(
    questions_dir: Path = QUESTIONS_DIR,
    datasets_dir: Path = DATASETS_DIR,
    min_rows: int = 20,
    max_rows: int = 200,
) -> ValidationReport:
    questions, errors = load_bank_with_errors(questions_dir)
    report = ValidationReport(questions=questions, errors=list(errors))
    if not questions and not errors:
        report.errors.append(f"no questions found in {questions_dir}")

    sizes, ds_errors = (
        check_datasets(datasets_dir, min_rows, max_rows) if datasets_dir.exists() else ({}, [])
    )
    report.dataset_sizes = sizes
    report.errors.extend(ds_errors)

    report.errors.extend(check_generated_facts(questions, questions_dir))
    for q in questions:
        if isinstance(q, CodingPython):
            report.errors.extend(run_python_question(q))
        elif isinstance(q, CodingSQL):
            if q.dataset not in sizes:
                report.errors.append(f"{q.id}: unknown dataset {q.dataset!r}")
            else:
                report.errors.extend(run_sql_question(q, datasets_dir))
    return report


def facts_dir_for(questions_dir: Path) -> Path:
    return generated_dir_for(questions_dir).parent / "facts"


def check_generated_facts(questions: list[Question], questions_dir: Path) -> list[str]:
    """Every fact_id on a generated question must exist in its entity's facts file."""
    errors: list[str] = []
    facts_dir = facts_dir_for(questions_dir)
    cache: dict[str, set[str] | None] = {}
    for q in questions:
        if q.source != "generated" or not q.fact_ids:
            continue
        if q.entity_id not in cache:
            path = facts_dir / f"{q.entity_id}.json"
            cache[q.entity_id] = (
                {f["fact_id"] for f in json.loads(path.read_text())["facts"]}
                if path.exists()
                else None
            )
        known = cache[q.entity_id]
        if known is None:
            errors.append(f"{q.id}: facts file for {q.entity_id} not found")
            continue
        missing = [f for f in q.fact_ids if f not in known]
        if missing:
            errors.append(f"{q.id}: unknown fact_ids {missing}")
    return errors


def generated_summary(questions: list[Question]) -> str:
    gen = [q for q in questions if q.source == "generated"]
    if not gen:
        return "Generated questions: none."
    by_entity = Counter((q.entity_id, q.status) for q in gen)
    lines = [f"Generated questions: {len(gen)}"]
    for entity in sorted({q.entity_id for q in gen}):
        counts = ", ".join(
            f"{s} {by_entity[(entity, s)]}"
            for s in ("draft", "approved", "rejected", "retired")
            if by_entity[(entity, s)]
        )
        lines.append(f"  {entity}: {counts}")
    return "\n".join(lines)


def band_gaps(questions: list[Question], minimum: int = MIN_PER_BAND) -> list[tuple[str, str, int]]:
    counts = Counter((q.topic, q.band) for q in questions)
    topics = sorted({q.topic for q in questions})
    return [(t, b, counts[(t, b)]) for t in topics for b in BANDS if counts[(t, b)] < minimum]


def coverage_table(questions: list[Question]) -> str:
    """Topic x role rows, difficulty-band columns (with an "all" row per topic), then counts
    by role and by type."""
    counts = Counter((q.topic, q.role, q.band) for q in questions)
    topics = sorted({q.topic for q in questions})
    width = max([len(t) for t in topics] + [5])

    def row(name: str, role: str, cells: list[int]) -> str:
        return (
            f"{name:<{width}}  {role:<4} " + "".join(f"{c:>8}" for c in cells) + f"{sum(cells):>8}"
        )

    head = f"{'topic':<{width}}  {'role':<4} " + "".join(f"{b:>8}" for b in BANDS) + f"{'total':>8}"
    lines = [head, "-" * len(head)]
    for t in topics:
        name = t
        for role in ROLES:
            cells = [counts[(t, role, b)] for b in BANDS]
            if any(cells):
                lines.append(row(name, role, cells))
                name = ""
        lines.append(row("", "all", [sum(counts[(t, r, b)] for r in ROLES) for b in BANDS]))
    lines.append("-" * len(head))
    lines.append(row("ALL", "all", [sum(1 for q in questions if q.band == b) for b in BANDS]))
    role_counts = Counter(q.role for q in questions)
    type_counts = Counter(q.type for q in questions)
    lines.append("")
    lines.append("By role: " + ", ".join(f"{r} {role_counts[r]}" for r in ROLES))
    lines.append("By type: " + ", ".join(f"{t} {type_counts[t]}" for t in QUESTION_TYPES))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--questions", type=Path, default=QUESTIONS_DIR)
    parser.add_argument("--datasets", type=Path, default=DATASETS_DIR)
    args = parser.parse_args(argv)

    report = validate(args.questions, args.datasets)
    for name, tables in report.dataset_sizes.items():
        print(f"dataset {name}: " + ", ".join(f"{t} {n}" for t, n in tables.items()))
    authored = [q for q in report.questions if q.source == "authored"]
    print()
    print("Authored bank coverage:")
    print(coverage_table(authored))
    print()
    print(generated_summary(report.questions))
    gaps = band_gaps(authored)
    print()
    if gaps:
        print(f"Topic/band cells with fewer than {MIN_PER_BAND} questions:")
        for t, b, n in gaps:
            print(f"  {t} / {b}: {n}")
    else:
        print(f"Every topic has at least {MIN_PER_BAND} questions in every band.")
    print()
    if report.errors:
        print(f"FAILED: {len(report.errors)} error(s)", file=sys.stderr)
        for e in report.errors:
            print(f"  {e}", file=sys.stderr)
        return 1
    print(f"OK: {len(report.questions)} questions valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
