"""Grading for every question type. Pure functions except where code must be executed.

- multiple_choice: options are shuffled per attempt (seedable) and graded by the original index.
- coding_python: the user's code runs in a separate, isolated Python process (``-I``) with a
  timeout; each test case reports pass/fail, expected vs actual, stdout and tracebacks.
- coding_sql: the user's query and the reference query run on an in-memory DuckDB copy of the
  dataset (no file or network access) and their results are compared by position.
- free_text: fraction of rubric points the user ticks. short_answer: self-grade 1 / 0.5 / 0.
"""

from __future__ import annotations

import inspect
import json
import math
import random
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from prep.bank import runner
from prep.bank.schema import (
    CodingPython,
    CodingSQL,
    FreeText,
    MultipleChoice,
    ShortAnswer,
)

CORRECT_THRESHOLD = 0.8
PARTIAL_THRESHOLD = 0.4
PYTHON_TIMEOUT_SECONDS = 5
SQL_TIMEOUT_SECONDS = 5
SQL_FLOAT_REL_TOL = 1e-6
SQL_MAX_ROWS = 10_000
DISPLAY_ROWS = 50
SELF_GRADES = {"got_it": 1.0, "partly": 0.5, "missed": 0.0}


@dataclass(frozen=True)
class GradeResult:
    score: float
    outcome: str
    method: str  # auto | self | rubric_self
    details: dict[str, Any] = field(default_factory=dict)


def outcome_for(score: float) -> str:
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"score must be in [0, 1], got {score}")
    if score >= CORRECT_THRESHOLD:
        return "correct"
    if score >= PARTIAL_THRESHOLD:
        return "partial"
    return "incorrect"


def _result(score: float, method: str, **details: Any) -> GradeResult:
    return GradeResult(score=score, outcome=outcome_for(score), method=method, details=details)


# --- multiple choice -------------------------------------------------------------------------


def shuffle_options(q: MultipleChoice, seed: int | None = None) -> list[int]:
    """Return a display order: a permutation of the original option indices."""
    order = list(range(len(q.options)))
    random.Random(seed).shuffle(order)
    return order


def grade_multiple_choice(q: MultipleChoice, chosen_original_index: int) -> GradeResult:
    """Grade by the *original* option index (map the displayed position back first)."""
    if not 0 <= chosen_original_index < len(q.options):
        raise ValueError(f"choice {chosen_original_index} out of range")
    correct = chosen_original_index == q.answer_index
    return _result(
        1.0 if correct else 0.0,
        "auto",
        chosen_index=chosen_original_index,
        answer_index=q.answer_index,
        chosen=q.options[chosen_original_index],
        answer=q.options[q.answer_index],
    )


# --- self-graded types -----------------------------------------------------------------------


def grade_short_answer(q: ShortAnswer, self_grade: str) -> GradeResult:
    if self_grade not in SELF_GRADES:
        raise ValueError(f"self_grade must be one of {list(SELF_GRADES)}, got {self_grade!r}")
    return _result(SELF_GRADES[self_grade], "self", self_grade=self_grade, answer=q.answer)


def grade_self(self_grade: str) -> GradeResult:
    """Flashcard self-grade for any question type."""
    if self_grade not in SELF_GRADES:
        raise ValueError(f"self_grade must be one of {list(SELF_GRADES)}, got {self_grade!r}")
    return _result(SELF_GRADES[self_grade], "self", self_grade=self_grade)


def grade_free_text(q: FreeText, ticked: list[int] | set[int]) -> GradeResult:
    ticked = set(ticked)
    bad = [i for i in ticked if not 0 <= i < len(q.rubric)]
    if bad:
        raise ValueError(f"rubric indices out of range: {bad}")
    score = len(ticked) / len(q.rubric)
    return _result(
        score,
        "rubric_self",
        ticked=sorted(ticked),
        hit=[q.rubric[i] for i in sorted(ticked)],
        missed=[p for i, p in enumerate(q.rubric) if i not in ticked],
    )


# --- coding_python ---------------------------------------------------------------------------

_HARNESS_MAIN = r"""
import contextlib, io, json, sys, traceback

cases = json.load(open(sys.argv[2], encoding="utf-8"))
out = open(sys.argv[3], "a", encoding="utf-8")

def emit(record):
    out.write(json.dumps(record, default=repr) + "\n")
    out.flush()

namespace = {"__name__": "user_solution"}
buf = io.StringIO()
try:
    with contextlib.redirect_stdout(buf):
        exec(compile(open(sys.argv[1], encoding="utf-8").read(), "solution.py", "exec"), namespace)
    fn = namespace.get(cases["function_name"])
    if not callable(fn):
        raise NameError(f"no function named {cases['function_name']!r} is defined")
except BaseException:
    emit({"load_error": traceback.format_exc(limit=5), "stdout": buf.getvalue()})
    sys.exit(0)

for i, tc in enumerate(cases["tests"]):
    args = [to_arg(a) for a in tc.get("args", [])]
    kwargs = {k: to_arg(v) for k, v in tc.get("kwargs", {}).items()}
    expected = tc["expected"]
    raises = expected.get("__raises__") if isinstance(expected, dict) else None
    buf = io.StringIO()
    record = {"index": i, "args": tc.get("args", []), "kwargs": tc.get("kwargs", {}),
              "expected": expected, "actual": None, "passed": False, "error": None}
    try:
        with contextlib.redirect_stdout(buf):
            got = fn(*args, **kwargs)
        if raises:
            record["actual"] = normalize(got)
            record["error"] = f"expected {raises} to be raised"
        else:
            record["actual"] = normalize(got)
            record["passed"] = values_equal(record["actual"], _expected(expected))
    except Exception as e:
        if raises and type(e).__name__ == raises:
            record["passed"] = True
            record["actual"] = {"__raises__": type(e).__name__}
        else:
            record["actual"] = {"__raises__": type(e).__name__}
            record["error"] = traceback.format_exc(limit=5)
    record["stdout"] = buf.getvalue()[-2000:]
    emit(record)
"""


def _harness_source() -> str:
    """The subprocess runs with ``python -I`` (no project on sys.path), so the comparison
    helpers from prep.bank.runner are inlined into the harness rather than imported."""
    helpers = [
        runner._raise_timeout,
        runner.to_arg,
        runner.normalize,
        runner.values_equal,
        runner._expected,
    ]
    header = (
        "from __future__ import annotations\nimport copy\nimport math\n"
        "from datetime import date, datetime\nfrom typing import Any\n"
        "import numpy as np\nimport pandas as pd\n"
        f"REL_TOL = {runner.REL_TOL!r}\nABS_TOL = {runner.ABS_TOL!r}\n"
        "TIME_LIMIT_SECONDS = 0\nclass TimeLimitExceeded(Exception):\n    pass\n\n"
    )
    return header + "\n\n".join(inspect.getsource(f) for f in helpers) + _HARNESS_MAIN


def grade_python(
    q: CodingPython, code: str, timeout: float = PYTHON_TIMEOUT_SECONDS
) -> GradeResult:
    """Run ``code`` against the question's test cases in an isolated subprocess."""
    tests = [tc.model_dump() for tc in q.test_cases]
    with tempfile.TemporaryDirectory(prefix="prep_grade_") as tmp:
        tmpdir = Path(tmp)
        (tmpdir / "solution.py").write_text(code, encoding="utf-8")
        (tmpdir / "harness.py").write_text(_harness_source(), encoding="utf-8")
        (tmpdir / "cases.json").write_text(
            json.dumps({"function_name": q.function_name, "tests": tests}), encoding="utf-8"
        )
        results_path = tmpdir / "results.jsonl"
        results_path.touch()
        timed_out = False
        stderr = ""
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "harness.py", "solution.py", "cases.json", "results.jsonl"],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            stderr = proc.stderr[-4000:]
        except subprocess.TimeoutExpired:
            timed_out = True
        records = [
            json.loads(line)
            for line in results_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    if records and "load_error" in records[0]:
        return _result(
            0.0,
            "auto",
            tests=[],
            load_error=records[0]["load_error"],
            stdout=records[0].get("stdout", ""),
            timed_out=False,
        )

    by_index = {r["index"]: r for r in records}
    results = []
    for i, tc in enumerate(tests):
        if i in by_index:
            results.append(by_index[i])
            continue
        if timed_out:
            msg = (
                f"Timed out: the code did not finish within {timeout:g} seconds "
                "(possible infinite loop or very slow solution)."
                if i == len(by_index)
                else "Not run: an earlier test timed out."
            )
        else:
            msg = "Not run: the test process exited unexpectedly." + (
                f"\n{stderr}" if stderr else ""
            )
        results.append(
            {
                "index": i,
                "args": tc.get("args", []),
                "kwargs": tc.get("kwargs", {}),
                "expected": tc["expected"],
                "actual": None,
                "passed": False,
                "error": msg,
                "stdout": "",
            }
        )
    passed = sum(1 for r in results if r["passed"])
    return _result(
        passed / len(results),
        "auto",
        tests=results,
        passed=passed,
        total=len(results),
        timed_out=timed_out,
        stderr=stderr,
    )


# --- coding_sql ------------------------------------------------------------------------------


def _norm_cell(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def _cells_equal(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b and type(a) is type(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=SQL_FLOAT_REL_TOL, abs_tol=1e-9)
    return a == b


def _rows_equal(r1: tuple, r2: tuple) -> bool:
    return len(r1) == len(r2) and all(_cells_equal(a, b) for a, b in zip(r1, r2, strict=True))


def _multiset_match(user: list[tuple], ref: list[tuple]) -> tuple[bool, tuple | None]:
    """Greedy tolerant multiset match. Returns (ok, first unmatched user row)."""
    remaining = list(ref)
    for row in user:
        for j, cand in enumerate(remaining):
            if _rows_equal(row, cand):
                del remaining[j]
                break
        else:
            return False, row
    return not remaining, None


def compare_results(
    user_cols: list[str],
    user_rows: list[tuple],
    ref_cols: list[str],
    ref_rows: list[tuple],
    order_matters: bool,
) -> tuple[bool, str]:
    """Compare two result sets by position. Returns (passed, reason)."""
    if len(user_cols) != len(ref_cols):
        return False, (
            f"Wrong columns: expected {len(ref_cols)} column(s) ({', '.join(ref_cols)}), "
            f"got {len(user_cols)}."
        )
    if len(user_rows) != len(ref_rows):
        return False, f"Wrong row count: expected {len(ref_rows)} row(s), got {len(user_rows)}."
    u = [tuple(_norm_cell(c) for c in r) for r in user_rows]
    e = [tuple(_norm_cell(c) for c in r) for r in ref_rows]
    if order_matters:
        for i, (a, b) in enumerate(zip(u, e, strict=True)):
            if not _rows_equal(a, b):
                same_set, _ = _multiset_match(u, e)
                if same_set:
                    return (
                        False,
                        "Right rows, wrong order (this question requires a specific ORDER BY).",
                    )
                return False, f"Wrong values: row {i + 1} is {a}, expected {b}."
        return True, "Results match."
    ok, bad_row = _multiset_match(u, e)
    if ok:
        return True, "Results match (row order ignored)."
    return False, f"Wrong values: your row {bad_row} does not appear in the expected result."


def _run_with_timeout(con: duckdb.DuckDBPyConnection, query: str, timeout: float):
    timer = threading.Timer(timeout, con.interrupt)
    timer.start()
    try:
        cur = con.execute(query)
        cols = [d[0] for d in cur.description or []]
        rows = cur.fetchmany(SQL_MAX_ROWS + 1)
        return cols, rows
    finally:
        timer.cancel()


def sandboxed_connection(dataset: str, datasets_dir: Path) -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB loaded with a dataset; external (file/network) access disabled after."""
    path = datasets_dir / f"{dataset}.sql"
    if not path.exists():
        raise FileNotFoundError(f"dataset {dataset!r} not found")
    con = duckdb.connect(":memory:")
    con.execute(path.read_text(encoding="utf-8"))
    con.execute("SET enable_external_access = false")
    con.execute("SET lock_configuration = true")
    return con


def grade_sql(
    q: CodingSQL, query: str, datasets_dir: Path, timeout: float = SQL_TIMEOUT_SECONDS
) -> GradeResult:
    con = sandboxed_connection(q.dataset, datasets_dir)
    try:
        ref_cols, ref_rows = _run_with_timeout(con, q.reference_query, timeout)
        details: dict[str, Any] = {
            "expected_columns": ref_cols,
            "expected_rows": ref_rows[:DISPLAY_ROWS],
            "expected_row_count": len(ref_rows),
        }
        if not query.strip():
            return _result(0.0, "auto", **details, error="Empty query.", reason="Empty query.")
        try:
            user_cols, user_rows = _run_with_timeout(con, query, timeout)
        except duckdb.InterruptException:
            msg = f"Query cancelled after {timeout:g} seconds."
            return _result(0.0, "auto", **details, error=msg, reason=msg)
        except duckdb.Error as e:
            msg = f"{type(e).__name__}: {e}"
            return _result(0.0, "auto", **details, error=msg, reason="SQL error.")
    finally:
        con.close()

    details.update(
        user_columns=user_cols,
        user_rows=user_rows[:DISPLAY_ROWS],
        user_row_count=len(user_rows),
    )
    if len(user_rows) > SQL_MAX_ROWS:
        return _result(
            0.0, "auto", **details, reason=f"Too many rows (more than {SQL_MAX_ROWS:,})."
        )
    passed, reason = compare_results(user_cols, user_rows, ref_cols, ref_rows, q.order_matters)
    return _result(1.0 if passed else 0.0, "auto", **details, passed=passed, reason=reason)


def dataset_preview(dataset: str, datasets_dir: Path, n: int = 5) -> dict[str, dict[str, Any]]:
    """Tables -> {columns: [(name, type)], rows: first n rows, row_count}."""
    con = sandboxed_connection(dataset, datasets_dir)
    try:
        tables = [
            r[0]
            for r in con.execute(
                "SELECT table_name FROM information_schema.tables ORDER BY table_name"
            ).fetchall()
        ]
        out = {}
        for t in tables:
            cols = con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = ? ORDER BY ordinal_position",
                [t],
            ).fetchall()
            cur = con.execute(f'SELECT * FROM "{t}" LIMIT {int(n)}')
            out[t] = {
                "columns": cols,
                "rows": cur.fetchall(),
                "row_count": con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0],
            }
        return out
    finally:
        con.close()
