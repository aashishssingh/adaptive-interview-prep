# Roadmap

- [x] **Phase 0 — Skeleton**: package layout, config, question metadata conventions (`prep/meta.py`), tests, docs.
- [x] **Phase 1 — Profile sync**: resume `content.yaml` + website pages → `data/profile.json` (`python -m prep.profile.sync`; change log in `data/local/profile_changes.json`).
- [x] **Phase 1.1 — Role rule**: a question's role comes from what it tests; resume provenance (`sources`/`role` on profile bullets) is only a hint.
- [x] **Phase 2 — Foundational question bank + schema**: pydantic schema (`prep/bank/schema.py`), loader/filters, `python -m prep.bank.validate`, 3 SQL datasets, 163 authored questions across 12 topics.
- [x] **Phase 3 — Streamlit practice UI + SQLite history**: each question card shows the role badge/color and "Difficulty N/10 · Band"; filters by role and difficulty range.
- [ ] **Phase 4 — LLM project-question generator**: explain / justify / challenge / extend depths. *In progress:* LLM gateway (Anthropic CLI sign-in or API key, OpenAI, cache, usage log, repair retry), generator with grounding checks, Review page and Practice source filters are done; Vetology generated (48 drafts awaiting review). Remaining entities wait for approval.
  - The generator assigns each question's role from what the question tests (ds = statistics, experimentation, analysis, interpreting/communicating results; mle = building, deploying, scaling or evaluating ML/LLM systems and engineering practices; both = genuinely both). The bullet's `sources`/`role` in profile.json is passed as a hint only.
  - Paraphrased bullets of the same fact across resumes (kept as separate bullets in profile.json) are treated as one fact, so they don't produce duplicate questions.
- [ ] **Phase 5 — Adaptive engine v1**: per-topic skill estimates, observed difficulty, selection near the edge of ability, spaced repetition, randomization.
- [ ] **Phase 6 — Adaptive engine v2**: LLM variants, follow-up chains, rubric grading feeding v1.
- [ ] **Phase 7 — Mock interview mode + timed assessment mode** with Python/SQL execution (DuckDB).
- [ ] **Phase 8 — Polish**: tests, README screenshots, offline demo mode.
- [ ] **Later**: spoken answers.
