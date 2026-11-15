"""Practice page: filtered practice sessions and flashcards. Works with LLM_PROVIDER=none."""

from __future__ import annotations

import sys
from pathlib import Path

# Make the project importable even if the editable install's .pth file is skipped (e.g. macOS
# marks files in .venv as hidden and Python 3.12+ ignores hidden .pth files).
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import random
import time

import pandas as pd
import streamlit as st

from prep import grading
from prep.bank.loader import by_id
from prep.bank.schema import Question, question_hash
from prep.engine.selector import RandomSelector, SelectionHistory, Selector
from prep.history import now_iso
from prep.practice import (
    FLASHCARD_TYPES,
    MODES,
    SOURCES,
    TRACKS,
    format_duration,
    matching_questions,
    summarize,
)
from prep.ui.components import (
    MONOSPACE_CSS,
    NEEDS_INPUT_MARKER,
    datasets_dir,
    entity_name,
    get_bank,
    get_history,
    question_header,
    role_label,
)

st.set_page_config(page_title="Practice · Adaptive Interview Prep", layout="wide")

SELECTOR: Selector = RandomSelector()
ALL_TYPES = ["free_text", "multiple_choice", "short_answer", "coding_python", "coding_sql"]

bank = get_bank()
questions_by_id = by_id(bank)
history = get_history()
ss = st.session_state
ss.setdefault("run", None)
ss.setdefault("cur", None)


# --- session lifecycle -----------------------------------------------------------------------


def start_run(candidates: list[Question], n_target: int, mode: str, filters: dict) -> None:
    seed = random.randrange(1_000_000_000)
    ss.run = {
        "session_id": history.start_session(mode, {**filters, "seed": seed}),
        "mode": mode,
        "candidate_ids": [q.id for q in candidates],
        "n_target": n_target,
        "asked": [],
        "results": [],
        "seed": seed,
        "done": False,
    }
    ss.cur = None


def finish_run() -> None:
    if ss.run and not ss.run["done"]:
        history.end_session(ss.run["session_id"])
        ss.run["done"] = True
    ss.cur = None


def next_question() -> None:
    run = ss.run
    if len(run["asked"]) >= run["n_target"]:
        finish_run()
        return
    candidates = [questions_by_id[i] for i in run["candidate_ids"] if i in questions_by_id]
    hist = SelectionHistory(history.last_outcomes(), frozenset(run["asked"]))
    rng = random.Random(run["seed"] + len(run["asked"]))
    q = SELECTOR.next_question(candidates, hist, rng)
    if q is None:
        finish_run()
        return
    run["asked"].append(q.id)
    ss.cur = {
        "qid": q.id,
        "started_at": now_iso(),
        "t0": time.time(),
        "hints": 0,
        "order": grading.shuffle_options(q, seed=rng.randrange(1_000_000))
        if q.type == "multiple_choice"
        else None,
        "revealed": False,
        "answer_text": "",
        "grade": None,
        "attempt_id": None,
        "preview": None,
    }


def record(q: Question, grade: grading.GradeResult, answer_text: str) -> None:
    cur, run = ss.cur, ss.run
    duration = time.time() - cur["t0"]
    cur["attempt_id"] = history.record_attempt(
        session_id=run["session_id"],
        question=q,
        question_hash=question_hash(q),
        started_at=cur["started_at"],
        submitted_at=now_iso(),
        duration_sec=duration,
        answer_text=answer_text,
        score=grade.score,
        outcome=grade.outcome,
        hints_used=cur["hints"],
        grading_method=grade.method,
    )
    cur["grade"] = grade
    cur["answer_text"] = answer_text
    run["results"].append(
        {
            "question_id": q.id,
            "topic": q.topic,
            "role": q.role,
            "score": grade.score,
            "outcome": grade.outcome,
            "duration_sec": duration,
        }
    )


# --- sidebar filters ------------------------------------------------------------------------

with st.sidebar:
    st.header("Session setup")
    track = st.radio("Track", list(TRACKS), index=2, key="f_track")
    only_specific = st.checkbox(
        "Only role-specific questions",
        key="f_only_specific",
        help="Drops questions tagged DS + MLE.",
    )
    topics_all = sorted({q.topic for q in bank})
    topics = st.multiselect(
        "Topics",
        topics_all,
        key="f_topics",
        format_func=lambda t: t.replace("_", " "),
        placeholder="All topics",
    )
    difficulty = st.slider("Difficulty", 1, 10, (1, 10), key="f_difficulty")
    mode = st.radio(
        "Mode",
        MODES,
        key="f_mode",
        horizontal=True,
        help="Flashcards use short-answer and multiple-choice questions only.",
    )
    type_options = list(FLASHCARD_TYPES) if mode == "Flashcards" else ALL_TYPES
    types = st.multiselect("Question types", type_options, key="f_types", placeholder="All types")
    source = st.radio(
        "Source",
        SOURCES,
        index=2,
        key="f_source",
        horizontal=True,
        help="Foundational = the authored bank; My projects = generated questions "
        "about your own work.",
    )
    include_drafts = st.checkbox(
        "Include drafts",
        key="f_drafts",
        help="Also practice generated questions you have not reviewed on the Review page.",
    )
    projects: list[str] = []
    if source != "Foundational":
        allowed = {"approved", "draft"} if include_drafts else {"approved"}
        project_ids = sorted(
            {q.entity_id for q in bank if q.source == "generated" and q.status in allowed}
        )
        if project_ids:
            projects = st.multiselect(
                "Projects",
                project_ids,
                key="f_projects",
                format_func=entity_name,
                placeholder="All projects",
            )
        else:
            st.caption(
                "No project questions available yet. Generate them, then approve them on "
                "the Review page (or tick Include drafts)."
            )
    n_questions = st.number_input("Number of questions", 1, 100, 10, key="f_n")

filters = {
    "track": track,
    "only_role_specific": only_specific,
    "topics": topics,
    "difficulty": list(difficulty),
    "types": types,
    "mode": mode,
    "source": source,
    "projects": projects,
    "include_drafts": include_drafts,
}
matches = matching_questions(
    bank,
    track,
    only_specific,
    topics,
    difficulty,
    types,
    mode,
    source=source,
    entities=projects,
    include_drafts=include_drafts,
)

# A single question requested from the Progress or Question Bank page.
single = ss.pop("practice_single", None)
if single and single in questions_by_id:
    start_run([questions_by_id[single]], 1, "Practice", {"single_question": single})


# --- renderers ------------------------------------------------------------------------------


def render_hints(q: Question) -> None:
    cur = ss.cur
    for i in range(cur["hints"]):
        st.info(f"Hint {i + 1}: {q.hints[i]}")
    if cur["grade"] is None and cur["hints"] < len(q.hints):
        if st.button(f"Show hint ({cur['hints'] + 1}/{len(q.hints)})", key=f"hint_{q.id}"):
            cur["hints"] += 1
            st.rerun()


@st.fragment(run_every=1)
def elapsed_timer() -> None:
    cur = ss.get("cur")
    if cur and cur.get("grade") is None:
        st.caption(f"⏱ Elapsed {format_duration(time.time() - cur['t0'])}")


def self_grade_buttons(q: Question, answer_text: str) -> None:
    st.write("How did you do?")
    cols = st.columns(3)
    for col, (key, label) in zip(
        cols, [("got_it", "Got it"), ("partly", "Partly"), ("missed", "Missed")], strict=True
    ):
        if col.button(label, key=f"sg_{key}_{q.id}", width="stretch"):
            g = (
                grading.grade_short_answer(q, key)
                if q.type == "short_answer"
                else grading.grade_self(key)
            )
            record(q, g, answer_text)
            st.rerun()


def render_multiple_choice(q: Question, flashcard: bool) -> None:
    cur = ss.cur
    order = cur["order"]
    if flashcard:
        for pos, idx in enumerate(order):
            st.markdown(f"**{chr(65 + pos)}.** {q.options[idx]}")
        if not cur["revealed"]:
            if st.button("Reveal answer", key=f"reveal_{q.id}", type="primary"):
                cur["revealed"] = True
                st.rerun()
            return
        st.success(f"Answer: {chr(65 + order.index(q.answer_index))}. {q.options[q.answer_index]}")
        st.markdown(q.explanation)
        if cur["grade"] is None:
            self_grade_buttons(q, "")
        return
    if cur["grade"] is None:
        with st.form(f"mc_{q.id}"):
            labels = [f"{chr(65 + pos)}. {q.options[idx]}" for pos, idx in enumerate(order)]
            choice = st.radio("Choose one", labels, index=None, key=f"mc_choice_{q.id}")
            if st.form_submit_button("Submit", type="primary"):
                if choice is None:
                    st.warning("Pick an option first.")
                else:
                    original = order[labels.index(choice)]
                    record(q, grading.grade_multiple_choice(q, original), q.options[original])
                    st.rerun()
        return
    g = cur["grade"]
    if g.outcome == "correct":
        st.success(f"Correct: {g.details['answer']}")
    else:
        st.error(f"Not quite. You chose: {g.details['chosen']}")
        st.success(f"Correct answer: {g.details['answer']}")


def render_short_answer(q: Question, flashcard: bool) -> None:
    cur = ss.cur
    if not cur["revealed"]:
        with st.form(f"sa_{q.id}"):
            text = "" if flashcard else st.text_input("Your answer", key=f"sa_text_{q.id}")
            if st.form_submit_button("Reveal answer", type="primary"):
                cur["revealed"] = True
                cur["answer_text"] = text
                st.rerun()
        return
    if cur["answer_text"]:
        st.markdown(f"**Your answer:** {cur['answer_text']}")
    st.success(f"Answer: {q.answer}")
    st.markdown(q.explanation)
    if cur["grade"] is None:
        self_grade_buttons(q, cur["answer_text"])


def render_free_text(q: Question) -> None:
    cur = ss.cur
    if not cur["revealed"]:
        with st.form(f"ft_{q.id}"):
            text = st.text_area("Your answer", height=220, key=f"ft_text_{q.id}")
            if st.form_submit_button("Show model answer and rubric", type="primary"):
                cur["revealed"] = True
                cur["answer_text"] = text
                st.rerun()
        return
    if cur["answer_text"]:
        with st.expander("Your answer", expanded=True):
            st.markdown(cur["answer_text"])
    if q.model_answer:
        with st.expander("Model answer", expanded=True):
            st.markdown(q.model_answer)
    else:
        with st.expander(f"{NEEDS_INPUT_MARKER}: answer guidance", expanded=True):
            st.caption(
                "There is no model answer: a strong answer needs details from your own "
                "experience that your profile does not contain."
            )
            st.markdown(q.answer_guidance or "")
    if cur["grade"] is None:
        with st.form(f"rubric_{q.id}"):
            st.write("Tick each rubric point your answer covered:")
            ticked = [
                i for i, point in enumerate(q.rubric) if st.checkbox(point, key=f"rub_{q.id}_{i}")
            ]
            if st.form_submit_button("Submit self-grade", type="primary"):
                record(q, grading.grade_free_text(q, ticked), cur["answer_text"])
                st.rerun()
    else:
        g = cur["grade"]
        st.write(f"Rubric points hit: {len(g.details['hit'])}/{len(q.rubric)}")
        for p in g.details["missed"]:
            st.markdown(f"- ✗ {p}")


def _python_results(g: grading.GradeResult) -> None:
    if g.details.get("load_error"):
        st.error("Your code could not be loaded.")
        st.code(g.details["load_error"], language="text")
        return
    st.write(f"Passed {g.details['passed']}/{g.details['total']} tests")
    rows = [
        {
            "test": t["index"] + 1,
            "result": "✓ pass" if t["passed"] else "✗ fail",
            "args": str(t["args"] or t["kwargs"])[:120],
            "expected": str(t["expected"])[:120],
            "actual": str(t["actual"])[:120],
        }
        for t in g.details["tests"]
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    for t in g.details["tests"]:
        if t.get("error") or t.get("stdout"):
            with st.expander(f"Test {t['index'] + 1} output"):
                if t.get("stdout"):
                    st.code(t["stdout"], language="text")
                if t.get("error"):
                    st.code(t["error"], language="text")


def render_coding_python(q: Question) -> None:
    cur = ss.cur
    st.markdown(MONOSPACE_CSS, unsafe_allow_html=True)
    if cur["grade"] is None:
        with st.form(f"py_{q.id}"):
            code = st.text_area(
                "Your code", value=q.starter_code, height=320, key=f"py_code_{q.id}"
            )
            c1, c2 = st.columns(2)
            run = c1.form_submit_button("Run tests (not saved)")
            submit = c2.form_submit_button("Submit", type="primary")
        if run or submit:
            with st.spinner("Running tests…"):
                g = grading.grade_python(q, code)
            if submit:
                record(q, g, code)
                st.rerun()
            cur["preview"] = g
        if cur.get("preview") is not None:
            _python_results(cur["preview"])
        return
    _python_results(cur["grade"])
    with st.expander("Reference solution"):
        st.code(q.reference_solution, language="python")


def _sql_table(columns: list[str], rows: list[tuple]) -> None:
    labels = [f"{i + 1}: {c}" for i, c in enumerate(columns)]  # duplicate-safe headers
    st.dataframe(pd.DataFrame(rows, columns=labels), hide_index=True, width="stretch")


def _sql_results(g: grading.GradeResult) -> None:
    d = g.details
    if d.get("error"):
        st.error(d["error"])
    elif g.score == 1.0:
        st.success(d["reason"])
    else:
        st.error(d["reason"])
    c1, c2 = st.columns(2)
    with c1:
        if "user_columns" in d:
            st.caption(f"Your result ({d['user_row_count']} rows, first 50 shown)")
            _sql_table(d["user_columns"], d["user_rows"])
    with c2:
        st.caption(f"Expected result ({d['expected_row_count']} rows, first 50 shown)")
        _sql_table(d["expected_columns"], d["expected_rows"])


def render_dataset(q: Question) -> None:
    with st.expander(f"Dataset: {q.dataset} (tables, columns, first 5 rows)"):
        preview = grading.dataset_preview(q.dataset, datasets_dir())
        for table, info in preview.items():
            cols = ", ".join(f"{c} {t}" for c, t in info["columns"])
            st.markdown(f"**{table}** ({info['row_count']} rows): `{cols}`")
            st.dataframe(
                pd.DataFrame(info["rows"], columns=[c for c, _ in info["columns"]]),
                hide_index=True,
                width="stretch",
            )


def render_coding_sql(q: Question) -> None:
    cur = ss.cur
    st.markdown(MONOSPACE_CSS, unsafe_allow_html=True)
    render_dataset(q)
    st.caption(
        "Rows are compared by position, not column name."
        + (" Row order matters." if q.order_matters else " Row order is ignored.")
    )
    if cur["grade"] is None:
        with st.form(f"sql_{q.id}"):
            query = st.text_area("Your query (DuckDB SQL)", height=240, key=f"sql_q_{q.id}")
            c1, c2 = st.columns(2)
            run = c1.form_submit_button("Run query (not saved)")
            submit = c2.form_submit_button("Submit", type="primary")
        if run or submit:
            g = grading.grade_sql(q, query, datasets_dir())
            if submit:
                record(q, g, query)
                st.rerun()
            cur["preview"] = g
        if cur.get("preview") is not None:
            _sql_results(cur["preview"])
        return
    _sql_results(cur["grade"])
    with st.expander("Reference query"):
        st.code(q.reference_query, language="sql")


def render_needs_input(q: Question) -> str | None:
    """For "needs your input" questions: guidance plus a box for your real answer."""
    if not q.needs_user_input:
        return None
    st.markdown(f"#### {NEEDS_INPUT_MARKER}")
    if q.type != "free_text" or q.model_answer:
        st.info(q.answer_guidance or "")
    real = st.text_area(
        "Your real answer",
        value=history.own_answer(q.id) or "",
        key=f"real_{q.id}",
        height=160,
        help="Saved only on this computer (data/local/history.db), never committed.",
    )
    if st.button("Save my real answer", key=f"save_real_{q.id}"):
        save_real_answer(q, real)
        st.success("Saved.")
    return real


def save_real_answer(q: Question, text: str | None) -> None:
    if q.needs_user_input and text and text.strip() and text != history.own_answer(q.id):
        history.save_own_answer(q.id, text)


def render_after_grading(q: Question) -> None:
    cur = ss.cur
    g = cur["grade"]
    icon = {"correct": "✅", "partial": "🟡", "incorrect": "❌"}[g.outcome]
    st.markdown(f"### {icon} {g.outcome.capitalize()} · score {g.score:.2f}")
    # free_text shows its model answer and short_answer / flashcards their explanation on reveal.
    shown_on_reveal = q.type in ("free_text", "short_answer") or ss.run["mode"] == "Flashcards"
    if not shown_on_reveal:
        st.markdown(f"**Explanation.** {q.explanation}")
    real_answer = render_needs_input(q)
    follow_answers: dict[str, str] = {}
    if q.follow_ups:
        st.markdown("#### Interviewer follow-up")
        for i, f in enumerate(q.follow_ups):
            follow_answers[f] = st.text_area(
                f"🗣 {f}", key=f"fu_{q.id}_{i}", height=90, placeholder="Optional: saved, not graded"
            )
    c1, c2 = st.columns(2)
    last = len(ss.run["asked"]) >= ss.run["n_target"]
    if c1.button("Finish session" if last else "Next question", type="primary", key=f"next_{q.id}"):
        if any(v.strip() for v in follow_answers.values()):
            history.save_followups(cur["attempt_id"], follow_answers)
        save_real_answer(q, real_answer)
        next_question()
        st.rerun()
    if not last and c2.button("End session", key=f"end_{q.id}"):
        if any(v.strip() for v in follow_answers.values()):
            history.save_followups(cur["attempt_id"], follow_answers)
        save_real_answer(q, real_answer)
        finish_run()
        st.rerun()


def render_question(q: Question) -> None:
    run, cur = ss.run, ss.cur
    flashcard = run["mode"] == "Flashcards"
    st.caption(f"Question {len(run['asked'])} of up to {run['n_target']} · {run['mode']}")
    question_header(q)
    elapsed_timer()
    st.markdown(q.prompt)
    render_hints(q)
    renderer = {
        "multiple_choice": lambda: render_multiple_choice(q, flashcard),
        "short_answer": lambda: render_short_answer(q, flashcard),
        "free_text": lambda: render_free_text(q),
        "coding_python": lambda: render_coding_python(q),
        "coding_sql": lambda: render_coding_sql(q),
    }[q.type]
    renderer()
    if cur["grade"] is not None:
        render_after_grading(q)
    elif st.button("End session", key=f"end_ungraded_{q.id}"):
        finish_run()
        st.rerun()


def render_summary() -> None:
    s = summarize(ss.run["results"])
    st.subheader("Session summary")
    if s["n"] == 0:
        st.info("No questions were answered in this session.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Score", f"{s['total_score']:.1f} / {s['n']}")
        c2.metric("Mean score", f"{s['mean_score']:.0%}")
        c3.metric("Total time", format_duration(s["total_time_sec"]))
        st.markdown("**By topic**")
        st.dataframe(s["by_topic"], hide_index=True, width="stretch")
        st.markdown("**By role**")
        by_role = s["by_role"].copy()
        by_role["role"] = [role_label(r) for r in by_role["role"]]
        st.dataframe(by_role, hide_index=True, width="stretch")
    if st.button("Start a new session", type="primary"):
        ss.run = None
        st.rerun()


# --- main -----------------------------------------------------------------------------------

st.title("Practice")

if ss.run is None:
    st.write(f"**{len(matches)}** question(s) match the current filters.")
    if mode == "Flashcards":
        st.caption("Flashcards: reveal with one click, then grade yourself.")
    if st.button("Start session", type="primary", disabled=not matches):
        start_run(matches, min(int(n_questions), len(matches)), mode, filters)
        next_question()
        st.rerun()
elif ss.run["done"]:
    render_summary()
else:
    if ss.cur is None:
        next_question()
        st.rerun()
    render_question(questions_by_id[ss.cur["qid"]])
