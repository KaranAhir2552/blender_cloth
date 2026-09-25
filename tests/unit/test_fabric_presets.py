import pytest

from ai_garment.core.errors import GarmentError
from ai_garment.core.fabric_presets import get_fabric_preset, list_fabrics, resolve_fabric
from ai_garment.core.garment_spec import FabricSpec
from ai_garment.core.physics_mapping import map_fabric_to_native
from ai_garment.core.quality import QUALITY_LEVELS, get_quality
from ai_garment.blender.api_contract import CLOTH_SETTINGS_ATTRS, CLOTH_COLLISION_ATTRS, COLLISION_SETTINGS_ATTRS

REQUIRED = ["cotton", "heavy_cotton", "jersey", "denim", "silk", "wool", "linen", "polyester", "nylon",
            "leather", "rubber", "elastic"]


def test_required_presets_present_and_artistic():
    names = list_fabrics()
    for n in REQUIRED:
        assert n in names
        p = get_fabric_preset(n)
        assert p.artistic is True, "presets must be labelled artistic unless validated"
        for attr in ("weight_class", "stretch", "bend", "drape", "damping"):
            assert getattr(p, attr)


@pytest.mark.parametrize("name,expected", [("cotton", "cotton"), ("denim", "denim"), ("silk", "silk"),
                                           ("Denim", "denim"), ("heavy cotton", "heavy_cotton"),
                                           ("spandex", "elastic"), ("t-shirt jersey", "jersey")])
def test_fabric_name_mapping(name, expected):
    assert resolve_fabric(name).base == expected


def test_heavy_denim_qualifier():
    plain = resolve_fabric("denim")
    heavy = resolve_fabric("heavy denim")
    assert heavy.base == "denim"
    assert "heavy" in heavy.qualifiers
    order = ["ultralight", "light", "medium", "heavy", "very_heavy"]
    assert order.index(heavy.weight_class) > order.index(plain.weight_class) or plain.weight_class == "very_heavy"


def test_stretchy_qualifier():
    assert resolve_fabric("stretchy denim").stretch != resolve_fabric("denim").stretch


def test_unknown_fabric():
    with pytest.raises(GarmentError) as exc:
        resolve_fabric("unicorn_skin")
    assert exc.value.code == "UNKNOWN_FABRIC"
    assert exc.value.suggestions  # lists known fabrics or close matches


def test_overrides():
    r = resolve_fabric(FabricSpec(name="cotton", overrides={"stretch": "high"}))
    assert r.stretch == "high"
    with pytest.raises(GarmentError):
        resolve_fabric(FabricSpec(name="cotton", overrides={"stretch": "infinite"}))


def _mass(name, quality="preview"):
    return map_fabric_to_native(resolve_fabric(name), quality)["cloth"]["mass"]


def _bend(name):
    return map_fabric_to_native(resolve_fabric(name), "preview")["cloth"]["bending_stiffness"]


def test_mapping_monotonic():
    assert _mass("silk") < _mass("cotton") < _mass("denim")
    assert _bend("silk") < _bend("cotton") < _bend("denim") <= _bend("leather")
    stretchy = map_fabric_to_native(resolve_fabric("elastic"), "preview")["cloth"]["tension_stiffness"]
    rigid = map_fabric_to_native(resolve_fabric("leather"), "preview")["cloth"]["tension_stiffness"]
    assert stretchy < rigid


def test_mapping_keys_are_real_blender_attributes():
    m = map_fabric_to_native(resolve_fabric("cotton"), "production")
    assert set(m["cloth"]) <= set(CLOTH_SETTINGS_ATTRS)
    assert set(m["cloth_collision"]) <= set(CLOTH_COLLISION_ATTRS)
    assert set(m["collider"]) <= set(COLLISION_SETTINGS_ATTRS)
    assert m["artistic"] is True


def test_physics_overrides_applied_and_validated():
    r = resolve_fabric(FabricSpec(name="cotton", physics_overrides={"tension_stiffness": 55.0}))
    assert map_fabric_to_native(r, "preview")["cloth"]["tension_stiffness"] == 55.0
    with pytest.raises(GarmentError):
        resolve_fabric(FabricSpec(name="cotton", physics_overrides={"warp_drive": 1.0}))


def test_quality_levels_ordered():
    assert QUALITY_LEVELS == ["draft", "preview", "medium", "production"]
    steps = [get_quality(q).cloth_steps for q in QUALITY_LEVELS]
    assert steps == sorted(steps)
    assert get_quality("production").self_collision is True
    assert get_quality("draft").self_collision is False
    q_prod = map_fabric_to_native(resolve_fabric("cotton"), "production")["cloth"]["quality"]
    q_prev = map_fabric_to_native(resolve_fabric("cotton"), "preview")["cloth"]["quality"]
    assert q_prod > q_prev


def test_unit_scale_scales_distances():
    m1 = map_fabric_to_native(resolve_fabric("cotton"), "preview", unit_scale=1.0)
    m10 = map_fabric_to_native(resolve_fabric("cotton"), "preview", unit_scale=0.1)  # decimetre scene
    assert m10["cloth_collision"]["distance_min"] == pytest.approx(m1["cloth_collision"]["distance_min"] * 10)
