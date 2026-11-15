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

### Review (generated questions)
Generated project questions start as drafts. The Review page groups them by project and shows
each question's depth, role, difficulty, model answer or answer guidance, and the profile facts
it came from. **Approve** or **Reject** each one, or **Approve all** for a project; decisions
are written back to the YAML file. Questions marked 🖐 *Needs your input* have no model answer:
a strong answer needs details only you know. After answering one in Practice, save
**Your real answer** (stored locally in `data/local/history.db`, never committed). Practice uses
only approved questions unless you tick **Include drafts**. Use the **Source** filter
(Foundational / My projects / Both) and the **Projects** picker to choose what to practice.

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

## Generate project questions (LLM)
Turns `data/profile.json` into interview questions about your own projects. This is the only
part of the app that needs an LLM. Configure `LLM_PROVIDER` (`anthropic` by default, or
`openai`) and the models `LLM_MODEL_DEEP` / `LLM_MODEL_FAST`.

For Anthropic, either run `ant auth login` (CLI sign-in; leave `ANTHROPIC_API_KEY` unset) or set
`ANTHROPIC_API_KEY`. Settings report which one is in use (`api key`, `CLI sign-in` or `none`)
without printing secrets.

```bash
python -m prep.generate.projects --dry-run                # plan, token and cost estimate; no API calls
python -m prep.generate.projects --entity vetology --yes  # one project (id or short slug)
python -m prep.generate.projects --changed-only           # only entities changed by the last profile sync
```

Without `--yes` the command shows the estimate and asks before spending. Each entity takes two
calls: one groups bullets and paraphrases into facts (`data/generated/facts/`), and one writes
questions at four depths (explain, justify, challenge, extend) into
`data/generated/projects/<entity>.yaml` as drafts.
- **Grounding:** answers may only use profile facts. Questions needing information the profile
  lacks are marked "needs your input" with answer guidance, and numbers not found in the profile
  are flagged for review.
- **Regeneration:** questions that are no longer produced are retired, never deleted.
- **Caching:** responses are cached in `data/local/llm_cache/`, so identical reruns are free.
  Usage is logged to `data/local/llm_usage.jsonl`.

## Test
```bash
pytest
ruff check .
```

## License
MIT — see [LICENSE](LICENSE).
