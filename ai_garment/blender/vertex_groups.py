"""Vertex group read/write helpers."""
from __future__ import annotations

from typing import Any, Dict, List


def write_groups(obj: Any, groups: Dict[str, Dict[int, float]]) -> None:
    """Create/replace vertex groups. Weights are bucketed so each ``add`` call gets one weight."""
    for name, weights in groups.items():
        vg = obj.vertex_groups.get(name)
        if vg is None:
            vg = obj.vertex_groups.new(name=name)
        buckets: Dict[float, List[int]] = {}
        for idx, w in weights.items():
            buckets.setdefault(round(float(w), 4), []).append(int(idx))
        for w, idx in buckets.items():
            vg.add(idx, w, "REPLACE")


def read_groups(obj: Any) -> Dict[str, Dict[int, float]]:
    names = {g.index: g.name for g in obj.vertex_groups}
    out: Dict[str, Dict[int, float]] = {n: {} for n in names.values()}
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group in names:
                out[names[g.group]][v.index] = g.weight
    return out


def group_names(obj: Any) -> List[str]:
    return [g.name for g in obj.vertex_groups]
