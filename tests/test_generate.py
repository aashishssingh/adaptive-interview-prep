"""Generator pipeline tests on a fixture profile, with FakeProvider only (no network)."""

import json
from pathlib import Path

import pytest
import yaml

from prep.bank.loader import load_bank
from prep.bank.validate import check_generated_facts
from prep.generate import projects as gen
from prep.generate.prompts import BEHAVIORAL_SYSTEM, FACTS_SYSTEM, QUESTIONS_SYSTEM
from prep.llm import FakeProvider, LLMClient

DS, MLE, CV = "X_Data_Scientist", "X_ML_AI_Engineer", "X_CV"
PROJECT = "demo-churn-project"
JOB = "corner-cafe--shift-lead"


def profile():
    return {
        "documents": [DS, MLE, CV],
        "entities": [
            {
                "id": PROJECT,
                "type": "project",
                "org": "Demo Churn Project",
                "title": None,
                "date": "Mar 2025",
                "role": "both",
                "content_hash": "hash-1",
                "bullets": [
                    {
                        "text": "Built a churn model on 12,000 members with gradient boosting.",
                        "sources": [DS],
                        "role": "ds",
                    },
                    {
                        "text": "Trained a gradient boosting churn model on 12,000 members.",
                        "sources": [MLE],
                        "role": "mle",
                    },
                    {
                        "text": "Deployed the model as a nightly batch job.",
                        "sources": [MLE],
                        "role": "mle",
                    },
                ],
                "website": {"page": "demo.html", "heading": "Demo", "text": "AUC was 0.81."},
            },
            {
                "id": JOB,
                "type": "additional_experience",
                "org": "Corner Cafe",
                "title": "Shift Lead",
                "date": "2020",
                "role": "both",
                "content_hash": "hash-2",
                "bullets": [
                    {
                        "text": "Trained new staff and handled opening shifts.",
                        "sources": [CV],
                        "role": "both",
                    }
                ],
                "website": None,
            },
            {
                "id": "some-university--b-s",
                "type": "education",
                "org": "Some University",
                "title": "B.S.",
                "date": "2024",
                "role": "both",
                "content_hash": "h3",
                "bullets": [],
                "website": None,
            },
        ],
    }


FACTS = {
    "facts": [
        {
            "statement": "Built a gradient boosting churn model on 12,000 members.",
            "source_bullets": [0, 1],
            "uses_website_text": False,
            "substantive": True,
        },
        {
            "statement": "Deployed the model as a nightly batch job.",
            "source_bullets": [2, 99],
            "uses_website_text": False,
            "substantive": True,
        },
        {
            "statement": "Has no traceable source.",
            "source_bullets": [42],
            "uses_website_text": False,
            "substantive": False,
        },
    ]
}


EMPTY = {
    "hints": [],
    "follow_ups": [],
    "needs_user_input": False,
    "answer_guidance": None,
    "model_answer": None,
    "rubric": [],
    "options": [],
    "answer_index": None,
    "answer": None,
    "explanation": None,
    "depth": None,
}


def q(prompt, depth="explain", difficulty=3, fact_ids=("demo-f01",), **kw):
    base = {
        **EMPTY,
        "fact_ids": list(fact_ids),
        "depth": depth,
        "type": "free_text",
        "role": "ds",
        "difficulty": difficulty,
        "prompt": prompt,
        "tags": ["churn"],
        "est_minutes": 4,
        "model_answer": "You built a gradient boosting churn model on 12,000 members.",
        "rubric": ["names the model", "states the data size", "explains the purpose"],
        "follow_ups": ["What would you change?"],
    }
    base.update(kw)
    return base


QUESTIONS = {
    "questions": [
        q("Walk me through the churn model you built for the demo project."),
        q("Walk me through the churn model you built for the demo project!"),  # near duplicate
        q(
            "Why did you choose gradient boosting over logistic regression for churn?",
            depth="justify",
            difficulty=5,
            needs_user_input=True,
            model_answer=None,
            answer_guidance="Explain your real reason; use the 12,000-member data size.",
        ),
        q("How would you detect leakage in the churn labels?", depth="challenge", difficulty=4),
        q(
            "How would you monitor the nightly batch job in production?",
            depth="extend",
            difficulty=8,
            fact_ids=["demo-f02"],
            role="mle",
            model_answer="Track the 97% uptime you achieved and alert on drift.",
            rubric=["data drift", "job failures", "score distribution"],
        ),
        q(
            "Tell me about Pat Example's contribution to the model.",
            depth="explain",
            model_answer="Pat Example did the feature engineering for the model.",
        ),
        q("Which fact is this?", fact_ids=["demo-f99"]),
        {
            **EMPTY,
            "fact_ids": ["demo-f01"],
            "depth": "explain",
            "type": "multiple_choice",
            "role": "ds",
            "difficulty": 3,
            "prompt": "How many members did the churn model use?",
            "tags": ["data"],
            "est_minutes": 1,
            "options": ["12,000", "1,200", "120,000", "500"],
            "answer_index": 0,
            "explanation": "The model was trained on 12,000 members; 1,200 is off by 10x.",
        },
    ]
}

BEHAVIORAL = {
    "questions": [
        {
            **EMPTY,
            "fact_ids": ["corner-cafe-f01"],
            "type": "free_text",
            "role": "both",
            "difficulty": 4,
            "prompt": "Tell me about a time you trained a new team member.",
            "tags": ["training"],
            "est_minutes": 5,
            "needs_user_input": True,
            "answer_guidance": "Use a specific shift; cover situation, actions, and the result.",
            "rubric": ["situation", "actions", "result"],
        },
    ]
}


def responder(facts=FACTS, questions=QUESTIONS, behavioral=BEHAVIORAL):
    def respond(system, user, model, schema):
        if system == FACTS_SYSTEM:
            if "Corner Cafe" in user:
                return {
                    "facts": [
                        {
                            "statement": "Trained new staff and handled opening shifts.",
                            "source_bullets": [0],
                            "uses_website_text": False,
                            "substantive": True,
                        }
                    ]
                }
            return facts
        if system == QUESTIONS_SYSTEM:
            return questions
        if system == BEHAVIORAL_SYSTEM:
            return behavioral
        raise AssertionError("unexpected system prompt")

    return respond


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL_DEEP", "claude-sonnet-5-5")
    paths = gen.Paths(
        profile=tmp_path / "data" / "profile.json",
        generated=tmp_path / "data" / "generated",
        local=tmp_path / "data" / "local",
    )
    paths.profile.parent.mkdir(parents=True)
    paths.profile.write_text(json.dumps(profile()))
    paths.generated.mkdir(parents=True)
    paths.entities_config.write_text(
        yaml.safe_dump({"entities": {PROJECT: {"slug": "demo", "priority": "high"}}})
    )
    paths.local.mkdir(parents=True)
    (paths.local / "redact_names.txt").write_text("Pat Example\n")
    (tmp_path / "data" / "questions").mkdir()
    return paths


def run(paths, args, fake, confirm=input):
    client = LLMClient(
        fake, cache_dir=paths.local / "llm_cache", usage_log=paths.local / "llm_usage.jsonl"
    )
    return gen.main(args, paths=paths, client_factory=lambda: client, confirm=confirm)


def load_questions(paths, entity_id):
    return yaml.safe_load((paths.projects / f"{entity_id}.yaml").read_text())["questions"]


def test_dry_run_makes_zero_provider_calls(env, capsys):
    fake = FakeProvider(responses=responder())

    def never():
        raise AssertionError("client must not be created on a dry run")

    assert gen.main(["--dry-run"], paths=env, client_factory=never) == 0
    out = capsys.readouterr().out
    assert "Dry run: no API calls made." in out and "TOTAL" in out
    assert PROJECT in out and JOB in out and "some-university" not in out  # education skipped
    assert fake.calls == []


def test_declining_confirmation_spends_nothing(env):
    fake = FakeProvider(responses=responder())
    assert run(env, [], fake, confirm=lambda _: "n") == 1
    assert fake.calls == [] and not env.projects.exists()


def test_facts_pipeline(env):
    fake = FakeProvider(responses=responder())
    assert run(env, ["--entity", "demo", "--yes"], fake) == 0
    facts = json.loads((env.facts / f"{PROJECT}.json").read_text())
    assert facts["profile_hash"] == "hash-1" and facts["generated_by"] == "claude-sonnet-5-5"
    f1, f2 = facts["facts"]  # the fact with no traceable source is dropped
    assert (f1["fact_id"], f1["source_bullets"], f1["role_hint"]) == ("demo-f01", [0, 1], "both")
    assert (f2["fact_id"], f2["source_bullets"], f2["role_hint"]) == ("demo-f02", [2], "mle")
    assert "paraphrase" in fake.calls[0]["system"].lower()
    assert "[1] (MLE resume) Trained" in fake.calls[0]["user"]  # provenance shown to the model


def test_question_pipeline_checks(env, capsys):
    fake = FakeProvider(responses=responder())
    assert run(env, ["--entity", PROJECT, "--yes"], fake) == 0
    qs = load_questions(env, PROJECT)
    prompts = [x["prompt"] for x in qs]
    assert len(qs) == 6  # near-duplicate and unknown-fact questions dropped
    assert not any(p.endswith("project!") for p in prompts)
    assert [x["id"] for x in qs] == [f"proj-demo-{i:04d}" for i in range(1, 7)]
    assert all(
        x["status"] == "draft"
        and x["source"] == "generated"
        and x["topic"] == "projects"
        and x["subtopic"] == PROJECT
        for x in qs
    )
    challenge = next(x for x in qs if x.get("depth") == "challenge")
    assert challenge["difficulty"] == 6  # clamped into the challenge range 6-9
    report = capsys.readouterr().out
    assert "duplicates dropped 1" in report and "unknown fact_ids 1" in report
    bank = load_bank(env.generated.parent / "questions")
    assert len(bank) == 6
    assert check_generated_facts(bank, env.generated.parent / "questions") == []


def test_grounding_marker_and_number_check(env):
    run(env, ["--entity", PROJECT, "--yes"], FakeProvider(responses=responder()))
    qs = {x["prompt"][:20]: x for x in load_questions(env, PROJECT)}
    justify = qs["Why did you choose g"]
    assert justify["needs_user_input"] is True and "model_answer" not in justify
    assert "12,000-member" in justify["answer_guidance"]
    extend = qs["How would you monito"]
    assert any("97" in n for n in extend["review_notes"])  # 97% is not in the profile
    mc = qs["How many members did"]
    assert "review_notes" not in mc  # distractor numbers in options are not flagged
    explain = qs["Walk me through the "]
    assert "review_notes" not in explain  # 12,000 is grounded in the profile


def test_names_removed_from_generated_text(env):
    run(env, ["--entity", PROJECT, "--yes"], FakeProvider(responses=responder()))
    text = (env.projects / f"{PROJECT}.yaml").read_text()
    assert "Pat Example" not in text and "[name]" in text


def test_behavioral_entities(env):
    assert run(env, ["--entity", JOB, "--yes"], FakeProvider(responses=responder())) == 0
    (b,) = load_questions(env, JOB)
    assert b["topic"] == "behavioral" and "depth" not in b and b["needs_user_input"]
    assert b["id"] == "proj-corner-cafe-0001"  # automatic slug


def test_regeneration_retires_and_keeps_ids(env):
    run(env, ["--entity", PROJECT, "--yes"], FakeProvider(responses=responder()))
    first = {x["prompt"]: x for x in load_questions(env, PROJECT)}
    from prep.generate.store import set_status

    keep_id = first["How would you detect leakage in the churn labels?"]["id"]
    set_status(env.projects / f"{PROJECT}.yaml", keep_id, "approved")

    new_questions = {
        "questions": [
            q("How would you detect leakage in the churn labels?", depth="challenge", difficulty=6),
            q(
                "How would you monitor the nightly batch job in production?",
                depth="extend",
                difficulty=7,
                fact_ids=["demo-f02"],
                role="mle",
                model_answer="Alert on job failures and on drift in the score distribution.",
                rubric=["data drift", "job failures", "score distribution"],
            ),
            q(
                "What baseline did you compare the churn model against?",
                depth="challenge",
                difficulty=7,
            ),
        ]
    }
    changed = (
        json.dumps(profile())
        .replace("hash-1", "hash-1b")
        .replace(
            "Deployed the model as a nightly batch job.",
            "Deployed the model as a nightly batch job with alerting.",
        )
    )
    env.profile.write_text(changed)
    (env.local / "profile_changes.json").write_text(
        json.dumps({"added": [], "removed": [], "changed": [PROJECT, "some-university--b-s"]})
    )
    assert (
        run(
            env,
            ["--changed-only", "--yes"],
            FakeProvider(responses=responder(questions=new_questions)),
        )
        == 0
    )
    after = {x["prompt"]: x for x in load_questions(env, PROJECT)}
    leak = after["How would you detect leakage in the churn labels?"]
    assert leak["id"] == keep_id and leak["status"] == "approved"  # unchanged content
    monitor = after["How would you monitor the nightly batch job in production?"]
    assert monitor["id"] == first[monitor["prompt"]]["id"] and monitor["status"] == "draft"
    assert after["What baseline did you compare the churn model against?"]["id"] == "proj-demo-0007"
    retired = [p for p, x in after.items() if x["status"] == "retired"]
    assert len(retired) == 4 and len(after) == 7  # nothing deleted
    assert not (env.projects / "some-university--b-s.yaml").exists()  # education never generated


def test_removed_entity_is_retired(env):
    run(env, ["--entity", JOB, "--yes"], FakeProvider(responses=responder()))
    (env.local / "profile_changes.json").write_text(
        json.dumps({"added": [], "changed": [], "removed": [JOB]})
    )
    fake = FakeProvider(responses=responder())
    assert run(env, ["--changed-only", "--yes"], fake) == 0
    assert fake.calls == []
    assert [x["status"] for x in load_questions(env, JOB)] == ["retired"]
    assert (env.projects / f"{JOB}.yaml").exists()


def test_rerun_is_served_from_cache(env):
    fake = FakeProvider(responses=responder())
    run(env, ["--entity", PROJECT, "--yes"], fake)
    n = len(fake.calls)
    run(env, ["--entity", PROJECT, "--yes"], fake)
    assert len(fake.calls) == n  # identical prompts: no new provider calls
    log = [json.loads(x) for x in (env.local / "llm_usage.jsonl").read_text().splitlines()]
    assert [r["cached"] for r in log] == [False, False, True, True]


def test_unknown_entity(env):
    with pytest.raises(SystemExit, match="Unknown"):
        gen.main(["--entity", "nope", "--dry-run"], paths=env)


def test_real_entities_config_covers_profile():
    from prep.generate.projects import PROFILE_PATH, Paths, eligible, load_entity_config

    config = load_entity_config(Paths())
    ids = {e["id"] for e in json.loads(Path(PROFILE_PATH).read_text())["entities"] if eligible(e)}
    assert ids <= set(config)
    assert len({v["slug"] for v in config.values()}) == len(config)  # slugs are unique


def test_prompt_states_explicit_total():
    from prep.generate.prompts import question_target

    facts = [{"substantive": True}] * 3 + [{"substantive": False}]
    assert question_target(facts, (6, 8), behavioral=False) == (18, 25)
    assert question_target(facts, (6, 8), behavioral=True) == (3, 5)


def test_output_schema_requires_every_field():
    from prep.generate.models import GenQuestionOut
    from prep.llm.client import json_schema_for

    item = json_schema_for(GenQuestionOut)
    assert set(item["required"]) == set(GenQuestionOut.model_fields)
