import json

from ai_garment.core.garment_spec import GarmentSpec
from ai_garment.core.validation import validate_spec


def codes(report):
    return [e.code for e in report.errors]


def test_valid_tshirt():
    r = validate_spec(GarmentSpec.from_dict({"type": "tshirt", "fabric": "cotton", "fit": "oversized"}))
    assert r.ok and r.errors == []
    json.dumps(r.to_dict())


def test_unknown_fabric():
    """Brief test 7."""
    r = validate_spec(GarmentSpec.from_dict({"type": "tshirt", "fabric": "unicorn_skin"}))
    assert not r.ok
    err = r.errors[0]
    assert err.code == "UNKNOWN_FABRIC"
    assert "unicorn_skin" in err.message
    assert err.path == "fabric"
    assert err.suggestions


def test_unknown_type():
    assert "UNKNOWN_GARMENT_TYPE" in codes(validate_spec(GarmentSpec.from_dict({"type": "spacesuit"})))


def test_unknown_fit():
    assert "UNKNOWN_FIT" in codes(validate_spec(GarmentSpec.from_dict({"type": "tshirt", "fit": "vacuum_sealed"})))


def test_bad_color():
    assert "INVALID_COLOR" in codes(validate_spec(GarmentSpec.from_dict({"type": "tshirt", "color": "#GGGGGG"})))


def test_component_not_allowed_for_category():
    spec = GarmentSpec.from_dict({"type": "pants", "components": [{"type": "hood", "name": "hood"}]})
    assert "INVALID_COMPONENT_FOR_TYPE" in codes(validate_spec(spec))


def test_unknown_component_type():
    spec = GarmentSpec.from_dict({"type": "tshirt", "components": [{"type": "jetpack", "name": "jp"}]})
    assert "UNKNOWN_COMPONENT" in codes(validate_spec(spec))


def test_invalid_length_for_category():
    assert "INVALID_LENGTH" in codes(validate_spec(GarmentSpec.from_dict({"type": "pants", "length": "hip"})))


def test_invalid_component_param():
    spec = GarmentSpec.from_dict({"type": "tshirt", "sleeves": {"length": "to_the_moon"}})
    assert "INVALID_PARAM" in codes(validate_spec(spec))


def test_elastic_tension_range():
    spec = GarmentSpec.from_dict({"type": "tshirt", "sleeves": {"cuff": {"type": "elastic", "tension": 0.8}}})
    assert "ELASTIC_TENSION_RANGE" in codes(validate_spec(spec))


def test_invalid_simulation_quality():
    spec = GarmentSpec.from_dict({"type": "tshirt", "simulation": {"quality": "ultra_mega"}})
    assert "INVALID_PARAM" in codes(validate_spec(spec))


def test_experimental_type_warns():
    r = validate_spec(GarmentSpec.from_dict({"type": "skirt"}))
    assert r.ok
    assert any("experimental" in w.lower() for w in r.warnings)


def test_all_errors_reported_together():
    r = validate_spec(GarmentSpec.from_dict({"type": "tshirt", "fabric": "unicorn_skin", "fit": "nope",
                                             "color": "not-a-colour"}))
    assert {"UNKNOWN_FABRIC", "UNKNOWN_FIT", "INVALID_COLOR"} <= set(codes(r))
