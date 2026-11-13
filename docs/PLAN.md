# Roadmap

- [x] **Phase 0 — Skeleton**: package layout, config, question metadata conventions (`prep/meta.py`), tests, docs.
- [x] **Phase 1 — Profile sync**: resume `content.yaml` + website pages → `data/profile.json` (`python -m prep.profile.sync`; change log in `data/local/profile_changes.json`).
- [ ] **Phase 2 — Foundational question bank + schema**.
- [ ] **Phase 3 — Streamlit practice UI + SQLite history**: each question card shows the role badge/color and "Difficulty N/10 · Band"; filters by role and difficulty range.
- [ ] **Phase 4 — LLM project-question generator**: explain / justify / challenge / extend depths.
- [ ] **Phase 5 — Adaptive engine v1**: per-topic skill estimates, observed difficulty, selection near the edge of ability, spaced repetition, randomization.
- [ ] **Phase 6 — Adaptive engine v2**: LLM variants, follow-up chains, rubric grading feeding v1.
- [ ] **Phase 7 — Mock interview mode + timed assessment mode** with Python/SQL execution (DuckDB).
- [ ] **Phase 8 — Polish**: tests, README screenshots, offline demo mode.
- [ ] **Later**: spoken answers.
