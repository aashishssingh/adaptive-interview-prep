# CLAUDE.md — project rules for adaptive-interview-prep

## Public repo: no secrets, no personal data
The GitHub repo is **public**. Treat everything committed as public.

- Never commit secrets (API keys, tokens, `.env`), phone numbers, email addresses,
  other people's names (teammates, advisors, co-authors), or anything from `data/local/`.
- Other people's names are listed privately in `data/local/redact_names.txt` (gitignored,
  never commit it) and replaced with `[name]` by the profile sync. Add new names there.
  Never put a real phone number, email, or name in code comments, tests, or fixtures: use
  obviously fake values (555 numbers, example.com, "Pat Example").
- Before every push:
  1. `git ls-files | grep -E '(^|/)\.env$'` must print nothing (and nothing under `data/local/`).
  2. Grep the diff being pushed for API-key patterns, phone numbers, and email addresses, e.g.
     ```bash
     git diff --cached   # or: git diff origin/main..HEAD (or the full tree on first push)
     ```
     piped through
     ```bash
     grep -nE 'sk-[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]+|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|\+?\(?[0-9]{3}\)?[ .-]?[0-9]{3}[ .-]?[0-9]{4}'
     ```
     Investigate every hit; fake test values must be obviously fake.
  3. Grep the same diff for every name in `data/local/redact_names.txt` (both "First Last" and
     "Last, F." forms). There must be no hits.

## Scope
- Tracks are **DS** (Data Scientist) and **MLE** (ML/AI Engineer) only. No data engineer track for now.
- Keep changes scoped to the phase being worked on.

## Question metadata
Every question has `role` and `difficulty`, as defined in `prep/meta.py`:

- `role`: `ds` | `mle` | `both`. UI shows a colorblind-safe (Okabe-Ito) color **plus** a text
  badge — never color alone: ds `#0072B2` "DS", mle `#E69F00` "MLE", both `#CC79A7` "DS + MLE".
- `difficulty`: integer 1–10 (1 easiest). Bands: 1–3 Easy, 4–6 Medium, 7–8 Hard, 9–10 Expert.
- Later phases add `observed_difficulty` learned from answer history. The authored `difficulty`
  is **never overwritten**.
- Project-based questions get their role from which resumes the source bullet appears on:
  only Data_Scientist → `ds`; only ML_AI_Engineer → `mle`; both, or neither (e.g. CV-only) → `both`.

## Engineering rules
- Every module gets pytest tests. Run `pytest` and `ruff check .` before finishing any task.
- Questions are data (YAML/JSON under `data/`), not hard-coded in Python.
- LLM calls go only through `prep/llm/` so the provider can be swapped. The app must still run
  with `LLM_PROVIDER=none`.
- Config comes from `prep/config.py` (`.env` via python-dotenv). Never print key values.

## Workflow
- When a phase is done, tick its checkbox in `docs/PLAN.md`.
- Commit with clear messages and push to `origin main` at the end of each phase (after the
  pre-push check above). Never force-push.
