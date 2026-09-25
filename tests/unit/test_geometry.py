import math

import pytest

from ai_garment.core.avatar_model import build_avatar_model
from ai_garment.core.garment_spec import GarmentSpec
from ai_garment.core.geometry.builder import build_garment_mesh
from ai_garment.core.garment_operations import apply_operation, normalize_operation
from fixtures.humanoid import make_humanoid
from mocks.mock_bpy import BVHTree  # pure-python nearest-vertex helper, no bpy install needed

ALL_TYPES = ["tshirt", "shirt", "hoodie", "sweatshirt", "jacket", "pants", "jeans", "shorts", "skirt", "dress"]


@pytest.fixture(scope="module")
def human():
    return make_humanoid()


@pytest.fixture(scope="module")
def avatar(human):
    return build_avatar_model("Human", human["vertices"], bones=human["bones"])


@pytest.mark.parametrize("gtype", ALL_TYPES)
def test_every_type_builds_valid_mesh(gtype, avatar):
    spec = GarmentSpec.from_dict({"type": gtype})
    data = build_garment_mesh(spec, avatar, quality="draft")
    assert data.validate() == []
    assert len(data.vertices) > 50
    assert len(data.faces) > 20
    for comp in spec.components:
        group = data.components.get(comp.name)
        assert group is not None, f"{gtype}: component {comp.name} has no vertex group"
        assert data.vertex_groups[group], f"{gtype}: group {group} empty"


def test_sleeves_are_sewn_to_body(avatar):
    data = build_garment_mesh(GarmentSpec.from_dict({"type": "tshirt"}), avatar, quality="draft")
    seams = {s["name"]: s for s in data.seams}
    assert seams["left_sleeve:body"]["edges"] > 0
    assert seams["right_sleeve:body"]["edges"] > 0
    n = len(data.vertices)
    assert data.edges and all(0 <= a < n and 0 <= b < n and a != b for a, b in data.edges)


def test_disabled_seam_removes_sewing(avatar):
    spec = GarmentSpec.from_dict({"type": "tshirt"})
    spec.disabled_seams.append("left_sleeve:body")
    data = build_garment_mesh(spec, avatar, quality="draft")
    assert "left_sleeve:body" not in {s["name"] for s in data.seams}


def _max_radius_near(data, group, z, tol=0.03):
    idx = data.vertex_groups[group]
    r = [math.hypot(data.vertices[i][0], data.vertices[i][1]) for i in idx if abs(data.vertices[i][2] - z) < tol]
    return max(r)


def test_ease_increases_size(avatar):
    chest_z = avatar.landmarks["chest"][2]
    reg = build_garment_mesh(GarmentSpec.from_dict({"type": "tshirt", "fit": "regular"}), avatar, quality="draft")
    big = build_garment_mesh(GarmentSpec.from_dict({"type": "tshirt", "fit": "oversized"}), avatar, quality="draft")
    assert _max_radius_near(big, "AIG_body", chest_z) > _max_radius_near(reg, "AIG_body", chest_z) + 0.02


def _extent_along_arm(data, avatar):
    sh = avatar.landmarks["shoulder_l"]
    wr = avatar.landmarks["wrist_l"]
    axis = [w - s for w, s in zip(wr, sh)]
    length = math.sqrt(sum(a * a for a in axis))
    axis = [a / length for a in axis]
    idx = data.vertex_groups["AIG_left_sleeve"]
    return max(sum((data.vertices[i][k] - sh[k]) * axis[k] for k in range(3)) for i in idx)


def test_rolled_sleeve_is_shorter(avatar):
    spec = GarmentSpec.from_dict({"type": "shirt"})
    rolled = apply_operation(spec, normalize_operation({"operation": "roll", "target": "sleeves"})).spec
    a = build_garment_mesh(spec, avatar, quality="draft")
    b = build_garment_mesh(rolled, avatar, quality="draft")
    assert _extent_along_arm(b, avatar) < _extent_along_arm(a, avatar) - 0.03
    assert b.vertex_groups.get("AIG_left_sleeve_roll")


def test_sleeve_length_adjustment_changes_geometry(avatar):
    spec = GarmentSpec.from_dict({"type": "shirt"})
    shorter = apply_operation(spec, normalize_operation({"operation": "modify_length", "target": "sleeves",
                                                          "amount": "-20%"})).spec
    assert _extent_along_arm(build_garment_mesh(shorter, avatar, quality="draft"), avatar) < \
        _extent_along_arm(build_garment_mesh(spec, avatar, quality="draft"), avatar) - 0.05


def test_initial_garment_clears_body(human, avatar):
    bvh = BVHTree(human["vertices"], human["faces"])
    for gtype in ("tshirt", "pants"):
        data = build_garment_mesh(GarmentSpec.from_dict({"type": gtype}), avatar, quality="draft")
        inside = 0
        for v in data.vertices:
            loc, normal, _, _ = bvh.find_nearest(v)
            if sum((v[k] - loc[k]) * normal[k] for k in range(3)) < -0.005:
                inside += 1
        assert inside / len(data.vertices) < 0.05, f"{gtype}: {inside} of {len(data.vertices)} vertices inside body"


def test_elastic_and_physics_groups(avatar):
    spec = GarmentSpec.from_dict({"type": "tshirt", "sleeves": {"cuff": {"type": "elastic", "strength": "strong"}}})
    data = build_garment_mesh(spec, avatar, quality="draft")
    phys = data.physics
    assert phys["shrink_group"] == "AIG_shrink"
    assert phys["shrink_max"] > 0
    weights = data.vertex_groups["AIG_shrink"]
    assert max(weights.values()) == pytest.approx(1.0)
    assert phys["stiff_group"] == "AIG_stiff"


def test_hood_and_pockets(avatar):
    data = build_garment_mesh(GarmentSpec.from_dict({"type": "hoodie"}), avatar, quality="draft")
    assert data.vertex_groups["AIG_hood"]
    assert "hood:body" in {s["name"] for s in data.seams}
    assert data.vertex_groups["AIG_kangaroo_pocket"]


def test_deterministic_and_quality_scaling(avatar):
    spec = GarmentSpec.from_dict({"type": "tshirt"})
    a = build_garment_mesh(spec, avatar, quality="draft")
    b = build_garment_mesh(spec, avatar, quality="draft")
    assert a.vertices == b.vertices and a.faces == b.faces
    prod = build_garment_mesh(spec, avatar, quality="production")
    assert len(prod.vertices) > len(a.vertices)


def test_offset_moves_garment(avatar):
    spec = GarmentSpec.from_dict({"type": "tshirt", "placement": {"offset": [0.0, 0.0, 0.05]}})
    base = build_garment_mesh(GarmentSpec.from_dict({"type": "tshirt"}), avatar, quality="draft")
    moved = build_garment_mesh(spec, avatar, quality="draft")
    assert moved.vertices[0][2] == pytest.approx(base.vertices[0][2] + 0.05)
