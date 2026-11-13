import pytest

from prep import meta


def test_role_styles():
    assert meta.ROLE_STYLES["ds"] == meta.RoleStyle("#0072B2", "DS")
    assert meta.ROLE_STYLES["mle"] == meta.RoleStyle("#E69F00", "MLE")
    assert meta.ROLE_STYLES["both"] == meta.RoleStyle("#CC79A7", "DS + MLE")
    assert set(meta.ROLE_STYLES) == set(meta.ROLES)
    for style in meta.ROLE_STYLES.values():
        assert style.badge  # never color alone


@pytest.mark.parametrize("role", ["ds", "mle", "both"])
def test_valid_roles(role):
    assert meta.validate_role(role) == role
    assert meta.role_style(role) is meta.ROLE_STYLES[role]


@pytest.mark.parametrize("role", ["de", "DS", "", None, 1, "ds ", "data_engineer"])
def test_invalid_roles(role):
    with pytest.raises(ValueError):
        meta.validate_role(role)


@pytest.mark.parametrize(
    "d,band",
    [
        (1, "Easy"),
        (2, "Easy"),
        (3, "Easy"),
        (4, "Medium"),
        (5, "Medium"),
        (6, "Medium"),
        (7, "Hard"),
        (8, "Hard"),
        (9, "Expert"),
        (10, "Expert"),
    ],
)
def test_difficulty_band(d, band):
    assert meta.validate_difficulty(d) == d
    assert meta.difficulty_band(d) == band


@pytest.mark.parametrize("d", [0, 11, -1, 5.0, 5.5, "5", None, True, False])
def test_invalid_difficulty(d):
    with pytest.raises(ValueError):
        meta.validate_difficulty(d)
    with pytest.raises(ValueError):
        meta.difficulty_band(d)


def test_difficulty_label():
    assert meta.difficulty_label(7) == "Difficulty 7/10 · Hard"
