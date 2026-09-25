"""Frame stepping, settling, baking. Uses Blender's own cloth solver.

Baking uses ``bpy.ops.ptcache.bake_from_cache`` (after stepping the frames,
which fills the cache) with ``Context.temp_override(point_cache=...)``, and
falls back to ``bpy.ops.ptcache.bake(bake=True)``. The exact context an
operator needs can differ between Blender versions; failures are reported,
never hidden. tests/blender/run_blender_tests.py exercises this path.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from ..core.diagnostics import analyze_settling
from ..core.errors import GarmentError
from . import scene as bscene
from ._bpy import get_bpy
from .modifiers import cloth_only_evaluation

SETTLED_KEY = "AIG_Settled"


def configure_cache(cloth_mod: Any, frame_start: int, frame_end: int, disk: bool = False) -> None:
    pc = cloth_mod.point_cache
    pc.frame_start = int(frame_start)
    pc.frame_end = int(frame_end)
    pc.use_disk_cache = bool(disk)


def _mean_displacement(a: List[tuple], b: List[tuple]) -> float:
    if not a or len(a) != len(b):
        return float("inf")
    return sum(math.dist(p, q) for p, q in zip(a, b)) / len(a)


def settle(obj: Any, cloth_mod: Any, frame_start: int, max_frames: int, threshold: float, window: int) -> Dict:
    """Step the solver from ``frame_start`` until motion stays below ``threshold``."""
    scene = bscene.current_scene()
    if cloth_mod.point_cache.frame_end < frame_start + max_frames:
        cloth_mod.point_cache.frame_end = frame_start + max_frames
    displacements: List[float] = []
    with cloth_only_evaluation(obj):
        scene.frame_set(frame_start)
        prev = bscene.world_coords(obj, evaluated=True, local=True)
        calm = 0
        for f in range(frame_start + 1, frame_start + max_frames + 1):
            scene.frame_set(f)
            cur = bscene.world_coords(obj, evaluated=True, local=True)
            d = _mean_displacement(prev, cur)
            if not math.isfinite(d):
                raise GarmentError("SIMULATION_UNSTABLE", f"Cloth vertex data became invalid at frame {f}.",
                                   suggestions=["increase simulation quality", "reduce stiffness"])
            displacements.append(d)
            prev = cur
            calm = calm + 1 if d < threshold else 0
            if calm >= window:
                break
        final_local = prev
    diag = analyze_settling(displacements, threshold, window)
    settled_at = diag.data["settled_at"]
    return {"settled": diag.data["settled"], "frames_run": len(displacements),
            "settled_frame": frame_start + 1 + settled_at if settled_at is not None else None,
            "final_motion": displacements[-1] if displacements else 0.0, "threshold": threshold,
            "diagnostic": diag.to_dict(), "final_local_coords": final_local}


def apply_settled_shape(obj: Any, local_coords: List[tuple]) -> str:
    """Store the settled drape as shape key 'AIG_Settled' (value 1.0). Non-destructive:
    the Basis keeps the original shape; removing the key restores it."""
    if len(local_coords) != len(obj.data.vertices):
        raise GarmentError("SETTLE_APPLY_FAILED", "Settled vertex count does not match the garment mesh.")
    if obj.data.shape_keys is None:
        obj.shape_key_add(name="Basis", from_mix=False)
    existing = obj.data.shape_keys.key_blocks.get(SETTLED_KEY)
    if existing is not None:
        obj.shape_key_remove(existing)
    key = obj.shape_key_add(name=SETTLED_KEY, from_mix=False)
    for point, co in zip(key.data, local_coords):
        point.co = co
    key.value = 1.0
    return key.name


def remove_settled_shape(obj: Any) -> bool:
    keys = obj.data.shape_keys
    if keys is None:
        return False
    k = keys.key_blocks.get(SETTLED_KEY)
    if k is None:
        return False
    obj.shape_key_remove(k)
    return True


def bake(obj: Any, cloth_mod: Any, frame_start: int, frame_end: int) -> Dict[str, Any]:
    bpy = get_bpy()
    scene = bscene.current_scene()
    configure_cache(cloth_mod, frame_start, frame_end, cloth_mod.point_cache.use_disk_cache)
    for f in range(frame_start, frame_end + 1):
        scene.frame_set(f)
    errors: List[str] = []
    for op_name, kwargs in (("bake_from_cache", {}), ("bake", {"bake": True})):
        try:
            with bpy.context.temp_override(point_cache=cloth_mod.point_cache, object=obj,
                                           active_object=obj, scene=scene):
                getattr(bpy.ops.ptcache, op_name)(**kwargs)
            if cloth_mod.point_cache.is_baked:
                scene.frame_set(frame_start)
                return {"baked": True, "method": f"ptcache.{op_name}", "frames": [frame_start, frame_end]}
        except (RuntimeError, TypeError, AttributeError) as err:
            errors.append(f"ptcache.{op_name}: {err}")
    scene.frame_set(frame_start)
    return {"baked": False, "frames": [frame_start, frame_end], "errors": errors,
            "note": "Frames were simulated into the in-memory cache but could not be marked as baked."}


def free_bake(obj: Any, cloth_mod: Any) -> bool:
    if not cloth_mod.point_cache.is_baked:
        return False
    bpy = get_bpy()
    with bpy.context.temp_override(point_cache=cloth_mod.point_cache, object=obj, active_object=obj):
        bpy.ops.ptcache.free_bake()
    return True


def evaluated_world(obj: Any) -> List[tuple]:
    with cloth_only_evaluation(obj):
        return bscene.world_coords(obj, evaluated=True)


def scene_frame(frame: Optional[int]) -> None:
    if frame is not None:
        bscene.current_scene().frame_set(int(frame))
