"""Question metadata conventions: role and difficulty.

- ``role`` is one of "ds", "mle", "both".
- ``difficulty`` is an integer from 1 (easiest) to 10.

The UI must always show the text badge next to the role color, never color alone.
Colors are from the colorblind-safe Okabe-Ito palette.
"""

from __future__ import annotations

from dataclasses import dataclass

ROLES: tuple[str, ...] = ("ds", "mle", "both")

DIFFICULTY_MIN = 1
DIFFICULTY_MAX = 10


@dataclass(frozen=True)
class RoleStyle:
    color: str
    badge: str


ROLE_STYLES: dict[str, RoleStyle] = {
    "ds": RoleStyle(color="#0072B2", badge="DS"),
    "mle": RoleStyle(color="#E69F00", badge="MLE"),
    "both": RoleStyle(color="#CC79A7", badge="DS + MLE"),
}

# (low, high, label), inclusive bounds
DIFFICULTY_BANDS: tuple[tuple[int, int, str], ...] = (
    (1, 3, "Easy"),
    (4, 6, "Medium"),
    (7, 8, "Hard"),
    (9, 10, "Expert"),
)


def validate_role(role: object) -> str:
    """Return ``role`` if it is a valid role, else raise ValueError."""
    if not isinstance(role, str) or role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}, got {role!r}")
    return role


def validate_difficulty(difficulty: object) -> int:
    """Return ``difficulty`` if it is an int in 1..10, else raise ValueError.

    Booleans, floats and numeric strings are rejected.
    """
    if isinstance(difficulty, bool) or not isinstance(difficulty, int):
        raise ValueError(f"difficulty must be an int, got {difficulty!r}")
    if not DIFFICULTY_MIN <= difficulty <= DIFFICULTY_MAX:
        raise ValueError(
            f"difficulty must be in {DIFFICULTY_MIN}..{DIFFICULTY_MAX}, got {difficulty}"
        )
    return difficulty


def difficulty_band(difficulty: int) -> str:
    """Map a difficulty (1-10) to Easy / Medium / Hard / Expert."""
    d = validate_difficulty(difficulty)
    for low, high, label in DIFFICULTY_BANDS:
        if low <= d <= high:
            return label
    raise AssertionError("unreachable: bands cover 1..10")


def role_style(role: str) -> RoleStyle:
    return ROLE_STYLES[validate_role(role)]


def difficulty_label(difficulty: int) -> str:
    """Display string, e.g. ``"Difficulty 7/10 · Hard"``."""
    d = validate_difficulty(difficulty)
    return f"Difficulty {d}/{DIFFICULTY_MAX} · {difficulty_band(d)}"


# --- role from resume sources -------------------------------------------------------------
# Project-based questions get their role from which resumes a source bullet appears on.
DS_DOCUMENT_SUFFIX = "Data_Scientist"
MLE_DOCUMENT_SUFFIX = "ML_AI_Engineer"


def role_from_sources(sources: list[str] | set[str] | tuple[str, ...]) -> str:
    """Only on a Data_Scientist resume -> "ds"; only on ML_AI_Engineer -> "mle";
    on both of them, or on neither (e.g. CV-only) -> "both"."""
    on_ds = any(s.endswith(DS_DOCUMENT_SUFFIX) for s in sources)
    on_mle = any(s.endswith(MLE_DOCUMENT_SUFFIX) for s in sources)
    if on_ds and not on_mle:
        return "ds"
    if on_mle and not on_ds:
        return "mle"
    return "both"


def combine_roles(roles: list[str] | set[str] | tuple[str, ...]) -> str:
    """"ds" or "mle" if every role is that value, otherwise (including empty) "both"."""
    distinct = {validate_role(r) for r in roles}
    if len(distinct) == 1:
        return distinct.pop()
    return "both"
