"""Progress: attempts over time, accuracy by topic / band / role, and missed questions."""

from __future__ import annotations

import sys
from pathlib import Path

# Make the project importable even if the editable install's .pth file is skipped (e.g. macOS
# marks files in .venv as hidden and Python 3.12+ ignores hidden .pth files).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import altair as alt
import pandas as pd
import streamlit as st

from prep.bank.loader import by_id
from prep.meta import DIFFICULTY_BANDS, ROLE_STYLES, ROLES, difficulty_label
from prep.ui.components import get_bank, get_history, practice_single, role_label

st.set_page_config(page_title="Progress · Adaptive Interview Prep", layout="wide")
st.title("Progress")

history = get_history()
questions = by_id(get_bank())
attempts = history.attempts()

if attempts.empty:
    st.info("No attempts yet. Answer some questions on the Practice page first.")
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("Attempts", len(attempts))
c2.metric("Questions practiced", attempts["question_id"].nunique())
c3.metric("Mean score", f"{attempts['score'].mean():.0%}")

st.subheader("Attempts over time")
attempts["date"] = pd.to_datetime(attempts["submitted_at"]).dt.date
daily = (
    attempts.groupby("date")
    .agg(attempts=("id", "count"), mean_score=("score", "mean"))
    .reset_index()
)
base = alt.Chart(daily).encode(x=alt.X("date:T", title="Date"))
bars = base.mark_bar(opacity=0.6).encode(y=alt.Y("attempts:Q", title="Attempts"))
line = base.mark_line(point=True, color="#000000").encode(
    y=alt.Y("mean_score:Q", title="Mean score", scale=alt.Scale(domain=[0, 1]))
)
st.altair_chart(alt.layer(bars, line).resolve_scale(y="independent"), width="stretch")


def accuracy_chart(
    df: pd.DataFrame, column: str, order: list[str] | None = None, color: alt.Color | None = None
) -> alt.Chart:
    enc = {
        "x": alt.X(
            "pct_correct:Q",
            title="Share correct",
            scale=alt.Scale(domain=[0, 1]),
            axis=alt.Axis(format="%"),
        ),
        "y": alt.Y(f"{column}:N", title=None, sort=order),
        "tooltip": [
            column,
            "attempts",
            alt.Tooltip("mean_score:Q", format=".2f"),
            alt.Tooltip("pct_correct:Q", format=".0%"),
        ],
    }
    if color is not None:
        enc["color"] = color
    chart = alt.Chart(df).mark_bar().encode(**enc)
    labels = (
        alt.Chart(df)
        .mark_text(align="left", dx=4)
        .encode(
            x="pct_correct:Q",
            y=alt.Y(f"{column}:N", sort=order),
            text=alt.Text("attempts:Q", format="d"),
        )
    )
    return chart + labels


left, right = st.columns(2)
with left:
    st.subheader("Accuracy by topic")
    st.caption("Bar labels show the number of attempts.")
    by_topic = history.accuracy_by("topic")
    st.altair_chart(accuracy_chart(by_topic, "topic"), width="stretch")
with right:
    st.subheader("Accuracy by difficulty band")
    band_order = [label for _lo, _hi, label in DIFFICULTY_BANDS]
    st.altair_chart(
        accuracy_chart(history.accuracy_by("band"), "band", band_order), width="stretch"
    )

    st.subheader("Accuracy by role")
    by_role = history.accuracy_by("role")
    by_role["role_badge"] = [role_label(r) for r in by_role["role"]]
    role_order = [ROLE_STYLES[r].badge for r in ROLES]
    role_color = alt.Color(
        "role_badge:N",
        scale=alt.Scale(domain=role_order, range=[ROLE_STYLES[r].color for r in ROLES]),
        legend=alt.Legend(title="Role"),
    )
    st.altair_chart(accuracy_chart(by_role, "role_badge", role_order, role_color), width="stretch")

st.subheader("Missed questions")
st.caption("Questions whose most recent attempt was incorrect or partial.")
missed = history.missed_questions()
missed = missed[missed["question_id"].isin(questions)]
if missed.empty:
    st.success("Nothing to retry. Every question's latest attempt was correct.")
else:
    table = pd.DataFrame(
        {
            "id": missed["question_id"],
            "role": [role_label(r) for r in missed["role"]],
            "difficulty": [difficulty_label(int(d)) for d in missed["difficulty"]],
            "topic": missed["topic"],
            "type": missed["type"],
            "last outcome": missed["outcome"],
            "last attempted": pd.to_datetime(missed["submitted_at"]).dt.strftime("%Y-%m-%d %H:%M"),
        }
    )
    st.dataframe(table, hide_index=True, width="stretch")
    pick = st.selectbox("Retry a question", table["id"], key="retry_pick")
    if st.button("Retry this question", type="primary"):
        practice_single(pick)
