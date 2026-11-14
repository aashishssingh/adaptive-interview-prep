# adaptive-interview-prep

A local Streamlit app for practicing **Data Scientist** and **ML/AI Engineer** interviews and
online assessments.

## The adaptive idea
Every question is tagged with a role (DS, MLE, or both) and an authored difficulty from 1 to 10.
As you answer, the app learns per-topic skill estimates and an *observed* difficulty for each
question, then picks questions near the edge of your ability, mixes in spaced repetition, and
generates follow-ups grounded in your own projects (via an optional LLM). It works without an LLM
too (`LLM_PROVIDER=none`).

See [docs/PLAN.md](docs/PLAN.md) for the roadmap.

## Setup
Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # then edit paths / keys
```

## Run
```bash
streamlit run app/Home.py
```
Everything works offline with `LLM_PROVIDER=none`. Practice history is stored locally in
`data/local/history.db` (gitignored).

### Practice (Home)
- **Sidebar filters:** track (Data Scientist = DS + both, ML/AI Engineer = MLE + both, or All),
  "Only role-specific questions" (drops DS + MLE questions), topics, difficulty range, question
  types and number of questions. The page shows how many questions match before you start.
- **Modes:** *Practice* covers every question type. *Flashcards* uses short-answer and
  multiple-choice questions with a one-click reveal and a quick Got it / Partly / Missed
  self-grade.
- **Question card:** role badge (color plus text), "Difficulty N/10 · Band", topic, estimated
  time, a live timer, and hints revealed one at a time (counted in your history).
- **Grading:**
  - *Multiple choice:* options are shuffled each attempt and auto-graded.
  - *Python:* runs your function against the test cases in an isolated subprocess (5 s
    limit). "Run tests" previews without saving; "Submit" records the attempt.
  - *SQL:* runs your query on the question's DuckDB dataset and compares it with the reference
    result by position (row order only when required). Expand the dataset panel for tables,
    columns and sample rows.
  - *Free text:* compare with the model answer and tick the rubric points you covered.
  - *Short answer:* reveal the answer and grade yourself.
- **After grading:** the explanation and "Interviewer follow-up" prompts, with optional
  answers that are saved but not graded. Each session ends with a summary by topic and role.

### Progress
Attempts and mean score over time, and accuracy by topic, difficulty band and role. The
Progress page also lists missed questions (latest attempt incorrect or partial), each with a
**Retry** button.

### Question Bank
Browse and search all questions with role, difficulty, topic, type, times attempted and last
outcome. Pick any question and click **Practice this question**.

### Troubleshooting
On macOS, files inside `.venv` can carry the "hidden" flag, which makes Python 3.12+ skip the
editable install's `.pth` file. The app pages handle this themselves. If `python -m prep...`
fails with `No module named 'prep'` outside the repo root, run:
```bash
chflags nohidden .venv/lib/python3.*/site-packages/__editable__*.pth
```

## Profile sync
Builds `data/profile.json` (public-safe: no phone numbers or emails) from your resume
`content.yaml` and portfolio website, set via `RESUME_CONTENT_PATH` and `SITE_PATH` in `.env`:

```bash
python -m prep.profile.sync
```

The previous profile is snapshotted to `data/local/snapshots/`, and added/removed/changed entity
ids go to `data/local/profile_changes.json`. Entries that are the same thing under different
names can be merged in `data/profile_aliases.yaml`.

## Question bank
Questions live in `data/questions/<topic>.yaml` (schema: `prep/bank/schema.py`); shared SQL
practice datasets live in `data/questions/datasets/*.sql`. Validate the bank (schema, unique ids,
runs every Python reference solution and SQL reference query, prints coverage):

```bash
python -m prep.bank.validate
```

## Test
```bash
pytest
ruff check .
```

## License
MIT — see [LICENSE](LICENSE).
