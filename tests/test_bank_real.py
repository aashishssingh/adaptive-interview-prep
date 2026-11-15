"""The committed question bank must always validate and keep its coverage guarantees."""

from collections import Counter

import pytest

from prep.bank import validate as v
from prep.bank.loader import filter_questions


@pytest.fixture(scope="module")
def report():
    return v.validate()


def test_real_bank_is_valid(report):
    assert report.ok, "\n".join(report.errors)
    assert len(authored(report)) >= 150


def authored(report):
    return [q for q in report.questions if q.source == "authored"]


def test_every_topic_covers_every_band(report):
    assert v.band_gaps(authored(report), minimum=1) == []


def test_mostly_medium_to_hard(report):
    qs = authored(report)
    mid = sum(1 for q in qs if 4 <= q.difficulty <= 8)
    assert mid / len(qs) > 0.5


def test_behavioral_is_free_text_and_coding_topics_are_mostly_code(report):
    by_topic = Counter((q.topic, q.type) for q in report.questions)
    assert all(t == "free_text" for (topic, t) in by_topic if topic == "behavioral")
    for topic in ("python", "sql", "algorithms"):
        qs = filter_questions(report.questions, topic=topic)
        coding = [q for q in qs if q.type.startswith("coding_")]
        assert len(coding) / len(qs) >= 0.5, topic


def test_three_datasets_present(report):
    assert {"healthcare", "insurance", "product_events"} <= set(report.dataset_sizes)
