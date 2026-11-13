import pytest

from prep.profile.pii import find_pii, scrub, strip_pii


@pytest.mark.parametrize(
    "text",
    [
        "(555) 010-0199",
        "555-010-0199",
        "555.010.0199",
        "555 010 0199",
        "+1 555 010 0199",
        "5550100199",
        "jane.doe@example.com",
        "mailto:jane.doe@example.com",
        "first.last+tag@sub.example.co.uk",
    ],
)
def test_strips_pii(text):
    cleaned, n = strip_pii(f"Call or write: {text} today.")
    assert n == 1
    assert find_pii(cleaned) == []
    assert "Call or write:" in cleaned and "today." in cleaned


@pytest.mark.parametrize(
    "text",
    [
        "7.17M hourly candles across 839,613 markets",
        "satellite imagery (2020 to 2023)",
        "95% CI 0.010 to 0.022, Brier score 0.04624",
        "Aug 2024 — May 2025",
        "2,600-label gold standard from 3,851 reports and 7,466 images",
        "bootstrap (B = 2,000)",
    ],
)
def test_no_false_positives(text):
    assert strip_pii(text) == (text, 0)


def test_scrub_nested():
    obj = {"a": ["x 555-010-0199", {"b": "y@example.com"}], "n": 3}
    clean, n = scrub(obj)
    assert n == 2
    assert clean == {"a": ["x", {"b": ""}], "n": 3}
