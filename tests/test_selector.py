import random

from prep.bank.schema import parse_question
from prep.engine.selector import RandomSelector, SelectionHistory, Selector
from tests.bank_helpers import free_text

QS = [parse_question(free_text(f"alpha-{i:04d}")) for i in range(1, 7)]


def ids(qs):
    return {q.id for q in qs}


def test_protocol():
    assert isinstance(RandomSelector(), Selector)


def test_prefers_unseen():
    hist = SelectionHistory(last_outcome={"alpha-0001": "incorrect", "alpha-0002": "correct"})
    sel = RandomSelector()
    for seed in range(20):
        q = sel.next_question(QS, hist, random.Random(seed))
        assert q.id not in {"alpha-0001", "alpha-0002"}


def test_then_missed_then_rest():
    seen = {q.id: "correct" for q in QS}
    seen["alpha-0003"] = "partial"
    seen["alpha-0005"] = "incorrect"
    sel = RandomSelector()
    picks = {sel.next_question(QS, SelectionHistory(seen), random.Random(s)).id for s in range(30)}
    assert picks == {"alpha-0003", "alpha-0005"}
    all_correct = {q.id: "correct" for q in QS}
    picks = {
        sel.next_question(QS, SelectionHistory(all_correct), random.Random(s)).id for s in range(60)
    }
    assert picks == ids(QS)


def test_never_repeats_within_session_and_exhausts():
    sel = RandomSelector()
    rng = random.Random(0)
    asked: set[str] = set()
    for _ in range(len(QS)):
        q = sel.next_question(QS, SelectionHistory({}, frozenset(asked)), rng)
        assert q.id not in asked
        asked.add(q.id)
    assert sel.next_question(QS, SelectionHistory({}, frozenset(asked)), rng) is None
    assert sel.next_question([], SelectionHistory(), rng) is None


def test_seeded_is_reproducible():
    sel = RandomSelector()
    a = [sel.next_question(QS, SelectionHistory(), random.Random(42)).id for _ in range(3)]
    assert len(set(a)) == 1
