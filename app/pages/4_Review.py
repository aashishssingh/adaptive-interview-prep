"""Review generated project questions: approve or reject drafts (written back to YAML)."""

from __future__ import annotations

import sys
from pathlib import Path

# Make the project importable even if the editable install's .pth file is skipped (e.g. macOS
# marks files in .venv as hidden and Python 3.12+ ignores hidden .pth files).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from collections import Counter

import streamlit as st

from prep.bank.schema import Question
from prep.generate.store import set_status
from prep.meta import difficulty_label
from prep.ui.components import (
    NEEDS_INPUT_MARKER,
    entity_name,
    generated_dir,
    get_bank,
    load_facts,
    role_badge_html,
)

st.set_page_config(page_title="Review · Adaptive Interview Prep", layout="wide")
st.title("Review generated questions")

bank = get_bank()
generated = [q for q in bank if q.source == "generated"]
if not generated:
    st.info("No generated questions yet. Run `python -m prep.generate.projects` to create them.")
    st.stop()

statuses = st.multiselect(
    "Show status",
    ["draft", "approved", "rejected", "retired"],
    default=["draft"],
    key="review_status",
)
only_input = st.checkbox(f"Only {NEEDS_INPUT_MARKER} questions", key="review_only_input")
shown = [q for q in generated if q.status in statuses and (not only_input or q.needs_user_input)]
counts = Counter(q.status for q in generated)
st.caption(
    " · ".join(f"{s}: {counts.get(s, 0)}" for s in ("draft", "approved", "rejected", "retired"))
)
if not shown:
    st.success("Nothing to review with these filters.")
    st.stop()


def write_status(entity_id: str, ids: list[str], status: str) -> None:
    set_status(generated_dir() / f"{entity_id}.yaml", ids, status)
    st.rerun()


def render_question(q: Question, facts: dict[str, str]) -> None:
    with st.container(border=True):
        marker = f" &nbsp; **{NEEDS_INPUT_MARKER}**" if q.needs_user_input else ""
        depth = f"depth: *{q.depth}* &nbsp;·&nbsp; " if q.depth else ""
        st.markdown(
            f"{role_badge_html(q.role)} &nbsp; **{difficulty_label(q.difficulty)}** &nbsp;·&nbsp; "
            f"{depth}{q.type} &nbsp;·&nbsp; `{q.id}` &nbsp;·&nbsp; *{q.status}*{marker}",
            unsafe_allow_html=True,
        )
        st.markdown(f"**{q.prompt}**")
        for note in q.review_notes:
            st.warning(note)
        if q.type == "free_text":
            if q.model_answer:
                st.markdown(f"**Model answer.** {q.model_answer}")
            if q.answer_guidance:
                st.markdown(f"**Answer guidance.** {q.answer_guidance}")
            st.markdown("**Rubric**\n" + "\n".join(f"- {p}" for p in q.rubric))
        elif q.type == "multiple_choice":
            for i, opt in enumerate(q.options):
                mark = "✓" if i == q.answer_index else "·"
                st.markdown(f"{mark} {chr(65 + i)}. {opt}")
            st.markdown(f"**Explanation.** {q.explanation}")
        else:
            st.markdown(f"**Answer.** {q.answer}")
            st.markdown(f"**Explanation.** {q.explanation}")
        if q.follow_ups:
            st.markdown("**Follow-ups:** " + " / ".join(q.follow_ups))
        with st.expander("Source facts"):
            for fid in q.fact_ids:
                st.markdown(f"- `{fid}` {facts.get(fid, '(fact not found)')}")
        c1, c2, _ = st.columns([1, 1, 6])
        if q.status != "approved" and c1.button("Approve", key=f"approve_{q.id}", type="primary"):
            write_status(q.entity_id, [q.id], "approved")
        if q.status != "rejected" and c2.button("Reject", key=f"reject_{q.id}"):
            write_status(q.entity_id, [q.id], "rejected")


for entity_id in sorted({q.entity_id for q in shown}, key=entity_name):
    items = [q for q in shown if q.entity_id == entity_id]
    drafts = [q.id for q in items if q.status == "draft"]
    st.subheader(f"{entity_name(entity_id)} ({len(items)})")
    if drafts and st.button(
        f"Approve all {len(drafts)} drafts for this entity", key=f"approve_all_{entity_id}"
    ):
        write_status(entity_id, drafts, "approved")
    facts = load_facts(entity_id)
    for q in sorted(items, key=lambda q: (q.depth or "", q.difficulty, q.id)):
        render_question(q, facts)
