"""Find the human character in the scene and extract raw data for core.avatar_model."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from ..core.avatar_model import AvatarModel, build_avatar_model
from ..core.errors import MSG_AVATAR_NOT_FOUND, GarmentError
from . import scene as bscene
from ._bpy import get_bpy

MIN_SCORE = 3
HUMAN_NAME = re.compile(r"human|body|character|avatar|person|man\b|woman|girl|boy|mpfb|makehuman|basemesh|genesis",
                        re.I)


def _armature_of(obj: Any) -> Optional[Any]:
    arm = obj.find_armature() if hasattr(obj, "find_armature") else None
    if arm is None and obj.parent is not None and obj.parent.type == "ARMATURE":
        arm = obj.parent
    return arm


def _props(obj: Any) -> Dict[str, Any]:
    out = {}
    for k in obj.keys():
        try:
            v = obj[k]
        except KeyError:
            continue
        if isinstance(v, (str, int, float, bool)):
            out[k] = v
    return out


def scan_avatar_candidates() -> List[Dict[str, Any]]:
    """Score mesh objects by how human-like / avatar-like they look."""
    bpy = get_bpy()
    active = bpy.context.active_object
    selected = set(getattr(o, "name", "") for o in (bpy.context.selected_objects or []))
    out = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or bscene.is_tagged(obj):
            continue
        score, ev = 0, []
        if "ai_garment_avatar" in obj.keys():
            score += 6
            ev.append("has ai_garment_avatar metadata")
        arm = _armature_of(obj)
        if arm is not None:
            score += 3
            ev.append(f"deformed by armature '{arm.name}'")
        n = len(obj.data.vertices)
        if n >= 500:
            score += 1
            ev.append(f"{n} vertices")
        props = " ".join(str(k) for k in obj.keys()).lower()
        if "mpfb" in props or "makehuman" in props or "mhx" in props:
            score += 2
            ev.append("MakeHuman/MPFB properties")
        if HUMAN_NAME.search(obj.name):
            score += 1
            ev.append(f"name '{obj.name}' suggests a character")
        if active is not None and active.name == obj.name:
            score += 2
            ev.append("active object")
        elif obj.name in selected:
            score += 1
            ev.append("selected")
        if score > 0:
            out.append({"name": obj.name, "score": score, "evidence": ev, "vertices": n})
    out.sort(key=lambda c: (-c["score"], c["name"]))
    return [c for c in out if c["score"] >= MIN_SCORE]


def extract_avatar_data(obj: Any) -> Dict[str, Any]:
    arm = _armature_of(obj)
    bones = {}
    if arm is not None:
        mw = arm.matrix_world
        if arm.pose is not None and len(arm.pose.bones):
            # PoseBone.head/tail: current pose, armature space
            for pb in arm.pose.bones:
                bones[pb.name] = (tuple(mw @ pb.head), tuple(mw @ pb.tail))
        else:
            # Bone.head is parent-relative; head_local/tail_local are armature space (rest pose)
            for b in arm.data.bones:
                bones[b.name] = (tuple(mw @ b.head_local), tuple(mw @ b.tail_local))
    return {"name": obj.name, "vertices": bscene.world_coords(obj, evaluated=True), "bones": bones or None,
            "vertex_groups": [g.name for g in obj.vertex_groups], "properties": _props(obj),
            "armature": arm.name if arm is not None else None}


def detect_avatar(name: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> AvatarModel:
    """Return an AvatarModel or raise GarmentError(AVATAR_NOT_FOUND)."""
    bpy = get_bpy()
    if name:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH":
            raise GarmentError("AVATAR_NOT_FOUND", f"No mesh object named '{name}'. {MSG_AVATAR_NOT_FOUND}",
                               suggestions=[c["name"] for c in scan_avatar_candidates()])
        evidence = ["requested by name"]
    else:
        cands = scan_avatar_candidates()
        if not cands:
            if metadata:
                return AvatarModel.from_metadata(metadata)
            raise GarmentError("AVATAR_NOT_FOUND", MSG_AVATAR_NOT_FOUND,
                               suggestions=["select the character mesh", "pass avatar='ObjectName'",
                                            "pass metadata={'height': 1.75, 'chest': 0.96, ...}"])
        obj = bpy.data.objects.get(cands[0]["name"])
        evidence = cands[0]["evidence"]
    raw = extract_avatar_data(obj)
    meta = metadata
    if meta is None and "ai_garment_avatar" in obj.keys():
        try:
            val = obj["ai_garment_avatar"]
            meta = json.loads(val) if isinstance(val, str) else dict(val)
        except (ValueError, TypeError) as err:
            raise GarmentError("INVALID_AVATAR_METADATA", f"ai_garment_avatar on '{obj.name}' is not valid JSON: "
                                                          f"{err}") from err
    model = build_avatar_model(raw["name"], raw["vertices"], bones=raw["bones"], vertex_groups=raw["vertex_groups"],
                               properties=raw["properties"], metadata=meta)
    model.evidence = evidence + model.evidence
    model.object_name = obj.name
    return model
