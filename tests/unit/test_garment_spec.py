import json

import pytest

from ai_garment.core.garment_spec import GarmentSpec
from ai_garment.core.garment_types import (
    GarmentTypeDef,
    get_garment_type,
    list_garment_types,
    register_garment_type,
    unregister_garment_type,
)
from ai_garment.core.errors import GarmentError
from ai_garment.core.validation import validate_spec

REQUIRED_TYPES = ["tshirt", "shirt", "hoodie", "jacket", "pants", "jeans", "shorts", "skirt", "dress", "sweatshirt"]


def test_all_required_types_registered():
    names = list_garment_types()
    for t in REQUIRED_TYPES:
        assert t in names


@pytest.mark.parametrize("alias,expected", [
    ("T-Shirt", "tshirt"), ("tee", "tshirt"), ("t shirt", "tshirt"), ("trousers", "pants"),
    ("Jeans", "jeans"), ("hooded sweatshirt", "hoodie"), ("button-up", "shirt"),
])
def test_type_aliases(alias, expected):
    assert GarmentSpec.from_dict({"type": alias}).type == expected


def test_unknown_type_lookup_raises_structured_error():
    with pytest.raises(GarmentError) as exc:
        get_garment_type("spacesuit")
    assert exc.value.code == "UNKNOWN_GARMENT_TYPE"


def test_tshirt_default_components():
    spec = GarmentSpec.from_dict({"type": "tshirt"})
    names = [c.name for c in spec.components]
    for n in ["body", "collar", "left_sleeve", "right_sleeve", "hem"]:
        assert n in names
    assert spec.fabric.name == "cotton"
    assert spec.fit.level == "regular"
    sleeve = spec.get_component("left_sleeve")
    assert sleeve.type == "sleeve"
    assert sleeve.params["side"] == "left"
    assert sleeve.params["length"] == "short"


def test_brief_example_shorthand_is_normalised():
    spec = GarmentSpec.from_dict({
        "type": "tshirt", "fit": "oversized", "fabric": "cotton", "color": "black",
        "sleeves": {"length": "short", "fit": "loose", "cuff": {"type": "elastic", "strength": "medium"}},
        "length": "hip",
        "simulation": {"gravity": True, "collision": True, "self_collision": True},
    })
    assert spec.fit.level == "oversized"
    assert spec.color == "black"
    assert spec.length == "hip"
    assert spec.simulation.self_collision is True
    for side in ("left", "right"):
        sleeve = spec.get_component(f"{side}_sleeve")
        assert sleeve.params["length"] == "short"
        assert spec.fit.component_levels[f"{side}_sleeve"] == "loose"
        cuff = spec.get_component(f"{side}_sleeve_cuff")
        assert cuff is not None
        assert cuff.type == "elastic_cuff"
        assert cuff.target == f"{side}_sleeve"
        assert cuff.params["strength"] == "medium"
    assert validate_spec(spec).ok


def test_jeans_defaults():
    spec = GarmentSpec.from_dict({"type": "jeans"})
    assert spec.type == "jeans"
    assert spec.fabric.name == "denim"
    names = [c.name for c in spec.components]
    for n in ["waistband", "left_leg", "right_leg"]:
        assert n in names
    slim = GarmentSpec.from_dict({"type": "jeans", "fit": "slim"})
    assert slim.fit.level == "slim"
    assert validate_spec(slim).ok


def test_cargo_pants_shorthand():
    spec = GarmentSpec.from_dict({"type": "pants", "fit": "loose", "pockets": {"type": "cargo"},
                                  "cuffs": {"type": "elastic", "strength": "medium"}})
    types_ = [c.type for c in spec.components]
    assert types_.count("cargo_pocket") == 2
    assert types_.count("elastic_cuff") == 2
    cuff_targets = sorted(c.target for c in spec.components if c.type == "elastic_cuff")
    assert cuff_targets == ["left_leg", "right_leg"]
    assert validate_spec(spec).ok


def test_explicit_components_merge_with_defaults():
    spec = GarmentSpec.from_dict({"type": "tshirt", "components": [
        {"type": "pocket", "name": "chest_pocket", "params": {"placement": "chest_left"}},
        {"name": "left_sleeve", "type": "sleeve", "params": {"side": "left", "length": "long"}},
    ]})
    assert spec.get_component("chest_pocket") is not None
    assert spec.get_component("left_sleeve").params["length"] == "long"
    assert spec.get_component("right_sleeve").params["length"] == "short"


def test_default_components_can_be_disabled():
    spec = GarmentSpec.from_dict({"type": "tshirt", "default_components": False,
                                  "components": [{"type": "body", "name": "body"}]})
    assert [c.name for c in spec.components] == ["body"]


def test_round_trip_is_stable_and_json_serialisable():
    spec = GarmentSpec.from_dict({"type": "hoodie", "fit": "relaxed", "fabric": "heavy cotton", "color": "#112233"})
    d = spec.to_dict()
    json.dumps(d)
    again = GarmentSpec.from_dict(d)
    assert again.to_dict() == d


def test_copy_is_deep():
    spec = GarmentSpec.from_dict({"type": "tshirt"})
    other = spec.copy()
    other.get_component("left_sleeve").params["length"] = "long"
    assert spec.get_component("left_sleeve").params["length"] == "short"


def test_new_garment_type_can_be_registered_without_architecture_changes():
    defn = GarmentTypeDef(
        name="tank_top", display_name="Tank Top", category="top", builder="top",
        default_fabric="jersey", default_fit="slim", default_length="hip", aliases=("tank",),
        default_components=({"type": "body", "name": "body"}, {"type": "collar", "name": "collar"},
                            {"type": "hem", "name": "hem"}),
    )
    register_garment_type(defn)
    try:
        spec = GarmentSpec.from_dict({"type": "tank"})
        assert spec.type == "tank_top"
        assert validate_spec(spec).ok
        assert "tank_top" in list_garment_types()
    finally:
        unregister_garment_type("tank_top")
    assert "tank_top" not in list_garment_types()


def test_register_duplicate_type_rejected():
    with pytest.raises(GarmentError):
        register_garment_type(get_garment_type("tshirt"))
