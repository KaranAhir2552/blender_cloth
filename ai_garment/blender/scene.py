"""Scene safety: tagging, safe removal, collections, journaled scene settings."""
from __future__ import annotations

from typing import Any, Iterable, List, Optional, Tuple

from ..core.errors import GarmentError
from ..core.transaction import Transaction
from ._bpy import get_bpy, get_mathutils

TAG_ID = "ai_garment_id"
TAG_ROLE = "ai_garment_role"
TAG_SPEC = "ai_garment_spec"
TAG_RECORD = "ai_garment_record"
TAG_AVATAR_SOURCE = "ai_garment_avatar_source"
COLLECTION_NAME = "AI Garments"


def _tx(tx: Optional[Transaction]) -> Transaction:
    return tx if tx is not None else Transaction("untracked")


def tag(obj: Any, garment_id: str, role: str) -> None:
    obj[TAG_ID] = garment_id
    obj[TAG_ROLE] = role


def is_tagged(obj: Any, garment_id: Optional[str] = None) -> bool:
    gid = obj.get(TAG_ID)
    return gid is not None and (garment_id is None or gid == garment_id)


def find_tagged(garment_id: Optional[str] = None, role: Optional[str] = None) -> List[Any]:
    bpy = get_bpy()
    return [o for o in bpy.data.objects
            if is_tagged(o, garment_id) and (role is None or o.get(TAG_ROLE) == role)]


def safe_remove_object(obj: Any, garment_id: str) -> None:
    """Delete an object ONLY if it was created by ai_garment for ``garment_id``."""
    if not is_tagged(obj, garment_id):
        raise GarmentError("UNSAFE_DELETE", f"Refusing to delete '{obj.name}': it was not created by ai_garment "
                                            f"for garment '{garment_id}'.")
    bpy = get_bpy()
    mesh = obj.data if obj.type == "MESH" else None
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and getattr(mesh, "users", 1) == 0:
        bpy.data.meshes.remove(mesh)


def ensure_collection(tx: Optional[Transaction] = None, name: str = COLLECTION_NAME) -> Any:
    bpy = get_bpy()
    coll = bpy.data.collections.get(name)
    if coll is not None:
        return coll
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
    coll_name = coll.name

    def undo() -> None:
        c = bpy.data.collections.get(coll_name)
        if c is not None and not list(c.objects):
            bpy.context.scene.collection.children.unlink(c)
            bpy.data.collections.remove(c)

    _tx(tx).record(f"create collection {coll_name}", undo)
    return coll


def link_new_object(obj: Any, collection: Any, garment_id: str, role: str, tx: Optional[Transaction]) -> None:
    collection.objects.link(obj)
    tag(obj, garment_id, role)
    bpy = get_bpy()
    name = obj.name

    def undo() -> None:
        o = bpy.data.objects.get(name)
        if o is not None:
            safe_remove_object(o, garment_id)

    _tx(tx).record(f"create object {name}", undo)


def set_attr(target: Any, attr: str, value: Any, tx: Optional[Transaction], label: str = "") -> None:
    """Set an attribute and journal the previous value (only if it changes)."""
    old = getattr(target, attr)
    if isinstance(old, (list, tuple)) or hasattr(old, "__len__") and not isinstance(old, str):
        old = tuple(old)
    if old == value:
        return
    setattr(target, attr, value)
    _tx(tx).record(f"set {label or attr}", lambda: setattr(target, attr, old))


def current_scene() -> Any:
    return get_bpy().context.scene


def world_coords(obj: Any, evaluated: bool = True, local: bool = False) -> List[Tuple[float, float, float]]:
    """Vertex positions (world space unless ``local``) of the evaluated or original mesh."""
    bpy = get_bpy()
    if evaluated:
        dg = bpy.context.evaluated_depsgraph_get()
        eo = obj.evaluated_get(dg)
        mesh = eo.to_mesh()
        try:
            coords = [tuple(v.co) for v in mesh.vertices]
        finally:
            eo.to_mesh_clear()
    else:
        coords = [tuple(v.co) for v in obj.data.vertices]
    if local:
        return coords
    mw = obj.matrix_world
    return [tuple(mw @ _vec(c)) for c in coords]


def polygons(obj: Any) -> List[Tuple[int, ...]]:
    return [tuple(p.vertices) for p in obj.data.polygons]


def _vec(c: Iterable[float]) -> Any:
    return get_mathutils().Vector(tuple(c))


def bbox(coords: List[Tuple[float, float, float]]) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    xs, ys, zs = zip(*coords)
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))
