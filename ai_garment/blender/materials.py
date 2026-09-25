"""Fabric-aware Principled BSDF material (colour, roughness, sheen)."""
from __future__ import annotations

from typing import Any, Optional

from ..core.fabric_presets import ResolvedFabric
from ..core.transaction import Transaction
from ..core.vocabulary import parse_color, srgb_to_linear
from . import scene as bscene
from ._bpy import get_bpy

# Blender 4.x names first, then 3.x names.
SHEEN_INPUTS = ("Sheen Weight", "Sheen")


def _set_input(node: Any, names, value: Any) -> bool:
    for n in names:
        sock = node.inputs.get(n)
        if sock is not None:
            sock.default_value = value
            return True
    return False


def ensure_material(obj: Any, garment_id: str, color: Any, fabric: ResolvedFabric,
                    tx: Optional[Transaction]) -> Any:
    bpy = get_bpy()
    r, g, b, a = parse_color(color)
    lin = [srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b), a]
    mat = next((m for m in obj.data.materials if m is not None and m.get(bscene.TAG_ID) == garment_id), None)
    if mat is None:
        mat = bpy.data.materials.new(f"AIG_{obj.name}_{fabric.name}")
        mat[bscene.TAG_ID] = garment_id
        obj.data.materials.append(mat)
        mat_name = mat.name

        def undo() -> None:
            m = bpy.data.materials.get(mat_name)
            if m is not None:
                bpy.data.materials.remove(m)

        bscene._tx(tx).record(f"create material {mat_name}", undo)
    mat.diffuse_color = lin
    mat.roughness = fabric.roughness
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree is not None else None
    if bsdf is not None:
        _set_input(bsdf, ("Base Color",), lin)
        _set_input(bsdf, ("Roughness",), fabric.roughness)
        _set_input(bsdf, SHEEN_INPUTS, fabric.sheen)
    return mat
