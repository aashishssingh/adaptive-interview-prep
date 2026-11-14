import math

import pandas as pd
import pytest

from prep.bank import validate as v
from prep.bank.runner import normalize, values_equal
from tests.bank_helpers import all_types, coding_python, coding_sql, free_text, write_bank


def run(tmp_path, files, **kw):
    qdir, ddir = write_bank(tmp_path, files, **kw)
    return v.validate(qdir, ddir), qdir, ddir


def test_valid_bank_passes(tmp_path):
    report, qdir, ddir = run(tmp_path, {"alpha": all_types()})
    assert report.ok, report.errors
    assert report.dataset_sizes == {"tiny": {"nums": 20}}
    assert v.main(["--questions", str(qdir), "--datasets", str(ddir)]) == 0


def test_failing_python_solution(tmp_path):
    bad = coding_python(reference_solution="def add(a, b):\n    return a - b\n")
    report, *_ = run(tmp_path, {"alpha": [bad]})
    assert any("test 1 expected 3, got -1" in e for e in report.errors)


def test_python_expected_exception_not_raised(tmp_path):
    bad = coding_python(reference_solution="def add(a, b):\n    return 0 if a is None else a + b\n")
    report, *_ = run(tmp_path, {"alpha": [bad]})
    assert any("expected ValueError" in e for e in report.errors)


def test_python_wrong_function_name_and_starter(tmp_path):
    bad = coding_python(function_name="plus")
    report, *_ = run(tmp_path, {"alpha": [bad]})
    assert any("starter_code does not define plus()" in e for e in report.errors)
    assert any("does not define a function named 'plus'" in e for e in report.errors)


def test_python_syntax_error(tmp_path):
    bad = coding_python(reference_solution="def add(a, b) return a + b")
    report, *_ = run(tmp_path, {"alpha": [bad]})
    assert any("failed to load: SyntaxError" in e for e in report.errors)


def test_infinite_loop_is_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr("prep.bank.runner.TIME_LIMIT_SECONDS", 1)
    bad = coding_python(reference_solution="def add(a, b):\n    while True:\n        pass\n")
    bad["test_cases"] = bad["test_cases"][:4]
    report, *_ = run(tmp_path, {"alpha": [bad]})
    assert any("TimeLimitExceeded" in e for e in report.errors)


def test_sql_errors(tmp_path):
    broken = coding_sql("alpha-0001", reference_query="SELECT nope FROM nums")
    empty = coding_sql("alpha-0002", reference_query="SELECT * FROM nums WHERE n > 100")
    missing = coding_sql("alpha-0003", dataset="nonexistent")
    report, *_ = run(tmp_path, {"alpha": [broken, empty, missing]})
    joined = "\n".join(report.errors)
    assert "alpha-0001: reference_query failed" in joined
    assert "alpha-0002: reference_query returned no rows" in joined
    assert "alpha-0003: unknown dataset 'nonexistent'" in joined


def test_dataset_row_limits(tmp_path):
    report, *_ = run(tmp_path, {"alpha": [free_text()]})
    assert report.ok
    qdir, ddir = write_bank(tmp_path / "x", {"alpha": [free_text()]})
    report = v.validate(qdir, ddir, min_rows=21)
    assert any("table nums has 20 rows" in e for e in report.errors)


def test_schema_errors_and_duplicates_fail_main(tmp_path, capsys):
    files = {
        "alpha": [
            free_text("alpha-0001"),
            free_text("alpha-0001"),
            free_text("alpha-0002", difficulty=12),
        ]
    }
    qdir, ddir = write_bank(tmp_path, files)
    assert v.main(["--questions", str(qdir), "--datasets", str(ddir)]) == 1
    err = capsys.readouterr().err
    assert "duplicate id alpha-0001" in err
    assert "alpha-0002: difficulty" in err


def test_empty_bank_fails(tmp_path):
    report, *_ = run(tmp_path, {})
    assert not report.ok


def test_coverage_table_and_gaps(tmp_path):
    qs = [
        free_text("alpha-0001", difficulty=1),
        free_text("alpha-0002", difficulty=2, role="mle"),
        free_text("alpha-0003", difficulty=9, role="both"),
    ]
    report, *_ = run(tmp_path, {"alpha": qs})
    table = v.coverage_table(report.questions)
    assert "Easy  Medium    Hard  Expert" in table
    assert "By type: free_text 3" in table
    lines = {
        line.split()[0] if not line.startswith(" ") else line.split()[0]
        for line in table.splitlines()
        if line.strip()
    }
    assert "alpha" in lines
    gaps = v.band_gaps(report.questions)
    assert ("alpha", "Medium", 0) in gaps and ("alpha", "Hard", 0) in gaps
    assert ("alpha", "Easy", 2) not in gaps
    assert ("alpha", "Expert", 1) in gaps


def test_normalize_and_compare():
    df = pd.DataFrame({"a": [1, 2], "b": [1.5, float("nan")]})
    assert normalize(df) == {"__df__": {"a": [1, 2], "b": [1.5, None]}}
    assert normalize((1, {2})) == [1, [2]]
    assert values_equal(0.1 + 0.2, 0.3)
    assert not values_equal(True, 1)
    assert values_equal(math.inf, math.inf)
    assert not values_equal([1, 2], [1, 2, 3])


@pytest.mark.parametrize("arg", [{"__df__": {"x": [1, 2, 3]}}])
def test_dataframe_arguments(tmp_path, arg):
    q = coding_python(
        function_name="total",
        starter_code="def total(df):\n    pass\n",
        reference_solution="def total(df):\n    return float(df['x'].sum())\n",
        test_cases=[{"args": [arg], "expected": 6.0}] * 4,
    )
    report, *_ = run(tmp_path, {"alpha": [q]})
    assert report.ok, report.errors
