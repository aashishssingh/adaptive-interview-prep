import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from prep.profile import sync
from prep.profile.pii import find_pii

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def env(tmp_path):
    resume = tmp_path / "content.yaml"
    shutil.copy(FIXTURES / "content.yaml", resume)
    site = tmp_path / "site"
    shutil.copytree(FIXTURES / "site", site)
    return {
        "resume": resume,
        "site": site,
        "out": tmp_path / "data" / "profile.json",
        "local": tmp_path / "data" / "local",
    }


def run(env, aliases=None, now=datetime(2026, 1, 1, 12, 0, 0)):
    return sync.run_sync(
        env["resume"], env["site"], env["out"], env["local"], aliases_path=aliases, now=now
    )


def by_id(profile):
    return {e["id"]: e for e in profile["entities"]}


def test_merge_roles_and_types(env):
    report = run(env)
    p = json.loads(env["out"].read_text())
    ents = by_id(p)
    assert set(ents) == {
        "example-university--b-s-statistics",
        "acme-corp--data-intern",
        "demo-forecasting-project",
        "vision-side-project",
        "lab-of-examples--research-assistant",
        "example-datafest--volunteer-mentor",
        "corner-cafe--barista",
    }
    types = {i: e["type"] for i, e in ents.items()}
    assert types["acme-corp--data-intern"] == "experience"
    assert types["demo-forecasting-project"] == "project"
    assert types["lab-of-examples--research-assistant"] == "research"
    assert types["example-university--b-s-statistics"] == "education"
    assert types["example-datafest--volunteer-mentor"] == "service"
    assert types["corner-cafe--barista"] == "additional_experience"

    acme = ents["acme-corp--data-intern"]
    assert acme["date"] == "Jan 2025 — Present"
    roles = {b["text"]: b["role"] for b in acme["bullets"]}
    assert roles["Built a churn model in Python that cut false positives by 20%."] == "both"
    assert roles["Ran A/B tests on the pricing pages with a two-sided t-test."] == "both"
    assert roles["Wrote a weekly KPI report for the growth team."] == "ds"
    assert roles["Deployed the churn model behind a FastAPI service in Docker."] == "mle"
    assert len(acme["bullets"]) == 5  # 4 DS + 3 MLE, minus 2 duplicates
    assert acme["role"] == "both"

    demo = ents["demo-forecasting-project"]
    assert len(demo["bullets"]) == 1  # near-duplicate DS + CV bullets merged
    assert demo["bullets"][0]["text"].endswith("and a quantile loss.")
    assert demo["bullets"][0]["sources"] == ["Test_Person_Data_Scientist", "Test_Person_CV"]
    assert demo["role"] == "ds"  # on DS and CV only
    assert ents["vision-side-project"]["role"] == "mle"
    assert ents["lab-of-examples--research-assistant"]["role"] == "both"  # CV only
    assert ents["example-university--b-s-statistics"]["date"] == "May 2024"  # majority

    assert p["skills"] == {
        "Programming": ["Python (pandas, NumPy)", "SQL", "PyTorch"],
        "MLOps": ["Docker", "CI"],
    }
    assert p["coursework"] == {"Modeling": ["Regression (STATS 100)", "Bayesian Methods"]}
    assert report.skipped_archived == ["Test_Person_Data_Analyst"]


def test_archived_and_header_skipped(env):
    run(env)
    text = env["out"].read_text()
    assert "Archived" not in text
    assert "must never appear" not in text
    assert "Test Person" not in text  # header name never read
    p = json.loads(text)
    assert "Test_Person_Data_Analyst" not in p["documents"]


def test_no_pii_survives(env):
    report = run(env)
    text = env["out"].read_text()
    assert find_pii(text) == []
    assert "example.com" not in text and "555" not in text
    no_hashes = re.sub(r'"content_hash": "[0-9a-f]+"', "", text)
    assert not re.search(r"\d{3}\D{0,2}\d{3}\D?\d{4}", no_hashes)
    assert report.redactions >= 2 + 1 + 3  # bullet (2), detail page (2), general pages (3)
    acme = by_id(json.loads(text))["acme-corp--data-intern"]
    assert "Reach me at or about this report." in [b["text"] for b in acme["bullets"]]


def test_website_matching_and_text(env):
    report = run(env)
    ents = by_id(json.loads(env["out"].read_text()))
    web = ents["demo-forecasting-project"]["website"]
    assert web["page"] == "demo-forecasting.html"
    assert "We forecast weekly demand for a fake store." in web["text"]
    for hidden in ("Projects\n", "console.log", "Copyright footer", "color: red"):
        assert hidden not in web["text"]
    assert ents["vision-side-project"]["website"] is None
    assert report.unmatched_pages == ["knitting-patterns.html"]
    assert report.projects_without_page == ["vision-side-project"]
    assert report.site_cards_without_entity == ["Knitting Pattern Generator"]
    p = json.loads(env["out"].read_text())
    assert set(p["site_pages"]) == {"about", "experience", "skills", "projects"}
    assert "Nav" not in p["site_pages"]["about"]


def test_aliases(env, tmp_path):
    aliases = tmp_path / "aliases.yaml"
    aliases.write_text("aliases:\n  vision-side-project: demo-forecasting-project\n")
    run(env, aliases=aliases)
    ents = by_id(json.loads(env["out"].read_text()))
    assert "vision-side-project" not in ents
    assert ents["demo-forecasting-project"]["role"] == "both"  # ds + mle bullets


def test_change_detection(env):
    first = run(env, now=datetime(2026, 1, 1, 12, 0, 0))
    assert first.changes["first_run"] and first.snapshot is None
    old = json.loads(env["out"].read_text())

    # Unchanged rerun: no snapshot, no changes, identical output.
    again = run(env, now=datetime(2026, 1, 1, 12, 5, 0))
    assert again.snapshot is None
    assert not any(again.changes[k] for k in ("added", "removed", "changed", "skills_changed"))
    assert json.loads(env["out"].read_text()) == old

    text = env["resume"].read_text()
    text = text.replace("Made coffee.", "Made very good coffee.")  # changed
    text = text.replace("org: Vision Side Project", "org: Speech Side Project")  # removed + added
    text = text.replace('[MLOps, "Docker, CI"]', '[MLOps, "Docker, CI, Kubernetes"]')
    env["resume"].write_text(text)

    second = run(env, now=datetime(2026, 2, 3, 4, 5, 6))
    assert second.changes["added"] == ["speech-side-project"]
    assert second.changes["removed"] == ["vision-side-project"]
    assert second.changes["changed"] == ["corner-cafe--barista"]
    assert second.changes["skills_changed"] is True

    snap = env["local"] / "snapshots" / "profile-20260203T040506.json"
    assert second.snapshot == snap and json.loads(snap.read_text()) == old
    record = json.loads((env["local"] / "profile_changes.json").read_text())
    assert record["changed"] == ["corner-cafe--barista"]
    assert record["generated_at"] == "2026-02-03T04:05:06"

    new_hashes = {
        e["id"]: e["content_hash"] for e in json.loads(env["out"].read_text())["entities"]
    }
    old_hashes = {e["id"]: e["content_hash"] for e in old["entities"]}
    assert new_hashes["acme-corp--data-intern"] == old_hashes["acme-corp--data-intern"]


def test_website_change_marks_entity_changed(env):
    run(env)
    page = env["site"] / "demo-forecasting.html"
    page.write_text(page.read_text().replace("fake store", "fake bakery"))
    report = run(env, now=datetime(2026, 3, 1))
    assert report.changes["changed"] == ["demo-forecasting-project"]


def test_summary_text(env):
    report = run(env)
    out = sync.format_report(report)
    assert "all 7 entities are new" in out
    assert "knitting-patterns.html" in out


@pytest.mark.parametrize("missing,var", [("resume", "RESUME_CONTENT_PATH"), ("site", "SITE_PATH")])
def test_missing_source_names_env_var(env, missing, var):
    env[missing] = env[missing].parent / "does-not-exist"
    with pytest.raises(sync.SourceMissingError, match=var):
        run(env)


def test_main_missing_source_exit_code(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("RESUME_CONTENT_PATH", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("SITE_PATH", str(tmp_path))
    assert sync.main([]) == 2
    assert "RESUME_CONTENT_PATH" in capsys.readouterr().err
