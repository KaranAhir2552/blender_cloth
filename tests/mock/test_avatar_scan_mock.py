import json

import pytest

from ai_garment.api.garment import GarmentSystem
from ai_garment.blender.avatar_scan import scan_avatar_candidates
from ai_garment.core.errors import MSG_AVATAR_NOT_FOUND
from fixtures.humanoid import make_humanoid
from mocks.mock_bpy import build_humanoid_scene


def test_makehuman_candidate_with_evidence(mock_bpy, humanoid):
    build_humanoid_scene(mock_bpy, humanoid)
    cands = scan_avatar_candidates()
    assert cands[0]["name"] == "Human"
    assert cands[0]["score"] > 0
    joined = " ".join(cands[0]["evidence"]).lower()
    assert "armature" in joined and "makehuman" in joined


def test_active_object_preferred(mock_bpy):
    a, _ = build_humanoid_scene(mock_bpy, make_humanoid(rig="mixamo"), name="Alice")
    b, _ = build_humanoid_scene(mock_bpy, make_humanoid(rig="makehuman"), name="Bob")
    mock_bpy.context.active_object = a
    av = GarmentSystem().detect_avatar()
    assert av.name == "Alice"
    assert av.model.source == "mixamo"


def test_detect_by_name(mock_bpy):
    build_humanoid_scene(mock_bpy, make_humanoid(), name="Alice")
    build_humanoid_scene(mock_bpy, make_humanoid(), name="Bob")
    assert GarmentSystem().detect_avatar(name="Bob").name == "Bob"
    missing = GarmentSystem().detect_avatar(name="Carol")
    assert not missing.ok and missing.result.errors[0].code == "AVATAR_NOT_FOUND"


def test_metadata_property_overrides(mock_bpy, humanoid):
    body, _ = build_humanoid_scene(mock_bpy, humanoid)
    body["ai_garment_avatar"] = json.dumps({"chest": 1.02, "units": "m"})
    av = GarmentSystem().detect_avatar()
    assert av.get_measurements()["chest_circumference"] == pytest.approx(1.02)


def test_non_human_mesh_ignored(mock_bpy):
    cube = [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    mock_bpy.make_mesh_object("Cube", cube, [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6),
                                             (0, 2, 6, 4), (1, 5, 7, 3)])
    av = GarmentSystem().detect_avatar()
    assert not av.ok
    assert av.result.errors[0].message == MSG_AVATAR_NOT_FOUND


def test_explicit_metadata_avatar_without_scene(mock_bpy):
    av = GarmentSystem().detect_avatar(metadata={"height": 1.8, "chest": 1.0, "waist": 0.85, "hip": 1.0})
    assert av.ok and av.model.source == "metadata"


def test_armature_less_mesh_uses_generic(mock_bpy, humanoid):
    build_humanoid_scene(mock_bpy, humanoid, with_armature=False)
    av = GarmentSystem().detect_avatar()
    assert av.ok
    assert av.model.source in ("generic", "makehuman")
    assert av.model.warnings
