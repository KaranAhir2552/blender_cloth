import json

import pytest

from ai_garment.core.errors import GarmentError
from ai_garment.core.garment_operations import (
    apply_operation,
    get_operation_def,
    list_operations,
    modify_kwargs_to_operations,
    normalize_operation,
    validate_operation,
)
from ai_garment.core.garment_spec import GarmentSpec

BRIEF_OPS = ["create", "fit", "resize", "move", "sew", "unsew", "simulate", "set_fabric", "set_fit",
             "add_component", "remove_component", "modify_component", "roll", "fold", "tuck", "untuck",
             "lengthen", "shorten", "tighten", "loosen", "set_elastic", "bake", "reset", "inspect"]


def tshirt():
    return GarmentSpec.from_dict({"type": "tshirt", "fit": "regular", "fabric": "cotton"})


def codes(issues):
    return [i.code for i in issues]


@pytest.mark.parametrize("name", BRIEF_OPS + [n.upper() for n in BRIEF_OPS])
def test_every_brief_operation_is_registered(name):
    assert get_operation_def(name) is not None


def test_every_operation_documented():
    for name in list_operations():
        d = get_operation_def(name)
        assert d.description
        assert isinstance(d.effects, frozenset)


def test_alias_normalisation():
    op = normalize_operation({"operation": "TIGHTEN", "region": "chest"})
    assert op.name == "modify_fit"
    assert op.params["direction"] == "tighter"
    op = normalize_operation({"op": "LENGTHEN", "target": "sleeves", "amount": "+5%"})
    assert op.name == "modify_length"
    assert op.params["amount"] == "+5%"
    op = normalize_operation({"operation": "shorten", "target": "sleeves"})
    assert op.name == "modify_length" and op.params["direction"] == "shorter"


def test_unknown_operation():
    with pytest.raises(GarmentError) as exc:
        normalize_operation({"operation": "frobnicate"})
    assert exc.value.code == "UNKNOWN_OPERATION"


def test_missing_and_invalid_params():
    assert "MISSING_PARAM" in codes(validate_operation(normalize_operation({"operation": "set_fabric"}), tshirt()))
    assert "INVALID_PARAM" in codes(validate_operation(
        normalize_operation({"operation": "modify_fit", "direction": "sideways"}), tshirt()))
    assert "UNKNOWN_FABRIC" in codes(validate_operation(
        normalize_operation({"operation": "set_fabric", "fabric": "unicorn_skin"}), tshirt()))
    assert "INVALID_COLOR" in codes(validate_operation(
        normalize_operation({"operation": "set_color", "color": "ultraviolet-ish"}), tshirt()))


def test_add_elastic_cuff_to_sleeves():
    """Brief test 3."""
    spec = tshirt()
    op = normalize_operation({"operation": "add_component", "type": "elastic_cuff", "target": "sleeves",
                              "strength": "medium"})
    assert validate_operation(op, spec) == []
    res = apply_operation(spec, op)
    cuffs = [c for c in res.spec.components if c.type == "elastic_cuff"]
    assert sorted(c.target for c in cuffs) == ["left_sleeve", "right_sleeve"]
    for c in cuffs:
        assert c.params["strength"] == "medium"
        assert 0 < c.params["tension"] <= 0.5
        assert 0 < c.params["width"] <= 0.2
    assert not [c for c in spec.components if c.type == "elastic_cuff"], "apply_operation must be pure"
    assert "geometry" in res.effects and "physics" in res.effects


def test_elastic_out_of_range_rejected():
    op = normalize_operation({"operation": "add_component", "type": "elastic_cuff", "target": "sleeves",
                              "strength": "medium", "tension": 0.95})
    assert "ELASTIC_TENSION_RANGE" in codes(validate_operation(op, tshirt()))


def test_set_elastic_on_existing_band():
    spec = GarmentSpec.from_dict({"type": "hoodie"})
    op = normalize_operation({"operation": "set_elastic", "target": "waistband", "strength": "strong"})
    assert validate_operation(op, spec) == []
    res = apply_operation(spec, op)
    band = res.spec.get_component("waistband")
    assert band.params["elastic"]["strength"] == "strong"


def test_roll_sleeves():
    res = apply_operation(tshirt(), normalize_operation({"operation": "roll", "target": "sleeves"}))
    for side in ("left", "right"):
        assert res.spec.get_component(f"{side}_sleeve").state["rolled"] >= 1
    assert "geometry" in res.effects


def test_roll_missing_target():
    pants = GarmentSpec.from_dict({"type": "pants"})
    assert "TARGET_NOT_FOUND" in codes(validate_operation(
        normalize_operation({"operation": "roll", "target": "sleeves"}), pants))
    assert validate_operation(normalize_operation({"operation": "roll", "target": "legs"}), pants) == []


def test_tuck_only_for_tops():
    shirt = GarmentSpec.from_dict({"type": "shirt"})
    res = apply_operation(shirt, normalize_operation({"operation": "tuck"}))
    assert res.spec.tucked is True
    res2 = apply_operation(res.spec, normalize_operation({"operation": "untuck"}))
    assert res2.spec.tucked is False
    pants = GarmentSpec.from_dict({"type": "pants"})
    assert "INVALID_FOR_TYPE" in codes(validate_operation(normalize_operation({"operation": "tuck"}), pants))


def test_set_fabric_effects():
    res = apply_operation(tshirt(), normalize_operation({"operation": "set_fabric", "fabric": "heavy denim"}))
    assert res.spec.fabric.name == "denim"
    assert "heavy" in res.spec.fabric.qualifiers
    assert "physics" in res.effects and "material" in res.effects
    assert "geometry" not in res.effects


def test_modify_length_garment_and_sleeves():
    res = apply_operation(tshirt(), normalize_operation({"operation": "modify_length", "amount": "+10%"}))
    assert res.spec.length_adjust["percent"] == pytest.approx(10.0)
    res = apply_operation(tshirt(), normalize_operation({"operation": "modify_length", "target": "sleeves",
                                                          "amount": "-5%"}))
    assert res.spec.get_component("left_sleeve").params["length_adjust"]["percent"] == pytest.approx(-5.0)
    res = apply_operation(tshirt(), normalize_operation({"operation": "shorten", "target": "sleeves",
                                                          "intensity": 0.5}))
    assert res.spec.get_component("right_sleeve").params["length_adjust"]["percent"] == pytest.approx(-5.0)


def test_modify_fit_region_and_component():
    res = apply_operation(tshirt(), normalize_operation({"operation": "modify_fit", "region": "chest",
                                                          "direction": "tighter"}))
    assert res.spec.fit.overrides["chest_ease"] == pytest.approx(-4.0)
    jeans = GarmentSpec.from_dict({"type": "jeans"})
    res = apply_operation(jeans, normalize_operation({"operation": "set_fit", "target": "legs", "level": "loose"}))
    assert res.spec.fit.component_levels["left_leg"] == "loose"
    assert res.spec.fit.component_levels["right_leg"] == "loose"


def test_remove_component():
    hoodie = GarmentSpec.from_dict({"type": "hoodie"})
    res = apply_operation(hoodie, normalize_operation({"operation": "remove_component", "target": "hood"}))
    assert res.spec.get_component("hood") is None
    assert "TARGET_NOT_FOUND" in codes(validate_operation(
        normalize_operation({"operation": "remove_component", "target": "hood"}), tshirt()))


def test_removing_body_is_refused():
    assert "REQUIRED_COMPONENT" in codes(validate_operation(
        normalize_operation({"operation": "remove_component", "target": "body"}), tshirt()))


def test_sew_unsew():
    res = apply_operation(tshirt(), normalize_operation({"operation": "unsew", "seam": "left_sleeve:body"}))
    assert "left_sleeve:body" in res.spec.disabled_seams
    res2 = apply_operation(res.spec, normalize_operation({"operation": "sew", "seam": "left_sleeve:body"}))
    assert "left_sleeve:body" not in res2.spec.disabled_seams


def test_resize_and_move():
    res = apply_operation(tshirt(), normalize_operation({"operation": "resize", "amount": "+5%"}))
    assert res.spec.fit.scale == pytest.approx(1.05)
    res = apply_operation(tshirt(), normalize_operation({"operation": "move", "offset": [0, 0, 0.02]}))
    assert res.spec.placement["offset"] == [0, 0, 0.02]


def test_scene_ops_do_not_change_spec():
    for name in ("simulate", "bake", "inspect", "fit"):
        res = apply_operation(tshirt(), normalize_operation({"operation": name}))
        assert res.spec.to_dict() == tshirt().to_dict()


@pytest.mark.parametrize("kwargs,expected", [
    ({"length": "+10%"}, {"operation": "modify_length", "target": "garment", "amount": "+10%"}),
    ({"region": "chest", "fit": "tighter"}, {"operation": "modify_fit", "region": "chest", "direction": "tighter"}),
    ({"component": "sleeves", "length": "-5%"}, {"operation": "modify_length", "target": "sleeves", "amount": "-5%"}),
    ({"component": "sleeves", "position": "rolled_up"}, {"operation": "roll", "target": "sleeves"}),
    ({"component": "legs", "fit": "baggy"}, {"operation": "set_fit", "target": "legs", "level": "loose"}),
    ({"fabric": "silk"}, {"operation": "set_fabric", "fabric": "silk"}),
    ({"color": "navy"}, {"operation": "set_color", "color": "navy"}),
])
def test_modify_kwargs_mapping(kwargs, expected):
    ops = modify_kwargs_to_operations(**kwargs)
    assert len(ops) == 1
    for k, v in expected.items():
        assert ops[0][k] == v
    json.dumps(ops)


def test_modify_kwargs_unknown_key():
    with pytest.raises(GarmentError) as exc:
        modify_kwargs_to_operations(sparkle=True)
    assert exc.value.code == "INVALID_PARAM"
