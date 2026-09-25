import pytest

from ai_garment.core.avatar_model import AvatarModel
from ai_garment.core.errors import GarmentError
from ai_garment.core.fit_system import (
    FIT_LEVELS,
    SLEEVE_LENGTH_FRACTIONS,
    adjust_fit,
    derive_garment_measurements,
    ease_for,
    resolve_ease,
    shift_fit_level,
)
from ai_garment.core.garment_spec import FitSpec, GarmentSpec
from ai_garment.core.validation import validate_spec


def test_fit_levels_and_monotonic_ease():
    assert FIT_LEVELS == ["tight", "slim", "regular", "relaxed", "loose", "oversized"]
    for key in ("chest_ease", "waist_ease", "hip_ease", "shoulder_drop", "sleeve_width_ease", "leg_width_ease",
                "cuff_width_ease"):
        values = [ease_for(level)[key] for level in FIT_LEVELS]
        assert values == sorted(values), key


def test_shift_fit_level():
    assert shift_fit_level("regular", 1) == "relaxed"
    assert shift_fit_level("regular", -2) == "tight"
    assert shift_fit_level("oversized", 3) == "oversized"
    assert shift_fit_level("tight", -1) == "tight"


def test_tighter_around_chest():
    fit = FitSpec(level="regular")
    new, notes = adjust_fit(fit, region="chest", direction="tighter")
    assert resolve_ease(new)["chest_ease"] == pytest.approx(ease_for("regular")["chest_ease"] - 4.0)
    assert resolve_ease(new)["waist_ease"] == pytest.approx(ease_for("regular")["waist_ease"])
    assert fit.overrides == {}, "adjust_fit must not mutate its input"
    assert notes


def test_slightly_is_half_step_and_region_alias():
    new, _ = adjust_fit(FitSpec(level="regular"), region="bust", direction="looser", intensity=0.5)
    assert resolve_ease(new)["chest_ease"] == pytest.approx(ease_for("regular")["chest_ease"] + 2.0)


def test_overall_adjustment_touches_all_circumferences():
    new, _ = adjust_fit(FitSpec(level="regular"), region=None, direction="looser")
    base = ease_for("regular")
    e = resolve_ease(new)
    for k in ("chest_ease", "waist_ease", "hip_ease"):
        assert e[k] > base[k]


def test_unknown_region():
    with pytest.raises(GarmentError) as exc:
        adjust_fit(FitSpec(), region="elbow_pit_of_doom", direction="tighter")
    assert exc.value.code == "UNKNOWN_REGION"


def test_ease_clamped():
    fit = FitSpec(level="tight")
    for _ in range(10):
        fit, _ = adjust_fit(fit, region="chest", direction="tighter")
    assert resolve_ease(fit)["chest_ease"] >= -8.0


def test_component_level_override():
    fit = FitSpec(level="regular", component_levels={"left_sleeve": "loose"})
    assert resolve_ease(fit, "left_sleeve")["sleeve_width_ease"] == ease_for("loose")["sleeve_width_ease"]
    assert resolve_ease(fit, "right_sleeve")["sleeve_width_ease"] == ease_for("regular")["sleeve_width_ease"]


MOCK_AVATAR = {"height": 1.75, "shoulder_width": 0.44, "chest": 0.96, "waist": 0.82, "hip": 0.98,
               "arm_length": 0.58}


def test_measurements_derived_from_avatar():
    """Brief test 4."""
    avatar = AvatarModel.from_metadata(MOCK_AVATAR)
    spec = GarmentSpec.from_dict({"type": "tshirt", "fit": "oversized"})
    m = derive_garment_measurements(avatar.get_measurements(), spec)
    e = ease_for("oversized")
    assert m["chest_circumference"] == pytest.approx(0.96 + e["chest_ease"] / 100)
    assert m["waist_circumference"] == pytest.approx(0.82 + e["waist_ease"] / 100)
    assert m["hip_circumference"] == pytest.approx(0.98 + e["hip_ease"] / 100)
    assert m["shoulder_width"] == pytest.approx(0.44 + 2 * e["shoulder_drop"] / 100)
    assert m["components"]["left_sleeve"]["length"] == pytest.approx(0.58 * SLEEVE_LENGTH_FRACTIONS["short"])
    assert m["garment_length"] > 0


def test_sleeve_length_adjustment_and_resize():
    avatar = AvatarModel.from_metadata(MOCK_AVATAR)
    spec = GarmentSpec.from_dict({"type": "shirt"})
    spec.get_component("left_sleeve").params["length_adjust"] = {"percent": -10.0, "meters": 0.0}
    m = derive_garment_measurements(avatar.get_measurements(), spec)
    assert m["components"]["left_sleeve"]["length"] == pytest.approx(0.58 * 1.0 * 0.9)
    assert m["components"]["right_sleeve"]["length"] == pytest.approx(0.58 * 1.0)
    spec.fit.scale = 1.05
    m2 = derive_garment_measurements(avatar.get_measurements(), spec)
    assert m2["chest_circumference"] == pytest.approx(m["chest_circumference"] * 1.05)


def test_pants_measurements():
    avatar = AvatarModel.from_metadata(dict(MOCK_AVATAR, thigh=0.56, inseam=0.80))
    spec = GarmentSpec.from_dict({"type": "pants", "fit": "loose"})
    m = derive_garment_measurements(avatar.get_measurements(), spec)
    assert m["thigh_circumference"] == pytest.approx(0.56 + ease_for("loose")["leg_width_ease"] / 100)
    assert 0.6 < m["garment_length"] < 1.2


def test_negative_ease_with_rigid_fabric_warns():
    spec = GarmentSpec.from_dict({"type": "jeans", "fit": "tight"})
    report = validate_spec(spec)
    assert report.ok
    assert any("negative ease" in w.lower() for w in report.warnings)
