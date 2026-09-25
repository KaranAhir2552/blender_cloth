import math

import pytest

from ai_garment.core.avatar_model import (
    BODY_REGIONS,
    AvatarModel,
    build_avatar_model,
    estimate_landmarks_from_bounds,
    infer_unit_scale,
    measure_section,
    resolve_landmarks_from_bones,
)
from fixtures.humanoid import make_humanoid


@pytest.mark.parametrize("rig", ["makehuman", "game_engine", "rigify", "mixamo"])
def test_bone_resolution_across_rigs(rig):
    h = make_humanoid(rig=rig)
    lm, rig_type, evidence = resolve_landmarks_from_bones(h["bones"])
    assert rig_type == rig
    assert evidence
    assert lm["shoulder_l"][0] > 0 and lm["shoulder_r"][0] < 0  # character's left is +X (faces -Y)
    assert lm["wrist_l"][2] < lm["elbow_l"][2] < lm["shoulder_l"][2]
    assert lm["ankle_r"][2] < lm["knee_r"][2] < lm["hip_joint_r"][2]
    assert lm["neck_base"][2] < lm["head_top"][2]


def test_unit_scale_inference():
    assert infer_unit_scale(1.75) == 1.0
    assert infer_unit_scale(17.5) == pytest.approx(0.1)
    assert infer_unit_scale(175.0) == pytest.approx(0.01)


def test_measure_section_ignores_separate_clusters():
    circle = [(0.1 * math.cos(t), 0.1 * math.sin(t)) for t in [i * 2 * math.pi / 64 for i in range(64)]]
    arm = [(0.4 + 0.03 * math.cos(t), 0.03 * math.sin(t)) for t in [i * 2 * math.pi / 16 for i in range(16)]]
    s = measure_section(circle + arm, center_x=0.0)
    assert s.circumference == pytest.approx(2 * math.pi * 0.1, rel=0.01)
    assert s.width == pytest.approx(0.2, rel=0.01)


def test_build_from_humanoid_measurements():
    h = make_humanoid()
    model = build_avatar_model("Human", h["vertices"], bones=h["bones"], vertex_groups=h["vertex_groups"],
                               properties=h["properties"])
    assert model.source == "makehuman"
    assert model.unit_scale == 1.0
    m = model.get_measurements()
    exp = h["expected"]
    assert m["height"] == pytest.approx(exp["height"], rel=0.03)
    for key in ("chest_circumference", "waist_circumference", "hip_circumference"):
        assert m[key] == pytest.approx(exp[key], rel=0.10), key
    assert m["shoulder_width"] == pytest.approx(exp["shoulder_width"], rel=0.15)
    assert m["arm_length"] == pytest.approx(exp["arm_length"], rel=0.05)
    assert model.pose == "A"


def test_regions_and_collision_surfaces():
    h = make_humanoid()
    model = build_avatar_model("Human", h["vertices"], bones=h["bones"])
    regions = model.get_body_regions()
    for r in BODY_REGIONS:
        assert r in regions
    top = model.get_collision_surfaces("tshirt")
    assert "chest" in top["regions"] and "left_arm" in top["regions"]
    assert "left_leg" not in top["regions"]
    bottom = model.get_collision_surfaces("pants")
    assert "left_leg" in bottom["regions"] and "hips" in bottom["regions"]
    assert "left_arm" not in bottom["regions"]
    assert top["margin"] > 0


def test_fallback_without_bones_uses_anthropometrics():
    h = make_humanoid()
    model = build_avatar_model("Blob", h["vertices"])
    assert model.source == "generic"
    assert any("anthropometric" in w.lower() for w in model.warnings)
    assert model.get_measurements()["height"] == pytest.approx(1.75, rel=0.05)


def test_decimetre_import_is_normalised():
    h = make_humanoid(scale=10.0)
    model = build_avatar_model("Human", h["vertices"], bones=h["bones"])
    assert model.unit_scale == pytest.approx(0.1)
    assert model.get_measurements()["height"] == pytest.approx(1.75, rel=0.03)
    assert model.get_measurements()["chest_circumference"] == pytest.approx(0.90, rel=0.1)


def test_t_pose_detected():
    h = make_humanoid(pose="T")
    model = build_avatar_model("Human", h["vertices"], bones=h["bones"])
    assert model.pose == "T"


def test_from_metadata_units_and_aliases():
    model = AvatarModel.from_metadata({"units": "cm", "height": 175, "chest": 96, "waist": 82})
    m = model.get_measurements()
    assert m["chest_circumference"] == pytest.approx(0.96)
    assert m["waist_circumference"] == pytest.approx(0.82)
    assert m["hip_circumference"] > 0  # estimated
    assert model.source == "metadata"


def test_estimate_landmarks_from_bounds():
    lm = estimate_landmarks_from_bounds((-0.3, -0.15, 0.0), (0.3, 0.15, 1.8))
    assert lm["knee_l"][2] < lm["hip_joint_l"][2] < lm["waist"][2] < lm["chest"][2] < lm["shoulder_l"][2]


def test_to_dict_json():
    import json
    h = make_humanoid()
    json.dumps(build_avatar_model("Human", h["vertices"], bones=h["bones"]).to_dict())


def test_register_custom_rig_signature():
    from ai_garment.core.avatar_model import RIG_SIGNATURES, register_rig_signature
    h = make_humanoid(rig="game_engine")
    renamed = {"CUSTOM_" + k: v for k, v in h["bones"].items()}
    roles = {role: ["custom" + names[0]] for role, names in RIG_SIGNATURES["game_engine"].items()}
    register_rig_signature("studio_rig", roles)
    try:
        lm, rig, _ = resolve_landmarks_from_bones(renamed)
        assert rig == "studio_rig"
        assert lm["wrist_l"][2] < lm["shoulder_l"][2]
    finally:
        RIG_SIGNATURES.pop("studio_rig")
