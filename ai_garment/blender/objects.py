"""Create / update garment mesh objects from core GarmentMeshData."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..core.geometry.tube import GarmentMeshData
from ..core.transaction import Transaction
from . import scene as bscene
from ._bpy import get_bpy
from .vertex_groups import read_groups, write_groups


def create_mesh_object(name: str, data: GarmentMeshData, collection: Any, garment_id: str, role: str,
                       tx: Optional[Transaction]) -> Any:
    bpy = get_bpy()
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(v) for v in data.vertices], [tuple(e) for e in data.edges],
                     [tuple(f) for f in data.faces])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bscene.link_new_object(obj, collection, garment_id, role, tx)
    write_groups(obj, data.vertex_groups)
    return obj


def _snapshot(obj: Any) -> Dict[str, Any]:
    mesh = obj.data
    return {"vertices": [tuple(v.co) for v in mesh.vertices], "edges": [tuple(e.vertices) for e in mesh.edges],
            "faces": [tuple(p.vertices) for p in mesh.polygons], "groups": read_groups(obj)}


def _restore(obj: Any, snap: Dict[str, Any]) -> None:
    _clear(obj)
    obj.data.from_pydata(snap["vertices"], snap["edges"], snap["faces"])
    obj.data.update()
    write_groups(obj, snap["groups"])


def _clear(obj: Any) -> None:
    if obj.data.shape_keys is not None:
        obj.shape_key_clear()
    obj.vertex_groups.clear()
    obj.data.clear_geometry()


def replace_geometry(obj: Any, data: GarmentMeshData, tx: Optional[Transaction]) -> None:
    """Regenerate a garment's mesh IN PLACE (object, modifiers and material are kept)."""
    snap = _snapshot(obj)
    _clear(obj)
    obj.data.from_pydata([tuple(v) for v in data.vertices], [tuple(e) for e in data.edges],
                         [tuple(f) for f in data.faces])
    obj.data.update()
    write_groups(obj, data.vertex_groups)
    bscene._tx(tx).record(f"regenerate {obj.name}", lambda: _restore(obj, snap))


def set_local_coords(obj: Any, coords: List[Tuple[float, float, float]]) -> None:
    for v, c in zip(obj.data.vertices, coords):
        v.co = c
    obj.data.update()


def duplicate_object(obj: Any, name: str, collection: Any, garment_id: str, tx: Optional[Transaction]) -> Any:
    new = obj.copy()
    new.data = obj.data.copy()
    new.name = name
    for key in (bscene.TAG_ID, bscene.TAG_ROLE):
        if key in new.keys():
            del new[key]
    bscene.link_new_object(new, collection, garment_id, "garment", tx)
    return new
