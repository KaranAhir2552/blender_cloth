"""End-to-end orchestration against the strict mock bpy.

Proves: call shapes, ordering, tagging, and structured results against our
model of the Blender API. Does NOT prove real cloth behaviour.
"""
import json

import pytest

from ai_garment.api.garment import GarmentSystem
from ai_garment.core.errors import MSG_AVATAR_NOT_FOUND, MSG_COLLISION_ISSUE, MSG_WRINKLES_UNAVAILABLE
from mocks.mock_bpy import Vector, build_humanoid_scene


@pytest.fixture
def scene(mock_bpy, humanoid):
    body, arm = build_humanoid_scene(mock_bpy, humanoid)
    return mock_bpy, body, arm, GarmentSystem()


def cloth_of(bpy, garment):
    obj = bpy.data.objects.get(garment.object_name)
    return obj, next(m for m in obj.modifiers if m.type == "CLOTH")


def test_detect_avatar_and_provider(scene):
    bpy, body, arm, system = scene
    av = system.detect_avatar()
    assert av.ok, av.result.to_dict()
    assert av.name == "Human"
    assert av.model.source == "makehuman"
    assert av.get_measurements()["chest_circumference"] == pytest.approx(0.90, rel=0.1)
    assert "left_arm" in av.get_body_regions()
    sel = system.detect_provider()
    assert sel.provider.name == "blender_native"
    assert sel.status.available


def test_full_tshirt_pipeline(scene):
    bpy, body, arm, system = scene
    body_mods_before = [(m.name, m.type) for m in body.modifiers]

    shirt = system.create(type="tshirt", fit="oversized", fabric="cotton", color="black")
    obj, cloth = cloth_of(bpy, shirt)
    assert obj["ai_garment_id"] == shirt.id
    assert obj["ai_garment_role"] == "garment"
    assert json.loads(obj["ai_garment_spec"])["type"] == "tshirt"
    groups = {g.name for g in obj.vertex_groups}
    assert {"AIG_body", "AIG_left_sleeve", "AIG_right_sleeve", "AIG_collar", "AIG_hem"} <= groups
    assert cloth.settings.use_sewing_springs is True
    assert cloth.settings.sewing_force_max > 0
    mod_types = [m.type for m in obj.modifiers]
    assert mod_types.index("CLOTH") < mod_types.index("SOLIDIFY") < mod_types.index("SUBSURF")
    assert obj.data.edges, "sewing springs must exist as loose edges"
    assert obj.data.materials and obj.data.materials[0].node_tree.nodes["Principled BSDF"].inputs[
        "Base Color"].default_value[:3] == pytest.approx([0.01, 0.01, 0.01], abs=0.02)

    r = shirt.fit_to_avatar()
    assert r.ok, r.to_dict()
    proxies = [o for o in bpy.data.objects if o.get("ai_garment_role") == "collision_proxy"]
    assert len(proxies) == 1
    proxy = proxies[0]
    assert proxy.hide_render is True
    assert [m.type for m in proxy.modifiers][-1] == "COLLISION"
    assert proxy.collision.thickness_outer > 0
    assert [(m.name, m.type) for m in body.modifiers] == body_mods_before, "avatar must not be modified"

    r = shirt.add_component(type="elastic_cuff", target="sleeves", strength="medium")
    assert r.ok, r.to_dict()
    obj, cloth = cloth_of(bpy, shirt)
    assert cloth.settings.vertex_group_shrink == "AIG_shrink"
    assert cloth.settings.shrink_max > 0
    assert cloth.settings.vertex_group_structural_stiffness == "AIG_stiff"
    assert cloth.settings.tension_stiffness_max > cloth.settings.tension_stiffness

    r = shirt.simulate(mode="natural", quality="draft")
    assert r.ok, r.to_dict()
    assert r.data["settle"]["settled"] is True
    assert r.data["baked"] is True
    assert cloth.point_cache.is_baked
    assert cloth.collision_settings.use_self_collision is True
    assert bpy.context.scene.use_gravity is True
    assert any(op == "ptcache.bake_from_cache" for op, _ in bpy.ops_log)

    info = shirt.inspect()
    json.dumps(info)
    assert info["garment"] == "T-Shirt"
    assert info["provider"] == "Blender Native Cloth"
    assert info["fabric"] == "cotton"
    assert info["fit"] == "oversized"
    assert info["simulation"] == {"cloth": True, "collision": True, "self_collision": True, "baked": True}
    assert {"body", "left_sleeve", "right_sleeve", "collar"} <= set(info["components"])
    assert isinstance(info["warnings"], list)

    mass_before = cloth.settings.mass
    r = shirt.set_fabric("heavy denim")
    assert r.ok
    assert cloth.settings.mass > mass_before
    assert not cloth.point_cache.is_baked
    assert any("cache" in w.lower() for w in r.warnings)


def test_modify_regenerates_in_place(scene):
    bpy, body, arm, system = scene
    shirt = system.create(type="shirt")
    obj, _ = cloth_of(bpy, shirt)
    name = obj.name
    r = shirt.modify(component="sleeves", length="-20%")
    assert r.ok, r.to_dict()
    assert bpy.data.objects.get(name) is obj, "garment object must be updated in place, not replaced"
    assert shirt.spec.get_component("left_sleeve").params["length_adjust"]["percent"] == pytest.approx(-20)
    r = shirt.modify(region="chest", fit="tighter")
    assert r.ok and shirt.spec.fit.overrides["chest_ease"] == pytest.approx(-4.0)
    r = shirt.modify(component="sleeves", position="rolled_up")
    assert r.ok and shirt.spec.get_component("left_sleeve").state["rolled"] >= 1
    assert "AIG_left_sleeve_roll" in {g.name for g in obj.vertex_groups}


def test_apply_instruction(scene):
    bpy, body, arm, system = scene
    shirt = system.create(type="tshirt")
    r = shirt.apply("Make the sleeves slightly shorter and make it tighter around the chest.")
    assert r.ok, r.to_dict()
    assert shirt.spec.get_component("left_sleeve").params["length_adjust"]["percent"] == pytest.approx(-5)
    assert shirt.spec.fit.overrides["chest_ease"] == pytest.approx(-4.0)


def test_flagship_instruction_end_to_end(scene):
    bpy, body, arm, system = scene
    text = ("Create an oversized black cotton T-shirt on my MakeHuman character. Make the sleeves slightly loose "
            "with medium elastic cuffs. Let gravity naturally settle the shirt and make the fabric look realistic.")
    preview = system.plan(text)
    assert preview.to_dict()["valid"] is True
    r = system.run(text, quality_cap="draft")  # cap quality so the mock run stays fast
    assert r.ok, r.to_dict()
    g = system.list_garments()[0]
    info = system.get(g["id"]).inspect()
    assert info["fit"] == "oversized" and info["fabric"] == "cotton" and info["color"] == "black"
    assert info["simulation"]["baked"] is True
    assert MSG_WRINKLES_UNAVAILABLE in r.warnings


def test_wrinkles_unavailable_is_reported(scene):
    bpy, body, arm, system = scene
    shirt = system.create(type="tshirt")
    r = shirt.generate_wrinkles()
    assert r.data["applied"] is False
    assert MSG_WRINKLES_UNAVAILABLE in r.warnings


def test_self_collision_presets(scene):
    bpy, body, arm, system = scene
    shirt = system.create(type="tshirt")
    _, cloth = cloth_of(bpy, shirt)
    assert shirt.enable_self_collision("production").ok
    prod = cloth.collision_settings.self_distance_min
    assert cloth.collision_settings.use_self_collision
    assert shirt.enable_self_collision("draft").ok
    assert cloth.collision_settings.self_distance_min >= prod
    assert shirt.enable_self_collision("off").ok
    assert cloth.collision_settings.use_self_collision is False
    assert shirt.enable_self_collision("ludicrous").ok is False


def test_pants_preview_pipeline(scene):
    bpy, body, arm, system = scene
    pants = system.create(type="pants", fit="loose", fabric="heavy cotton")
    pants.add_component(type="cargo_pocket", target="legs")
    assert pants.fit_to_avatar().ok
    r = pants.simulate(mode="preview")
    assert r.ok
    assert r.data["baked"] is False
    _, cloth = cloth_of(bpy, pants)
    assert cloth.collision_settings.use_self_collision is False


def test_penetration_is_diagnosed(scene):
    bpy, body, arm, system = scene
    shirt = system.create(type="tshirt")
    shirt.fit_to_avatar()

    def collapse(obj, frame, coords):  # garment collapses into the torso centre line
        return [Vector((0.0, 0.0, c[2])) for c in coords]

    bpy._physics_stub = collapse
    r = shirt.simulate(mode="preview")
    issues = r.data["diagnostics"]["penetration"]["issues"]
    assert issues and issues[0]["message"] == MSG_COLLISION_ISSUE
    assert "increase collision margin" in issues[0]["suggestions"]
    assert MSG_COLLISION_ISSUE in " ".join(r.warnings)


def test_settle_non_convergence_warns(scene):
    bpy, body, arm, system = scene
    shirt = system.create(type="tshirt")

    def jitter(obj, frame, coords):
        return [Vector((c[0], c[1], c[2] + (0.01 if frame % 2 else -0.01))) for c in coords]

    bpy._physics_stub = jitter
    r = shirt.settle(max_frames=12)
    assert r.data["settled"] is False
    assert any("settle" in w.lower() for w in r.warnings)


def test_settle_applies_shape_key(scene):
    bpy, body, arm, system = scene
    shirt = system.create(type="tshirt")

    def drop(obj, frame, coords):
        return [Vector((c[0], c[1], c[2] - 0.001 * min(frame, 5))) for c in coords]

    bpy._physics_stub = drop
    r = shirt.settle(max_frames=30, apply="shape_key")
    assert r.ok and r.data["settled"]
    obj, _ = cloth_of(bpy, shirt)
    key = obj.data.shape_keys.key_blocks.get("AIG_Settled")
    assert key is not None and key.value == 1.0


def test_no_avatar(mock_bpy):
    system = GarmentSystem()
    av = system.detect_avatar()
    assert not av.ok
    assert av.result.errors[0].message == MSG_AVATAR_NOT_FOUND
    shirt = system.create(type="tshirt")
    assert any("default proportions" in w for w in shirt.result.warnings)
    r = shirt.fit_to_avatar()
    assert not r.ok and r.errors[0].code == "AVATAR_NOT_FOUND"


def test_scene_persistence_and_duplicate(scene):
    bpy, body, arm, system = scene
    shirt = system.create(type="hoodie", color="red")
    fresh = GarmentSystem()
    loaded = fresh.load_from_scene()
    assert [g.id for g in loaded] == [shirt.id]
    assert loaded[0].spec.to_dict() == shirt.spec.to_dict()
    dup = shirt.duplicate(name="Hoodie Copy")
    assert dup.id != shirt.id
    assert bpy.data.objects.get(dup.object_name) is not None
    assert bpy.data.objects.get(dup.object_name)["ai_garment_id"] == dup.id


def test_reset_and_delete(scene):
    bpy, body, arm, system = scene
    shirt = system.create(type="tshirt")
    shirt.fit_to_avatar()
    shirt.simulate(mode="natural", quality="draft")
    r = shirt.reset()
    assert r.ok
    _, cloth = cloth_of(bpy, shirt)
    assert not cloth.point_cache.is_baked
    r = shirt.delete()
    assert r.ok
    assert all(o.get("ai_garment_id") != shirt.id for o in bpy.data.objects)
    assert bpy.data.objects.get("Human") is body and bpy.data.objects.get("Human_rig") is arm
