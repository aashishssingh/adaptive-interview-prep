"""Question selection. The UI only talks to a Selector, so Phase 5 can swap in the adaptive
engine without UI changes."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from prep.bank.schema import Question


@dataclass(frozen=True)
class SelectionHistory:
    """What a selector may know about past practice.

    last_outcome: question id -> outcome of its most recent attempt (any session).
    asked_this_session: question ids already shown in the current session.
    """

    last_outcome: dict[str, str] = field(default_factory=dict)
    asked_this_session: frozenset[str] = frozenset()


@runtime_checkable
class Selector(Protocol):
    def next_question(
        self, candidates: Sequence[Question], history: SelectionHistory, rng: random.Random
    ) -> Question | None:
        """Return the next question, or None when no eligible candidate remains."""
        ...


class RandomSelector:
    """Unseen questions first, then ones last answered incorrect or partial, then the rest.
    Never repeats a question within a session. Random within each tier."""

    def next_question(
        self, candidates: Sequence[Question], history: SelectionHistory, rng: random.Random
    ) -> Question | None:
        pool = [q for q in candidates if q.id not in history.asked_this_session]
        if not pool:
            return None
        unseen = [q for q in pool if q.id not in history.last_outcome]
        missed = [q for q in pool if history.last_outcome.get(q.id) in ("incorrect", "partial")]
        tier = unseen or missed or pool
        tier = sorted(tier, key=lambda q: q.id)  # deterministic order before the seeded draw
        return rng.choice(tier)
