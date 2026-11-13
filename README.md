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

## Profile sync
Builds `data/profile.json` (public-safe: no phone numbers or emails) from your resume
`content.yaml` and portfolio website, set via `RESUME_CONTENT_PATH` and `SITE_PATH` in `.env`:

```bash
python -m prep.profile.sync
```

The previous profile is snapshotted to `data/local/snapshots/`, and added/removed/changed entity
ids go to `data/local/profile_changes.json`. Entries that are the same thing under different
names can be merged in `data/profile_aliases.yaml`.

## Test
```bash
pytest
ruff check .
```

## License
MIT — see [LICENSE](LICENSE).
