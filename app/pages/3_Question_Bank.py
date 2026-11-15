"""Question bank browser: filter every question and practice any single one."""

from __future__ import annotations

import sys
from pathlib import Path

# Make the project importable even if the editable install's .pth file is skipped (e.g. macOS
# marks files in .venv as hidden and Python 3.12+ ignores hidden .pth files).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

from prep.meta import ROLE_STYLES, ROLES, difficulty_label
from prep.ui.components import (
    badge_text_color,
    get_bank,
    get_history,
    practice_single,
    role_label,
)

st.set_page_config(page_title="Question Bank · Adaptive Interview Prep", layout="wide")
st.title("Question Bank")

bank = get_bank()
history = get_history()
counts = history.attempt_counts()
last = history.last_outcomes()

c1, c2, c3, c4 = st.columns([2, 3, 3, 3])
roles = c1.multiselect("Role", list(ROLES), format_func=role_label, placeholder="All roles")
topics = c2.multiselect("Topic", sorted({q.topic for q in bank}), placeholder="All topics")
types = c3.multiselect("Type", sorted({q.type for q in bank}), placeholder="All types")
difficulty = c4.slider("Difficulty", 1, 10, (1, 10))
search = st.text_input("Search prompts and tags", placeholder="e.g. calibration")

rows = []
for q in bank:
    if roles and q.role not in roles:
        continue
    if topics and q.topic not in topics:
        continue
    if types and q.type not in types:
        continue
    if not difficulty[0] <= q.difficulty <= difficulty[1]:
        continue
    if search and search.lower() not in (q.prompt + " " + " ".join(q.tags)).lower():
        continue
    rows.append(
        {
            "id": q.id,
            "role": role_label(q.role),
            "difficulty": difficulty_label(q.difficulty),
            "topic": q.topic,
            "type": q.type,
            "status": q.status,
            "times attempted": counts.get(q.id, 0),
            "last outcome": last.get(q.id, "—"),
            "prompt": q.prompt[:90] + ("…" if len(q.prompt) > 90 else ""),
        }
    )

st.write(f"**{len(rows)}** of {len(bank)} questions")
if rows:
    df = pd.DataFrame(rows)
    badge_colors = {s.badge: s.color for s in ROLE_STYLES.values()}

    def color_role(value: str) -> str:
        bg = badge_colors.get(value)
        return f"background-color: {bg}; color: {badge_text_color(bg)}" if bg else ""

    st.dataframe(df.style.map(color_role, subset=["role"]), hide_index=True, width="stretch")
    pick = st.selectbox("Practice a single question", df["id"], key="bank_pick")
    if st.button("Practice this question", type="primary"):
        practice_single(pick)
