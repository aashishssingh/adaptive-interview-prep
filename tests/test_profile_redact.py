from prep.profile.redact import load_names, name_patterns, redact, redact_text, surviving_names

PATS = name_patterns(["Pat Example", "Robin Sample", "Dana Advisor", "Lee, Q."])


def test_full_names_and_collapse():
    text, n = redact_text("With teammates Pat Example and Robin Sample, built X.", PATS)
    assert text == "With teammates [names], built X."
    assert n == 2


def test_single_name():
    assert redact_text("Committee chair: Dana Advisor.", PATS) == ("Committee chair: [name].", 1)


def test_citation_rewritten_to_et_al():
    text, n = redact_text(
        "Example, P., Person, T., and Sample, R. (2024, Jun). Fake Study. Report.", PATS
    )
    assert text == "Person, T. et al. (2024, Jun). Fake Study. Report."
    assert n == 2


def test_citation_form_entry_matches_both_forms():
    assert redact_text("Lee, Q. (2024). Paper.", PATS)[0] == "Co-authored (2024). Paper."
    assert redact_text("Thanks to Quinn Lee.", PATS)[0] == "Thanks to [name]."


def test_no_false_positives_on_places():
    pats = name_patterns(["Paris, Z."])
    for text in ["Lab (UC Paris)", "Paris, France", "Paris, TX", "at UC Paris, Z team"]:
        assert redact_text(text, pats) == (text, 0)


def test_redact_nested_and_survivors():
    obj = {"a": ["Pat Example said hi", {"b": "Sample, R. (2020). T."}], "n": 1}
    clean, n = redact(obj, PATS)
    assert n == 2
    assert surviving_names(str(clean), PATS) == []


def test_load_names(tmp_path):
    f = tmp_path / "names.txt"
    f.write_text("# comment\nPat Example\n\n  Lee, Q.  # trailing\n")
    assert load_names(f) == ["Pat Example", "Lee, Q."]
    assert load_names(tmp_path / "missing.txt") == []
