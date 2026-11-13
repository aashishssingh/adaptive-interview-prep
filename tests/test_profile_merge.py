from prep import meta
from prep.profile.merge import dedupe_bullets, entity_key, merge_skill_rows
from prep.profile.resume import split_items

DS, MLE, DE, CV = (
    "X_Data_Scientist",
    "X_ML_AI_Engineer",
    "X_Data_Engineer",
    "X_CV",
)


def test_role_from_sources():
    assert meta.role_from_sources([DS]) == "ds"
    assert meta.role_from_sources([DS, CV]) == "ds"
    assert meta.role_from_sources([MLE]) == "mle"
    assert meta.role_from_sources([MLE, DE]) == "mle"
    assert meta.role_from_sources([DS, MLE]) == "both"
    assert meta.role_from_sources([CV]) == "both"
    assert meta.role_from_sources([DE]) == "both"
    assert meta.role_from_sources([]) == "both"


def test_combine_roles():
    assert meta.combine_roles(["ds", "ds"]) == "ds"
    assert meta.combine_roles(["mle"]) == "mle"
    assert meta.combine_roles(["ds", "mle"]) == "both"
    assert meta.combine_roles(["ds", "both"]) == "both"
    assert meta.combine_roles([]) == "both"


def test_entity_key():
    assert entity_key("Acme Corp", "Data Intern") == "acme-corp--data-intern"
    assert entity_key("The 99-Cent Question (STATS 414)", None) == "the-99-cent-question-stats-414"


def test_dedupe_exact_whitespace_and_near():
    out = dedupe_bullets(
        [
            ("Built a churn model.", DS),
            ("Built  a churn\nmodel.", MLE),  # same after whitespace normalization
            ("Ran A/B tests on pricing pages with a two-sided t-test.", DS),
            ("Ran A/B tests on the pricing pages with a two-sided t-test.", MLE),  # near dup
            ("Something completely different.", CV),
        ]
    )
    assert [b["text"] for b in out] == [
        "Built a churn model.",
        "Ran A/B tests on the pricing pages with a two-sided t-test.",  # longest kept
        "Something completely different.",
    ]
    assert out[0]["sources"] == [DS, MLE] and out[0]["role"] == "both"
    assert out[1]["sources"] == [DS, MLE]
    assert out[2]["role"] == "both"


def test_dedupe_keeps_distinct_rewrites():
    out = dedupe_bullets(
        [
            ("Resolved 32 Jira tickets end to end, cleaning raw Excel files.", DS),
            ("Ran the intake workflow across 32 Jira tickets and bulk-loaded CRM records.", MLE),
        ]
    )
    assert [b["role"] for b in out] == ["ds", "mle"]


def test_split_items_respects_parentheses():
    assert split_items("Python (pandas, NumPy), SQL,  R ") == ["Python (pandas, NumPy)", "SQL", "R"]


def test_merge_skill_rows():
    rows = [("a", "Prog", "Python, SQL"), ("b", "Prog", "sql, PyTorch"), ("b", "Ops", "Docker")]
    assert merge_skill_rows(rows) == {"Prog": ["Python", "SQL", "PyTorch"], "Ops": ["Docker"]}
