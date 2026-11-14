import pytest
from pydantic import ValidationError

from prep.bank.schema import CodingPython, FreeText, parse_question
from tests.bank_helpers import coding_python, coding_sql, free_text, multiple_choice, short_answer


def test_parses_every_type():
    for builder in (free_text, multiple_choice, short_answer, coding_python, coding_sql):
        q = parse_question(builder())
        assert q.type == builder()["type"]
        assert q.source == "authored"
        assert q.band == "Medium"


def test_type_specific_models():
    assert isinstance(parse_question(free_text()), FreeText)
    q = parse_question(coding_python())
    assert isinstance(q, CodingPython) and len(q.test_cases) == 4


@pytest.mark.parametrize(
    "change",
    [
        {"role": "de"},
        {"role": "DS"},
        {"difficulty": 0},
        {"difficulty": 11},
        {"difficulty": 4.0},
        {"difficulty": "4"},
        {"difficulty": True},
        {"id": "alpha-1"},
        {"id": "Alpha-0001"},
        {"id": "beta-0001"},  # prefix != topic
        {"tags": []},
        {"hints": ["a", "b", "c"]},
        {"follow_ups": ["a", "b", "c", "d"]},
        {"est_minutes": 0},
        {"est_minutes": "5"},
        {"source": "scraped"},
        {"unexpected_field": 1},
        {"type": "essay"},
        {"rubric": ["only", "two"]},
        {"rubric": ["1", "2", "3", "4", "5", "6", "7"]},
    ],
)
def test_rejects_bad_free_text(change):
    with pytest.raises(ValidationError):
        parse_question(free_text(**change))


@pytest.mark.parametrize(
    "change",
    [
        {"options": ["a", "b", "c"]},
        {"options": ["a", "b", "c", "d", "e"]},
        {"options": ["a", "A", "c", "d"]},
        {"answer_index": 4},
        {"answer_index": "1"},
        {"explanation": "short"},
    ],
)
def test_rejects_bad_multiple_choice(change):
    with pytest.raises(ValidationError):
        parse_question(multiple_choice(**change))


def test_short_answer_must_be_one_line():
    with pytest.raises(ValidationError):
        parse_question(short_answer(answer="line one\nline two"))


@pytest.mark.parametrize(
    "change",
    [
        {"test_cases": [{"args": [1, 2], "expected": 3}] * 3},
        {"test_cases": [{"args": [1, 2]}] * 4},  # missing expected
        {"function_name": "not valid"},
        {"model_answer": "not allowed here"},
    ],
)
def test_rejects_bad_coding_python(change):
    with pytest.raises(ValidationError):
        parse_question(coding_python(**change))


def test_rejects_bad_coding_sql():
    with pytest.raises(ValidationError):
        parse_question(coding_sql(order_matters="yes"))
    with pytest.raises(ValidationError):
        parse_question(coding_sql(expected_rows=[[1]]))  # expected results are never hand-written
