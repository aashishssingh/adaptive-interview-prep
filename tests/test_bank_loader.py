import pytest

from prep.bank.loader import BankError, filter_questions, load_bank, load_bank_with_errors
from tests.bank_helpers import all_types, free_text, write_bank


@pytest.fixture
def bank(tmp_path):
    qs = all_types("alpha")
    qs[0]["role"], qs[0]["difficulty"] = "mle", 2
    qs[1]["role"], qs[1]["difficulty"] = "both", 9
    beta = [free_text("beta-0001", difficulty=7), free_text("beta-0002", role="mle")]
    qdir, _ = write_bank(tmp_path, {"alpha": qs, "beta": beta})
    return load_bank(qdir)


def test_load_bank(bank):
    assert len(bank) == 7
    assert {q.topic for q in bank} == {"alpha", "beta"}


def test_filter_role_includes_both_by_default(bank):
    assert {q.role for q in filter_questions(bank, role="ds")} == {"ds", "both"}
    assert {q.role for q in filter_questions(bank, role="ds", include_both=False)} == {"ds"}
    assert {q.id for q in filter_questions(bank, role="both")} == {"alpha-0002"}
    with pytest.raises(ValueError):
        filter_questions(bank, role="de")


def test_filter_topic_type_difficulty(bank):
    assert len(filter_questions(bank, topic="beta")) == 2
    assert len(filter_questions(bank, topic=["alpha", "beta"])) == 7
    assert [q.id for q in filter_questions(bank, type="coding_sql")] == ["alpha-0005"]
    assert {q.id for q in filter_questions(bank, difficulty=(7, 10))} == {"alpha-0002", "beta-0001"}
    assert {q.id for q in filter_questions(bank, difficulty=(2, 2))} == {"alpha-0001"}
    combo = filter_questions(bank, role="mle", topic="beta", difficulty=(1, 5))
    assert [q.id for q in combo] == ["beta-0002"]
    with pytest.raises(ValueError):
        filter_questions(bank, difficulty=(6, 4))


def test_duplicate_ids_across_files(tmp_path):
    qdir, _ = write_bank(
        tmp_path,
        {"alpha": [free_text("alpha-0001")], "gamma": [free_text("alpha-0001", topic="alpha")]},
    )
    qs, errors = load_bank_with_errors(qdir)
    # second file fails the topic/file-name check before the duplicate check
    assert any("does not match file name" in e for e in errors)
    qdir, _ = write_bank(
        tmp_path / "b", {"alpha": [free_text("alpha-0001"), free_text("alpha-0001")]}
    )
    with pytest.raises(BankError, match="duplicate id alpha-0001"):
        load_bank(qdir)


def test_invalid_question_reported_with_id(tmp_path):
    qdir, _ = write_bank(tmp_path, {"alpha": [free_text(role="data_engineer")]})
    with pytest.raises(BankError, match="alpha-0001: role"):
        load_bank(qdir)


def test_bad_yaml_and_shape(tmp_path):
    qdir = tmp_path / "q"
    qdir.mkdir()
    (qdir / "alpha.yaml").write_text("questions: [unclosed\n")
    (qdir / "beta.yaml").write_text("- just a list\n")
    _, errors = load_bank_with_errors(qdir)
    assert any("invalid YAML" in e for e in errors)
    assert any("top-level 'questions:'" in e for e in errors)
