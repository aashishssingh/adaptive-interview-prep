"""Reusable Streamlit pieces. Colors always come with a visible text badge."""

from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

from prep.bank.loader import BankError, load_bank
from prep.bank.schema import Question
from prep.config import load_settings
from prep.history import History
from prep.meta import ROLE_STYLES, difficulty_label, role_style

MONOSPACE_CSS = """
<style>
textarea { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace !important; }
</style>
"""


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    rgb = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast_ratio(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def badge_text_color(background: str) -> str:
    """Black or white, whichever contrasts more with the badge background."""
    white = contrast_ratio(background, "#FFFFFF")
    black = contrast_ratio(background, "#000000")
    return "#FFFFFF" if white >= black else "#000000"


def role_badge_html(role: str) -> str:
    style = role_style(role)
    return (
        f'<span style="background:{style.color};color:{badge_text_color(style.color)};'
        "padding:2px 10px;border-radius:999px;font-weight:600;font-size:0.85em;"
        f'white-space:nowrap" title="role: {html.escape(role)}">{html.escape(style.badge)}</span>'
    )


def role_label(role: str) -> str:
    return ROLE_STYLES[role].badge


@st.cache_resource(show_spinner=False)
def _cached_bank(questions_dir: str, mtime_key: float) -> list[Question]:
    return load_bank(Path(questions_dir))


def _dir_mtime(path: Path) -> float:
    return max((p.stat().st_mtime for p in path.glob("*.yaml")), default=0.0)


def get_bank() -> list[Question]:
    """Load (and cache) the bank; stops the page with an error if it is invalid."""
    qdir = load_settings().questions_dir
    try:
        return _cached_bank(str(qdir), _dir_mtime(qdir))
    except BankError as e:
        st.error("The question bank has errors. Run `python -m prep.bank.validate`.")
        st.code("\n".join(e.errors[:20]))
        st.stop()


def datasets_dir() -> Path:
    return load_settings().questions_dir / "datasets"


def get_history() -> History:
    return History(load_settings().history_db_path)


def question_header(q: Question) -> None:
    st.markdown(
        f"{role_badge_html(q.role)} &nbsp; **{difficulty_label(q.difficulty)}** &nbsp;·&nbsp; "
        f"{html.escape(q.topic.replace('_', ' '))} / {html.escape(q.subtopic)} &nbsp;·&nbsp; "
        f"~{q.est_minutes} min &nbsp;·&nbsp; `{q.id}`",
        unsafe_allow_html=True,
    )


def practice_single(question_id: str) -> None:
    """Close any session in progress, then open the Practice page on one question."""
    run = st.session_state.get("run")
    if run and not run.get("done"):
        get_history().end_session(run["session_id"])
    st.session_state["run"] = None
    st.session_state["cur"] = None
    st.session_state["practice_single"] = question_id
    st.switch_page("Home.py")
