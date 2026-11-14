import json
import sqlite3

import pytest

from prep.bank.schema import parse_question, question_hash
from prep.history import History, now_iso
from tests.bank_helpers import free_text, multiple_choice


@pytest.fixture
def hist(tmp_path):
    return History(tmp_path / "nested" / "history.db")


def record(hist, q, outcome, score, session_id=None):
    return hist.record_attempt(
        session_id=session_id,
        question=q,
        question_hash=question_hash(q),
        started_at=now_iso(),
        submitted_at=now_iso(),
        duration_sec=12.5,
        answer_text="x",
        score=score,
        outcome=outcome,
        hints_used=1,
        grading_method="auto",
    )


def test_creates_directory_and_tables(tmp_path):
    h = History(tmp_path / "a" / "b" / "h.db")
    assert (tmp_path / "a" / "b" / "h.db").exists()
    assert h.attempts().empty and h.sessions().empty


def test_session_and_attempt_roundtrip(hist):
    q = parse_question(multiple_choice("alpha-0001", role="mle", difficulty=7))
    sid = hist.start_session("practice", {"roles": ["mle"], "difficulty": [4, 8]})
    aid = record(hist, q, "correct", 1.0, sid)
    hist.save_followups(aid, {"Why?": "Because.", "Empty": "  "})
    hist.end_session(sid)
    a = hist.attempts(sid).iloc[0]
    assert (a.question_id, a.role, a.topic, a.difficulty, a.type, a.band) == (
        "alpha-0001",
        "mle",
        "alpha",
        7,
        "multiple_choice",
        "Hard",
    )
    assert a.question_hash == question_hash(q) and a.hints_used == 1
    assert json.loads(a.followup_answers_json) == {"Why?": "Because."}
    s = hist.sessions().iloc[0]
    assert s["mode"] == "practice" and s["ended_at"] is not None
    assert json.loads(s.filters_json)["difficulty"] == [4, 8]


def test_question_hash_detects_edits():
    q1 = parse_question(free_text())
    q2 = parse_question(free_text(model_answer="A different, still long model answer."))
    assert question_hash(q1) == question_hash(parse_question(free_text()))
    assert question_hash(q1) != question_hash(q2)


def test_queries(hist):
    a = parse_question(free_text("alpha-0001", role="ds", difficulty=2))
    b = parse_question(free_text("alpha-0002", role="mle", difficulty=9))
    c = parse_question(free_text("beta-0001", role="both", difficulty=5))
    record(hist, a, "incorrect", 0.0)
    record(hist, a, "correct", 1.0)  # latest for a
    record(hist, b, "partial", 0.5)
    record(hist, c, "incorrect", 0.2)
    assert hist.last_outcomes() == {
        "alpha-0001": "correct",
        "alpha-0002": "partial",
        "beta-0001": "incorrect",
    }
    assert hist.attempt_counts() == {"alpha-0001": 2, "alpha-0002": 1, "beta-0001": 1}
    assert set(hist.missed_questions()["question_id"]) == {"alpha-0002", "beta-0001"}
    by_topic = hist.accuracy_by("topic").set_index("topic")
    assert by_topic.loc["alpha", "attempts"] == 3
    assert by_topic.loc["alpha", "pct_correct"] == pytest.approx(1 / 3)
    assert by_topic.loc["alpha", "mean_score"] == pytest.approx(0.5)
    by_band = hist.accuracy_by("band").set_index("band")
    assert set(by_band.index) == {"Easy", "Medium", "Expert"}
    by_role = hist.accuracy_by("role").set_index("role")
    assert by_role.loc["both", "pct_correct"] == 0
    with pytest.raises(ValueError):
        hist.accuracy_by("answer_text")


def test_rejects_invalid_values(hist):
    q = parse_question(free_text())
    with pytest.raises(sqlite3.IntegrityError):
        record(hist, q, "great", 1.0)
    with pytest.raises(sqlite3.IntegrityError):
        record(hist, q, "correct", 1.5)


def test_empty_accuracy(hist):
    assert list(hist.accuracy_by("role").columns) == [
        "role",
        "attempts",
        "mean_score",
        "pct_correct",
    ]
