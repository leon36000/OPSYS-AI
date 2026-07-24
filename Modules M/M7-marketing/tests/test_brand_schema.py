import datetime

import pytest

import brand_schema


MINIMAL_PROFILE = {
    "name": "OPSYS-AI",
    "tagline": "Systèmes complets d'automatisation d'entreprise par intelligence artificielle",
    "tone": "professionnel, factuel, français d'abord",
    "colors": ["#000000", "#FFFFFF"],
    "langue": "fr",
}


def test_validate_profile_returns_normalized_copy():
    result = brand_schema.validate_profile(MINIMAL_PROFILE.copy())

    assert isinstance(result, dict)
    assert result is not MINIMAL_PROFILE
    assert result == {
        "name": "OPSYS-AI",
        "tagline": "Systèmes complets d'automatisation d'entreprise par intelligence artificielle",
        "tone": "professionnel, factuel, français d'abord",
        "colors": ["#000000", "#FFFFFF"],
        "langue": "fr",
    }


def test_unknown_fields_are_tolerated():
    data = {**MINIMAL_PROFILE, "extra": "surprise"}
    result = brand_schema.validate_profile(data)
    assert result["extra"] == "surprise"


@pytest.mark.parametrize("field", brand_schema.REQUIRED_FIELDS)
def test_missing_required_field_raises(field):
    data = {k: v for k, v in MINIMAL_PROFILE.items() if k != field}
    with pytest.raises(brand_schema.ProfileError) as exc_info:
        brand_schema.validate_profile(data)
    assert exc_info.value.field == field
    assert field in exc_info.value.message
    assert field in str(exc_info.value)


@pytest.mark.parametrize(
    "invalid_profile",
    [
        {**MINIMAL_PROFILE, "name": ""},
        {**MINIMAL_PROFILE, "colors": []},
        {**MINIMAL_PROFILE, "colors": ["#000000", 123]},
        {**MINIMAL_PROFILE, "colors": ["#000000", True]},
        {**MINIMAL_PROFILE, "tagline": datetime.date(2024, 1, 1)},
        {**MINIMAL_PROFILE, "tagline": True},
    ],
)
def test_invalid_types_raise_profile_error(invalid_profile):
    with pytest.raises(brand_schema.ProfileError):
        brand_schema.validate_profile(invalid_profile)


@pytest.mark.parametrize("obj", [[], None])
def test_non_dict_input_raises_racine_error(obj):
    with pytest.raises(brand_schema.ProfileError) as exc_info:
        brand_schema.validate_profile(obj)
    assert exc_info.value.field == "racine"
    assert "racine" in exc_info.value.message
