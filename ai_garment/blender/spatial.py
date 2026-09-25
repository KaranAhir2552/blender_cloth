"""Body-surface queries with mathutils.bvhtree (nearest point + normal)."""
from __future__ import annotations

from typing import Any, Callable, List, Optional, Sequence, Tuple

from ..core.geometry.builder import push_out, signed_clearance
from . import scene as bscene
from ._bpy import get_bvhtree_class

Nearest = Callable[[Sequence[float]], Tuple[Optional[tuple], Optional[tuple]]]


def body_nearest(avatar_obj: Any, max_distance: float = 1.0e3) -> Nearest:
    """Nearest-surface function in WORLD space for the evaluated (posed) avatar."""
    BVHTree = get_bvhtree_class()
    verts = bscene.world_coords(avatar_obj, evaluated=True)
    bvh = BVHTree.FromPolygons(verts, bscene.polygons(avatar_obj))

    def nearest(p: Sequence[float]):
        loc, normal, _idx, _dist = bvh.find_nearest(tuple(p), max_distance)
        if loc is None:
            return None, None
        return tuple(loc), tuple(normal)

    return nearest


def signed_distances(nearest: Nearest, points: List[tuple]) -> List[float]:
    return signed_clearance(points, nearest)


def push_out_points(nearest: Nearest, points: List[tuple], margin: float) -> int:
    return push_out(points, nearest, margin)
