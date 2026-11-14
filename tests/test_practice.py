import pytest

from prep.bank.schema import parse_question
from prep.practice import format_duration, matching_questions, roles_for, summarize
from tests.bank_helpers import coding_sql, free_text, multiple_choice, short_answer

QS = [
    parse_question(free_text("alpha-0001", role="ds", difficulty=2)),
    parse_question(multiple_choice("alpha-0002", role="mle", difficulty=5)),
    parse_question(short_answer("beta-0001", role="both", difficulty=8)),
    parse_question(coding_sql("beta-0002", role="ds", difficulty=6)),
]


def ids(qs):
    return [q.id for q in qs]


def test_roles_for_tracks():
    assert roles_for("Data Scientist") == {"ds", "both"}
    assert roles_for("ML/AI Engineer") == {"mle", "both"}
    assert roles_for("All") == {"ds", "mle", "both"}
    assert roles_for("Data Scientist", only_role_specific=True) == {"ds"}
    assert roles_for("All", only_role_specific=True) == {"ds", "mle"}
    with pytest.raises(ValueError):
        roles_for("Data Engineer")


def test_matching_questions_filters():
    assert ids(matching_questions(QS, "Data Scientist")) == ["alpha-0001", "beta-0001", "beta-0002"]
    assert ids(matching_questions(QS, "ML/AI Engineer", True)) == ["alpha-0002"]
    assert ids(matching_questions(QS, topics=["beta"])) == ["beta-0001", "beta-0002"]
    assert ids(matching_questions(QS, difficulty=(5, 6))) == ["alpha-0002", "beta-0002"]
    assert ids(matching_questions(QS, types=["free_text"])) == ["alpha-0001"]


def test_flashcards_restrict_types():
    assert ids(matching_questions(QS, mode="Flashcards")) == ["alpha-0002", "beta-0001"]
    assert ids(matching_questions(QS, mode="Flashcards", types=["free_text"])) == []
    assert ids(matching_questions(QS, mode="Flashcards", types=["short_answer", "coding_sql"])) == [
        "beta-0001"
    ]


def test_summarize():
    s = summarize(
        [
            {
                "question_id": "a",
                "topic": "t1",
                "role": "ds",
                "score": 1.0,
                "outcome": "correct",
                "duration_sec": 30,
            },
            {
                "question_id": "b",
                "topic": "t1",
                "role": "mle",
                "score": 0.5,
                "outcome": "partial",
                "duration_sec": 45,
            },
            {
                "question_id": "c",
                "topic": "t2",
                "role": "ds",
                "score": 0.0,
                "outcome": "incorrect",
                "duration_sec": 15,
            },
        ]
    )
    assert s["n"] == 3 and s["total_score"] == 1.5 and s["total_time_sec"] == 90
    t1 = s["by_topic"].set_index("topic").loc["t1"]
    assert t1.questions == 2 and t1.correct == 1
    assert s["by_role"].set_index("role").loc["ds", "score"] == 1.0
    assert summarize([])["n"] == 0


def test_format_duration():
    assert format_duration(5) == "0:05"
    assert format_duration(125) == "2:05"
    assert format_duration(3725) == "1:02:05"


def test_badge_contrast_meets_aa_for_every_role():
    from prep.meta import ROLE_STYLES
    from prep.ui.components import badge_text_color, contrast_ratio, role_badge_html

    for role, style in ROLE_STYLES.items():
        fg = badge_text_color(style.color)
        assert contrast_ratio(style.color, fg) >= 4.5, role
        assert style.badge in role_badge_html(role)  # text badge always present
    assert badge_text_color("#E69F00") == "#000000"
    assert badge_text_color("#0072B2") == "#FFFFFF"
