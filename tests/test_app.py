"""Streamlit AppTest smoke tests against a tiny fixture bank and a temp history DB."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from prep.history import History
from tests.bank_helpers import all_types, write_bank

APP = Path(__file__).resolve().parent.parent / "app"
TIMEOUT = 30


@pytest.fixture
def env(tmp_path, monkeypatch):
    qs = all_types("demo")  # demo-0001 free_text ... demo-0005 coding_sql
    qs[1]["follow_ups"] = ["Why is b right?"]
    qdir, _ = write_bank(tmp_path, {"demo": qs})
    db = tmp_path / "local" / "history.db"
    monkeypatch.setenv("QUESTIONS_DIR", str(qdir))
    monkeypatch.setenv("HISTORY_DB_PATH", str(db))
    monkeypatch.setenv("LLM_PROVIDER", "none")
    return {"db": db}


def run_page(name: str) -> AppTest:
    at = AppTest.from_file(str(APP / name), default_timeout=TIMEOUT)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


@pytest.mark.parametrize("page", ["Home.py", "pages/2_Progress.py", "pages/3_Question_Bank.py"])
def test_pages_load(env, page):
    at = run_page(page)
    assert at.title[0].value in {"Practice", "Progress", "Question Bank"}


def test_home_shows_match_count_and_filters(env):
    at = run_page("Home.py")
    assert any("**5** question(s) match" in m.value for m in at.markdown)
    at.multiselect(key="f_types").set_value(["multiple_choice", "coding_sql"]).run()
    assert any("**2** question(s) match" in m.value for m in at.markdown)
    at.radio(key="f_mode").set_value("Flashcards").run()
    # coding_sql is not a flashcard type, so only the multiple-choice question remains
    assert at.multiselect(key="f_types").value == ["multiple_choice"]
    assert any("**1** question(s) match" in m.value for m in at.markdown)
    at.multiselect(key="f_types").set_value([]).run()
    assert any("**2** question(s) match" in m.value for m in at.markdown)  # demo-0002 + 0003


def test_answer_multiple_choice_and_record(env):
    at = run_page("Home.py")
    at.multiselect(key="f_types").set_value(["multiple_choice"]).run()
    at.number_input(key="f_n").set_value(1).run()
    at.button[-1].click().run()  # Start session
    assert not at.exception, [e.value for e in at.exception]
    assert any("Difficulty 4/10 · Medium" in m.value for m in at.markdown)
    assert any(">DS</span>" in m.value for m in at.markdown)  # badge text visible
    radio = at.radio(key="mc_choice_demo-0002")
    correct = next(o for o in radio.options if o.endswith(". b"))
    radio.set_value(correct)
    submit = next(b for b in at.button if b.label == "Submit")
    submit.click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Correct" in s.value for s in at.success)
    at.text_area(key="fu_demo-0002_0").input("Because of reasons.")
    next(b for b in at.button if b.label == "Finish session").click().run()
    assert any("Session summary" in s.value for s in at.subheader)

    hist = History(env["db"])
    attempts = hist.attempts()
    assert len(attempts) == 1
    row = attempts.iloc[0]
    assert (row.question_id, row.outcome, row.score, row.grading_method) == (
        "demo-0002",
        "correct",
        1.0,
        "auto",
    )
    assert "Because of reasons." in row.followup_answers_json
    assert hist.sessions().iloc[0]["ended_at"] is not None


def test_progress_and_bank_show_recorded_attempt(env):
    hist = History(env["db"])
    from prep.bank.loader import load_bank
    from prep.bank.schema import question_hash
    from prep.history import now_iso

    q = next(
        q for q in load_bank(Path(env["db"]).parent.parent / "questions") if q.id == "demo-0001"
    )
    hist.record_attempt(
        session_id=None,
        question=q,
        question_hash=question_hash(q),
        started_at=now_iso(),
        submitted_at=now_iso(),
        duration_sec=3,
        answer_text="",
        score=0.0,
        outcome="incorrect",
        hints_used=0,
        grading_method="rubric_self",
    )
    at = run_page("pages/2_Progress.py")
    assert at.metric[0].value == "1"
    assert at.selectbox(key="retry_pick").value == "demo-0001"
    at = run_page("pages/3_Question_Bank.py")
    assert any("**5** of 5 questions" in m.value for m in at.markdown)


def test_single_question_from_other_page(env):
    at = AppTest.from_file(str(APP / "Home.py"), default_timeout=TIMEOUT)
    at.session_state["practice_single"] = "demo-0003"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("demo-0003" in m.value for m in at.markdown)


def start_single(qid: str) -> AppTest:
    at = AppTest.from_file(str(APP / "Home.py"), default_timeout=TIMEOUT)
    at.session_state["practice_single"] = qid
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def click(at: AppTest, label: str) -> AppTest:
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def only_attempt(env):
    attempts = History(env["db"]).attempts()
    assert len(attempts) == 1
    return attempts.iloc[0]


def test_free_text_rubric_flow(env):
    at = start_single("demo-0001")
    at.text_area(key="ft_text_demo-0001").input("My answer")
    click(at, "Show model answer and rubric")
    at.checkbox(key="rub_demo-0001_0").check()
    at.checkbox(key="rub_demo-0001_2").check()
    click(at, "Submit self-grade")
    row = only_attempt(env)
    assert row.grading_method == "rubric_self" and abs(row.score - 2 / 3) < 1e-9
    assert row.outcome == "partial" and row.answer_text == "My answer"


def test_short_answer_self_grade_flow(env):
    at = start_single("demo-0003")
    at.text_input(key="sa_text_demo-0003").input("42")
    click(at, "Reveal answer")
    assert any("Answer: 42" in s.value for s in at.success)
    click(at, "Partly")
    row = only_attempt(env)
    assert (row.grading_method, row.score, row.outcome) == ("self", 0.5, "partial")


def test_hints_are_counted(env, tmp_path, monkeypatch):
    qs = all_types("demo")
    qs[2]["hints"] = ["first hint", "second hint"]
    qdir, _ = write_bank(tmp_path / "h", {"demo": qs})
    monkeypatch.setenv("QUESTIONS_DIR", str(qdir))
    at = start_single("demo-0003")
    click(at, "Show hint (1/2)")
    click(at, "Show hint (2/2)")
    assert [i.value for i in at.info][-2:] == ["Hint 1: first hint", "Hint 2: second hint"]
    click(at, "Reveal answer")
    click(at, "Got it")
    assert only_attempt(env).hints_used == 2


def test_python_run_then_submit(env):
    at = start_single("demo-0004")
    at.text_area(key="py_code_demo-0004").input("def add(a, b):\n    return a - b\n")
    click(at, "Run tests (not saved)")
    assert History(env["db"]).attempts().empty  # previews are not recorded
    assert any("Passed 0/4 tests" in m.value for m in at.markdown)
    at.text_area(key="py_code_demo-0004").input(
        "def add(a, b):\n    if a is None:\n        raise ValueError\n    return a + b\n"
    )
    click(at, "Submit")
    row = only_attempt(env)
    assert (row.grading_method, row.score, row.outcome) == ("auto", 1.0, "correct")


def test_sql_wrong_then_right(env):
    at = start_single("demo-0005")
    assert any("Dataset: tiny" in e.label for e in at.expander)
    at.text_area(key="sql_q_demo-0005").input("SELECT label FROM nums")
    click(at, "Run query (not saved)")
    assert any("Wrong columns" in e.value for e in at.error)
    at.text_area(key="sql_q_demo-0005").input("SELECT label, COUNT(*) FROM nums GROUP BY label")
    click(at, "Submit")
    row = only_attempt(env)
    assert (row.score, row.outcome) == (1.0, "correct")


def test_flashcards_flow(env):
    at = run_page("Home.py")
    at.radio(key="f_mode").set_value("Flashcards").run()
    at.number_input(key="f_n").set_value(2).run()
    click(at, "Start session")
    for _ in range(2):
        click(at, "Reveal answer")
        click(at, "Got it")
        label = (
            "Finish session"
            if any(b.label == "Finish session" for b in at.button)
            else "Next question"
        )
        click(at, label)
    assert any("Session summary" in s.value for s in at.subheader)
    attempts = History(env["db"]).attempts()
    assert sorted(attempts["question_id"]) == ["demo-0002", "demo-0003"]
    assert set(attempts["grading_method"]) == {"self"}


def test_every_real_question_renders(tmp_path, monkeypatch):
    from prep.bank.loader import QUESTIONS_DIR, load_bank

    monkeypatch.setenv("QUESTIONS_DIR", str(QUESTIONS_DIR))
    monkeypatch.setenv("HISTORY_DB_PATH", str(tmp_path / "h.db"))
    for q in load_bank(QUESTIONS_DIR):
        at = AppTest.from_file(str(APP / "Home.py"), default_timeout=TIMEOUT)
        at.session_state["practice_single"] = q.id
        at.run()
        assert not at.exception, (q.id, [e.value for e in at.exception])
        assert any(q.id in m.value for m in at.markdown), q.id


@pytest.mark.parametrize("page", ["Home.py", "pages/2_Progress.py", "pages/3_Question_Bank.py"])
def test_pages_do_not_rely_on_editable_install(page):
    """Each page must put the project root on sys.path before importing prep: on macOS the
    editable install's .pth can be hidden and skipped, and `streamlit run` does not add the
    repo root to sys.path."""
    src = (APP / page).read_text()
    assert src.index("sys.path.insert(0, str(_ROOT))") < src.index("from prep")
    depth = int(src.split("parents[")[1][0])
    assert (APP / page).resolve().parents[depth] == APP.parent
