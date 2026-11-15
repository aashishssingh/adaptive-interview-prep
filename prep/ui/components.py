"""Reusable Streamlit pieces. Colors always come with a visible text badge."""

from __future__ import annotations

import html
import json
from pathlib import Path

import streamlit as st

from prep.bank.loader import BankError, generated_dir_for, load_bank
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
    files = list(path.glob("*.yaml")) + list(generated_dir_for(path).glob("*.yaml"))
    return max((p.stat().st_mtime_ns for p in files), default=0) + len(files)


def get_bank() -> list[Question]:
    """Load (and cache) the authored and generated bank; stops the page on invalid files.
    The cache key changes whenever any question file changes, e.g. after a review."""
    qdir = load_settings().questions_dir
    try:
        return _cached_bank(str(qdir), _dir_mtime(qdir))
    except BankError as e:
        st.error("The question bank has errors. Run `python -m prep.bank.validate`.")
        st.code("\n".join(e.errors[:20]))
        st.stop()


def generated_dir() -> Path:
    return generated_dir_for(load_settings().questions_dir)


def facts_dir() -> Path:
    return generated_dir().parent / "facts"


@st.cache_data(show_spinner=False)
def _profile_names(profile_path: str, mtime: float) -> dict[str, str]:
    data = json.loads(Path(profile_path).read_text(encoding="utf-8"))
    names = {}
    for e in data.get("entities", []):
        names[e["id"]] = e.get("org") or e["id"]
    return names


def entity_names() -> dict[str, str]:
    """entity_id -> project / organization name from data/profile.json (empty if missing)."""
    path = load_settings().questions_dir.parent / "profile.json"
    if not path.exists():
        return {}
    return _profile_names(str(path), path.stat().st_mtime)


def entity_name(entity_id: str | None) -> str:
    if not entity_id:
        return ""
    return entity_names().get(entity_id, entity_id)


def load_facts(entity_id: str) -> dict[str, str]:
    """fact_id -> statement for one entity (empty if the facts file is missing)."""
    path = facts_dir() / f"{entity_id}.json"
    if not path.exists():
        return {}
    return {
        f["fact_id"]: f["statement"] for f in json.loads(path.read_text(encoding="utf-8"))["facts"]
    }


def datasets_dir() -> Path:
    return load_settings().questions_dir / "datasets"


def get_history() -> History:
    return History(load_settings().history_db_path)


NEEDS_INPUT_MARKER = "🖐 Needs your input"


def question_header(q: Question) -> None:
    if q.source == "generated":
        where = f"**{html.escape(entity_name(q.entity_id))}**"
        if q.depth:
            where += f" &nbsp;·&nbsp; depth: *{q.depth}*"
    else:
        where = f"{html.escape(q.topic.replace('_', ' '))} / {html.escape(q.subtopic)}"
    extra = f" &nbsp;·&nbsp; {NEEDS_INPUT_MARKER}" if q.needs_user_input else ""
    status = f" &nbsp;·&nbsp; *{q.status}*" if q.status != "approved" else ""
    st.markdown(
        f"{role_badge_html(q.role)} &nbsp; **{difficulty_label(q.difficulty)}** &nbsp;·&nbsp; "
        f"{where} &nbsp;·&nbsp; ~{q.est_minutes} min &nbsp;·&nbsp; `{q.id}`{extra}{status}",
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
