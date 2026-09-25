"""Modifier helpers. Only modifiers whose name starts with ``AIG_`` are ever removed."""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from ..core.errors import GarmentError
from ..core.transaction import Transaction
from . import scene as bscene
from ._bpy import get_bpy

PREFIX = "AIG_"
CLOTH = "AIG_Cloth"
COLLISION = "AIG_Collision"
SOLIDIFY = "AIG_Solidify"
SUBSURF = "AIG_Subsurf"
MASK = "AIG_Mask"
DECIMATE = "AIG_Decimate"
POST_CLOTH = (SOLIDIFY, SUBSURF)


def of_type(obj: Any, mod_type: str) -> List[Any]:
    return [m for m in obj.modifiers if m.type == mod_type]


def get_or_add(obj: Any, name: str, mod_type: str, tx: Optional[Transaction]) -> Tuple[Any, bool]:
    mod = obj.modifiers.get(name)
    if mod is not None:
        if mod.type != mod_type:
            raise GarmentError("MODIFIER_CONFLICT", f"'{obj.name}' has a modifier '{name}' of type {mod.type}, "
                                                    f"expected {mod_type}.")
        return mod, False
    mod = obj.modifiers.new(name=name, type=mod_type)
    obj_ref, mod_name = obj, mod.name

    def undo() -> None:
        m = obj_ref.modifiers.get(mod_name)
        if m is not None:
            obj_ref.modifiers.remove(m)

    bscene._tx(tx).record(f"add {mod_type} modifier to {obj.name}", undo)
    return mod, True


def remove_own(obj: Any, name: str) -> bool:
    if not name.startswith(PREFIX):
        raise GarmentError("UNSAFE_DELETE", f"Refusing to remove modifier '{name}' that ai_garment did not create.")
    mod = obj.modifiers.get(name)
    if mod is None:
        return False
    obj.modifiers.remove(mod)
    return True


def ensure_post_cloth(obj: Any, solidify_thickness: float, subdiv_viewport: int, subdiv_render: int,
                      tx: Optional[Transaction]) -> None:
    """Solidify + Subdivision must come AFTER the cloth modifier (cloth simulates the thin mesh)."""
    names = [m.name for m in obj.modifiers]
    if CLOTH in names and any(n in names and names.index(n) < names.index(CLOTH) for n in POST_CLOTH):
        for n in POST_CLOTH:
            if n in names:
                remove_own(obj, n)
    sol, _ = get_or_add(obj, SOLIDIFY, "SOLIDIFY", tx)
    sol.thickness = solidify_thickness
    sol.offset = 1.0  # grow outward, away from the body
    sol.use_even_offset = True
    sub, _ = get_or_add(obj, SUBSURF, "SUBSURF", tx)
    sub.levels = int(subdiv_viewport)
    sub.render_levels = int(subdiv_render)


class cloth_only_evaluation:
    """Context manager: hide post-cloth modifiers so evaluated meshes have the
    cloth vertex count (Solidify/Subsurf change topology)."""

    def __init__(self, obj: Any):
        self.obj = obj
        self.saved: List[Tuple[Any, bool]] = []

    def __enter__(self) -> "cloth_only_evaluation":
        for n in POST_CLOTH:
            m = self.obj.modifiers.get(n)
            if m is not None and m.show_viewport:
                self.saved.append((m, True))
                m.show_viewport = False
        if self.saved:
            get_bpy().context.view_layer.update()  # re-evaluate so reads see the cloth-only mesh
        return self

    def __exit__(self, *exc: Any) -> bool:
        for m, state in self.saved:
            m.show_viewport = state
        if self.saved:
            get_bpy().context.view_layer.update()
        return False
