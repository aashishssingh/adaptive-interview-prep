"""Builders for tiny question banks used by the bank tests."""

from __future__ import annotations

import copy
import shutil
from pathlib import Path

import yaml

FIXTURES = Path(__file__).parent / "fixtures" / "bank"

BASE = {
    "role": "ds",
    "difficulty": 4,
    "subtopic": "basics",
    "tags": ["test"],
    "prompt": "A sufficiently long prompt for testing.",
    "est_minutes": 3,
}


def free_text(qid="alpha-0001", **kw):
    return {
        **BASE,
        "id": qid,
        "topic": qid.rsplit("-", 1)[0],
        "type": "free_text",
        "model_answer": "A model answer that is long enough.",
        "rubric": ["point one", "point two", "point three"],
        **kw,
    }


def multiple_choice(qid="alpha-0002", **kw):
    return {
        **BASE,
        "id": qid,
        "topic": qid.rsplit("-", 1)[0],
        "type": "multiple_choice",
        "options": ["a", "b", "c", "d"],
        "answer_index": 1,
        "explanation": "b is right because of reasons; a is wrong.",
        **kw,
    }


def short_answer(qid="alpha-0003", **kw):
    return {
        **BASE,
        "id": qid,
        "topic": qid.rsplit("-", 1)[0],
        "type": "short_answer",
        "answer": "42",
        "explanation": "Because six times seven is 42.",
        **kw,
    }


def coding_python(qid="alpha-0004", **kw):
    return {
        **BASE,
        "id": qid,
        "topic": qid.rsplit("-", 1)[0],
        "type": "coding_python",
        "function_name": "add",
        "starter_code": "def add(a, b):\n    pass\n",
        "reference_solution": "def add(a, b):\n    if a is None:\n        raise ValueError\n"
        "    return a + b\n",
        "test_cases": [
            {"args": [1, 2], "expected": 3},
            {"args": [0.1, 0.2], "expected": 0.3},
            {"kwargs": {"a": -1, "b": 1}, "expected": 0},
            {"args": [None, 1], "expected": {"__raises__": "ValueError"}},
        ],
        "explanation": "Adds two numbers; rejects None.",
        **kw,
    }


def coding_sql(qid="alpha-0005", **kw):
    return {
        **BASE,
        "id": qid,
        "topic": qid.rsplit("-", 1)[0],
        "type": "coding_sql",
        "dataset": "tiny",
        "reference_query": "SELECT label, COUNT(*) FROM nums GROUP BY 1",
        "order_matters": False,
        "explanation": "Counts even and odd numbers.",
        **kw,
    }


def all_types(topic="alpha"):
    return [
        f(f"{topic}-{i:04d}")
        for i, f in enumerate(
            [free_text, multiple_choice, short_answer, coding_python, coding_sql], 1
        )
    ]


def write_bank(root: Path, files: dict[str, list[dict]], with_dataset: bool = True):
    qdir = root / "questions"
    qdir.mkdir(parents=True, exist_ok=True)
    for name, questions in files.items():
        (qdir / f"{name}.yaml").write_text(yaml.safe_dump({"questions": copy.deepcopy(questions)}))
    ddir = qdir / "datasets"
    ddir.mkdir(exist_ok=True)
    if with_dataset:
        shutil.copy(FIXTURES / "tiny.sql", ddir / "tiny.sql")
    return qdir, ddir
