from pathlib import Path

import pytest

from prep import grading as g
from prep.bank.loader import DATASETS_DIR, by_id, filter_questions, load_bank
from prep.bank.schema import parse_question
from tests.bank_helpers import coding_python, coding_sql, free_text, multiple_choice, short_answer

FIXTURE_DATASETS = Path(__file__).parent / "fixtures" / "bank"


@pytest.fixture(scope="module")
def bank():
    return by_id(load_bank())


@pytest.mark.parametrize(
    "score,outcome",
    [
        (1.0, "correct"),
        (0.8, "correct"),
        (0.79, "partial"),
        (0.4, "partial"),
        (0.39, "incorrect"),
        (0.0, "incorrect"),
    ],
)
def test_outcome_thresholds(score, outcome):
    assert g.outcome_for(score) == outcome


def test_outcome_rejects_out_of_range():
    with pytest.raises(ValueError):
        g.outcome_for(1.5)


# --- multiple choice


def test_shuffle_is_seedable_permutation():
    q = parse_question(multiple_choice())
    a, b = g.shuffle_options(q, seed=7), g.shuffle_options(q, seed=7)
    assert a == b and sorted(a) == [0, 1, 2, 3]
    assert len({tuple(g.shuffle_options(q, seed=s)) for s in range(30)}) > 1


def test_mc_graded_by_original_index():
    q = parse_question(multiple_choice())  # answer_index = 1
    order = g.shuffle_options(q, seed=3)
    displayed_pos = order.index(1)
    r = g.grade_multiple_choice(q, order[displayed_pos])
    assert r.score == 1.0 and r.outcome == "correct" and r.method == "auto"
    wrong = g.grade_multiple_choice(q, 0)
    assert wrong.score == 0.0 and wrong.details["answer"] == "b"
    with pytest.raises(ValueError):
        g.grade_multiple_choice(q, 4)


# --- self-graded


def test_short_answer_self_grades():
    q = parse_question(short_answer())
    assert [g.grade_short_answer(q, s).score for s in ("got_it", "partly", "missed")] == [1, 0.5, 0]
    assert g.grade_short_answer(q, "partly").outcome == "partial"
    assert g.grade_short_answer(q, "got_it").method == "self"
    with pytest.raises(ValueError):
        g.grade_short_answer(q, "sort of")


def test_free_text_rubric_fraction():
    q = parse_question(free_text(rubric=["a", "b", "c", "d", "e"]))
    r = g.grade_free_text(q, [0, 2, 4, 4])
    assert r.score == pytest.approx(0.6) and r.outcome == "partial" and r.method == "rubric_self"
    assert r.details["missed"] == ["b", "d"]
    assert g.grade_free_text(q, []).outcome == "incorrect"
    assert g.grade_free_text(q, range(5)).outcome == "correct"
    with pytest.raises(ValueError):
        g.grade_free_text(q, [5])


# --- coding_python


@pytest.fixture
def add_q():
    return parse_question(coding_python())  # add(a, b); None raises ValueError


def test_python_correct(add_q):
    r = g.grade_python(add_q, add_q.reference_solution)
    assert r.score == 1.0 and r.details["passed"] == 4
    assert all(t["passed"] for t in r.details["tests"])


def test_python_partial_with_expected_actual_and_stdout(add_q):
    code = "def add(a, b):\n    print('debug', a)\n    return a * b\n"
    r = g.grade_python(add_q, code)
    tests = r.details["tests"]
    assert [t["passed"] for t in tests] == [False, False, False, False]
    assert tests[0]["expected"] == 3 and tests[0]["actual"] == 2
    assert tests[0]["stdout"] == "debug 1\n"
    assert "expected ValueError" in tests[3]["error"] or tests[3]["error"]


def test_python_exception_traceback(add_q):
    r = g.grade_python(add_q, "def add(a, b):\n    return 1 / 0\n")
    assert r.score == 0.0
    assert "ZeroDivisionError" in r.details["tests"][0]["error"]


def test_python_timeout_counts_as_failure(add_q):
    code = (
        "def add(a, b):\n    if a == 0.1:\n        while True:\n            pass\n"
        "    return a + b\n"
    )
    r = g.grade_python(add_q, code, timeout=2)
    tests = r.details["tests"]
    assert r.details["timed_out"] is True
    assert tests[0]["passed"] is True
    assert "Timed out" in tests[1]["error"]
    assert "Not run" in tests[2]["error"]
    assert r.score == pytest.approx(0.25)


def test_python_syntax_error_and_missing_function(add_q):
    r = g.grade_python(add_q, "def add(a, b) return a")
    assert r.score == 0 and "SyntaxError" in r.details["load_error"]
    r = g.grade_python(add_q, "def plus(a, b):\n    return a + b\n")
    assert "no function named 'add'" in r.details["load_error"]


def test_python_runs_isolated(add_q, tmp_path):
    # the user's code runs in a temp dir, in a separate process
    code = "import os\ndef add(a, b):\n    return os.getcwd()\n"
    r = g.grade_python(add_q, code)
    assert "prep_grade_" in str(r.details["tests"][0]["actual"])


def test_every_bank_python_reference_passes(bank):
    for q in filter_questions(bank.values(), type="coding_python"):
        r = g.grade_python(q, q.reference_solution)
        assert r.score == 1.0, (q.id, r.details)


# --- coding_sql


@pytest.fixture
def nums_q():
    return parse_question(
        coding_sql(
            reference_query="SELECT n, label FROM nums WHERE n < 5 ORDER BY n", order_matters=True
        )
    )


def test_sql_correct_and_column_names_ignored(nums_q):
    r = g.grade_sql(
        nums_q, "SELECT n AS x, label AS y FROM nums WHERE n < 5 ORDER BY n", FIXTURE_DATASETS
    )
    assert r.score == 1.0, r.details


def test_sql_wrong_order(nums_q):
    r = g.grade_sql(
        nums_q, "SELECT n, label FROM nums WHERE n < 5 ORDER BY n DESC", FIXTURE_DATASETS
    )
    assert r.score == 0 and "wrong order" in r.details["reason"]


def test_sql_order_ignored_when_not_required():
    q = parse_question(
        coding_sql(reference_query="SELECT n FROM nums WHERE n < 3", order_matters=False)
    )
    r = g.grade_sql(q, "SELECT n FROM nums WHERE n < 3 ORDER BY n DESC", FIXTURE_DATASETS)
    assert r.score == 1.0


@pytest.mark.parametrize(
    "query,reason",
    [
        ("SELECT n FROM nums WHERE n < 5", "Wrong columns"),
        ("SELECT n, label FROM nums WHERE n < 4 ORDER BY n", "Wrong row count"),
        ("SELECT n + 1, label FROM nums WHERE n < 5 ORDER BY n", "Wrong values"),
        ("", "Empty query"),
    ],
)
def test_sql_mismatch_reasons(nums_q, query, reason):
    r = g.grade_sql(nums_q, query, FIXTURE_DATASETS)
    assert r.score == 0 and reason in r.details["reason"]


def test_sql_error_message(nums_q):
    r = g.grade_sql(nums_q, "SELEC n FROM nums", FIXTURE_DATASETS)
    assert r.score == 0 and "Parser" in r.details["error"]
    assert r.details["expected_row_count"] == 5


def test_sql_no_file_access(nums_q):
    r = g.grade_sql(nums_q, "SELECT * FROM read_csv('/etc/hosts')", FIXTURE_DATASETS)
    assert r.score == 0 and "disabled" in r.details["error"]


def test_compare_results_tolerance_nulls_multiset():
    ok, _ = g.compare_results(
        ["a", "b"],
        [(1.0000001, None), (2, "x")],
        ["p", "q"],
        [(2, "x"), (1.0, None)],
        order_matters=False,
    )
    assert ok
    ok, _ = g.compare_results(["a"], [(1.01,)], ["a"], [(1.0,)], order_matters=False)
    assert not ok
    ok, _ = g.compare_results(["a"], [(1,), (1,)], ["a"], [(1,), (2,)], order_matters=False)
    assert not ok  # multiset, not set
    ok, _ = g.compare_results(["a"], [(None,)], ["a"], [(0,)], order_matters=True)
    assert not ok  # NULL is not 0


def test_sql_results_capped_for_display():
    q = parse_question(coding_sql(reference_query="SELECT range FROM range(80)"))
    r = g.grade_sql(q, "SELECT range FROM range(80)", FIXTURE_DATASETS)
    assert r.score == 1.0 and len(r.details["user_rows"]) == 50
    assert r.details["user_row_count"] == 80


def test_every_bank_sql_reference_passes(bank):
    for q in filter_questions(bank.values(), type="coding_sql"):
        r = g.grade_sql(q, q.reference_query, DATASETS_DIR)
        assert r.score == 1.0, (q.id, r.details.get("reason"))


def test_dataset_preview():
    preview = g.dataset_preview("healthcare", DATASETS_DIR)
    assert set(preview) == {"patients", "visits", "diagnoses"}
    assert len(preview["patients"]["rows"]) == 5
    assert preview["patients"]["columns"][0][0] == "patient_id"
