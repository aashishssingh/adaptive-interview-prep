"""Execute coding questions: Python reference solutions against test cases, and SQL reference
queries in DuckDB against a shared dataset.

This runs code from the authored bank only. Do not run untrusted (e.g. LLM-generated) code with
it outside a sandbox.
"""

from __future__ import annotations

import copy
import math
import signal
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from prep.bank.schema import CodingPython, CodingSQL

TIME_LIMIT_SECONDS = 5
REL_TOL = 1e-6
ABS_TOL = 1e-9


class TimeLimitExceeded(Exception):
    pass


@contextmanager
def time_limit(seconds: int) -> Iterator[None]:
    """SIGALRM-based limit (Unix, main thread only); a no-op elsewhere."""
    if not hasattr(signal, "SIGALRM"):
        yield
        return
    try:
        old = signal.signal(signal.SIGALRM, _raise_timeout)
    except ValueError:  # not in main thread
        yield
        return
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def _raise_timeout(signum, frame):
    raise TimeLimitExceeded(f"exceeded {TIME_LIMIT_SECONDS}s")


# --- value conversion and comparison --------------------------------------------------------


def to_arg(value: Any) -> Any:
    """Convert a YAML test-case value into a call argument."""
    if isinstance(value, dict) and set(value) == {"__df__"}:
        return pd.DataFrame(value["__df__"])
    return copy.deepcopy(value)


def normalize(value: Any) -> Any:
    """Convert a returned value into plain YAML-comparable Python."""
    if isinstance(value, pd.DataFrame):
        df = value.reset_index(drop=True)
        return {"__df__": {str(c): [normalize(v) for v in df[c].tolist()] for c in df.columns}}
    if isinstance(value, pd.Series):
        return {normalize(k): normalize(v) for k, v in value.to_dict().items()}
    if isinstance(value, np.ndarray):
        return [normalize(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        return normalize(value.item())
    if isinstance(value, (pd.Timestamp, datetime)):
        if value.hour == value.minute == value.second == value.microsecond == 0:
            return value.strftime("%Y-%m-%d")
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None or value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (list, tuple)):
        return [normalize(v) for v in value]
    if isinstance(value, (set, frozenset)):
        items = [normalize(v) for v in value]
        try:
            return sorted(items)
        except TypeError:
            return items
    if isinstance(value, dict):
        return {normalize(k): normalize(v) for k, v in value.items()}
    return value


def values_equal(got: Any, expected: Any) -> bool:
    if isinstance(got, bool) or isinstance(expected, bool):
        return got is expected or (type(got) is type(expected) and got == expected)
    if isinstance(got, (int, float)) and isinstance(expected, (int, float)):
        if math.isinf(got) or math.isinf(expected):
            return got == expected
        return math.isclose(got, expected, rel_tol=REL_TOL, abs_tol=ABS_TOL)
    if isinstance(got, list) and isinstance(expected, list):
        return len(got) == len(expected) and all(map(values_equal, got, expected))
    if isinstance(got, dict) and isinstance(expected, dict):
        return set(got) == set(expected) and all(values_equal(got[k], expected[k]) for k in got)
    return got == expected


def _expected(value: Any) -> Any:
    # YAML ".inf" parses to float('inf'); strings "inf"/"-inf" are allowed too.
    if value == "inf":
        return math.inf
    if value == "-inf":
        return -math.inf
    if isinstance(value, list):
        return [_expected(v) for v in value]
    if isinstance(value, dict) and set(value) != {"__raises__"}:
        return {k: _expected(v) for k, v in value.items()}
    return value


# --- Python ----------------------------------------------------------------------------------


def load_function(source: str, name: str, label: str):
    namespace: dict[str, Any] = {"__name__": f"bank_{label}"}
    exec(compile(source, f"<{label}>", "exec"), namespace)  # noqa: S102 - authored bank code
    fn = namespace.get(name)
    if not callable(fn):
        raise ValueError(f"does not define a function named {name!r}")
    return fn


def run_python_question(q: CodingPython) -> list[str]:
    """Return a list of error messages (empty = every test case passed)."""
    errors: list[str] = []
    try:
        compile(q.starter_code, f"<{q.id} starter>", "exec")
        if f"def {q.function_name}(" not in q.starter_code:
            errors.append(f"{q.id}: starter_code does not define {q.function_name}()")
    except SyntaxError as e:
        errors.append(f"{q.id}: starter_code has a syntax error: {e}")
    try:
        fn = load_function(q.reference_solution, q.function_name, q.id)
    except Exception as e:  # noqa: BLE001
        return errors + [f"{q.id}: reference_solution failed to load: {type(e).__name__}: {e}"]

    for i, tc in enumerate(q.test_cases, 1):
        args = [to_arg(a) for a in tc.args]
        kwargs = {k: to_arg(v) for k, v in tc.kwargs.items()}
        raises = tc.expected.get("__raises__") if isinstance(tc.expected, dict) else None
        try:
            with time_limit(TIME_LIMIT_SECONDS):
                got = fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            if raises and type(e).__name__ == raises:
                continue
            errors.append(f"{q.id}: test {i} raised {type(e).__name__}: {e}")
            continue
        if raises:
            errors.append(f"{q.id}: test {i} expected {raises} but returned {normalize(got)!r}")
            continue
        got_n, exp_n = normalize(got), _expected(tc.expected)
        if not values_equal(got_n, exp_n):
            errors.append(f"{q.id}: test {i} expected {exp_n!r}, got {got_n!r}")
    return errors


# --- SQL -------------------------------------------------------------------------------------


def dataset_path(name: str, datasets_dir: Path) -> Path:
    return datasets_dir / f"{name}.sql"


def connect_dataset(name: str, datasets_dir: Path) -> duckdb.DuckDBPyConnection:
    path = dataset_path(name, datasets_dir)
    if not path.exists():
        raise FileNotFoundError(f"dataset {name!r} not found ({path.name})")
    con = duckdb.connect(":memory:")
    con.execute(path.read_text(encoding="utf-8"))
    return con


def run_query(con: duckdb.DuckDBPyConnection, query: str) -> tuple[list[str], list[tuple]]:
    cur = con.execute(query)
    columns = [d[0] for d in cur.description or []]
    return columns, cur.fetchall()


def expected_result(q: CodingSQL, datasets_dir: Path) -> tuple[list[str], list[tuple]]:
    """Expected output for a SQL question: always computed by running the reference query."""
    con = connect_dataset(q.dataset, datasets_dir)
    try:
        return run_query(con, q.reference_query)
    finally:
        con.close()


def run_sql_question(q: CodingSQL, datasets_dir: Path) -> list[str]:
    try:
        _cols, rows = expected_result(q, datasets_dir)
    except Exception as e:  # noqa: BLE001
        return [f"{q.id}: reference_query failed on dataset {q.dataset!r}: {e}"]
    if not rows:
        return [f"{q.id}: reference_query returned no rows"]
    return []


def check_datasets(
    datasets_dir: Path, min_rows: int = 20, max_rows: int = 200
) -> tuple[dict[str, dict[str, int]], list[str]]:
    """Load every dataset and check each table has min_rows..max_rows rows."""
    sizes: dict[str, dict[str, int]] = {}
    errors: list[str] = []
    for path in sorted(datasets_dir.glob("*.sql")):
        try:
            con = connect_dataset(path.stem, datasets_dir)
        except Exception as e:  # noqa: BLE001
            errors.append(f"dataset {path.name}: failed to load: {e}")
            continue
        tables = [
            r[0]
            for r in con.execute(
                "SELECT table_name FROM information_schema.tables ORDER BY table_name"
            ).fetchall()
        ]
        if not tables:
            errors.append(f"dataset {path.name}: defines no tables")
        sizes[path.stem] = {}
        for t in tables:
            n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            sizes[path.stem][t] = n
            if not min_rows <= n <= max_rows:
                errors.append(
                    f"dataset {path.name}: table {t} has {n} rows (expected {min_rows}-{max_rows})"
                )
        con.close()
    return sizes, errors
