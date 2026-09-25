"""MeshBuilder: lofted rings, patches, vertex groups and sewing edges."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .mathutil import Vec3, add, dist, is_finite, scale

GROUP_PREFIX = "AIG_"


@dataclass
class Ring:
    center: Vec3
    u: Vec3
    v: Vec3
    a: float
    b: float

    def point(self, t: float) -> Vec3:
        return add(self.center, add(scale(self.u, self.a * math.cos(t)), scale(self.v, self.b * math.sin(t))))


@dataclass
class GarmentMeshData:
    vertices: List[Vec3]
    faces: List[Tuple[int, ...]]
    edges: List[Tuple[int, int]]
    vertex_groups: Dict[str, Dict[int, float]]
    components: Dict[str, str]
    seams: List[Dict[str, Any]]
    physics: Dict[str, Any]
    stats: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def validate(self) -> List[str]:
        problems: List[str] = []
        n = len(self.vertices)
        if n == 0:
            problems.append("mesh has no vertices")
        for i, v in enumerate(self.vertices):
            if len(v) != 3 or not is_finite(v):
                problems.append(f"vertex {i} is not a finite 3D point")
                break
        for f in self.faces:
            if len(f) < 3 or len(set(f)) != len(f) or not all(0 <= i < n for i in f):
                problems.append(f"invalid face {f}")
                break
        seen = set()
        for e in self.edges:
            if len(e) != 2 or e[0] == e[1] or not all(0 <= i < n for i in e):
                problems.append(f"invalid edge {e}")
                break
            key = tuple(sorted(e))
            if key in seen:
                problems.append(f"duplicate edge {e}")
                break
            seen.add(key)
        for name, weights in self.vertex_groups.items():
            if not all(0 <= i < n and 0.0 <= w <= 1.0 for i, w in weights.items()):
                problems.append(f"vertex group {name} has invalid indices or weights")
        return problems

    def scaled(self, factor: float) -> "GarmentMeshData":
        """Copy with vertex coordinates multiplied by ``factor`` (metres -> scene units)."""
        return GarmentMeshData([scale(v, factor) for v in self.vertices], list(self.faces), list(self.edges),
                               {k: dict(v) for k, v in self.vertex_groups.items()}, dict(self.components),
                               [dict(s) for s in self.seams], dict(self.physics), dict(self.stats),
                               list(self.warnings))


class MeshBuilder:
    def __init__(self) -> None:
        self.vertices: List[Vec3] = []
        self.faces: List[Tuple[int, ...]] = []
        self.edges: List[Tuple[int, int]] = []
        self._edge_set = set()
        self.groups: Dict[str, Dict[int, float]] = {}
        self.seams: List[Dict[str, Any]] = []
        self.warnings: List[str] = []

    def add_tube(self, rings: Sequence[Ring], segments: int,
                 arc: Optional[Tuple[float, float]] = None) -> List[List[int]]:
        """Loft rings. ``arc`` (t0, t1) builds an open strip instead of a closed tube."""
        out: List[List[int]] = []
        count = segments if arc is None else segments + 1
        for ring in rings:
            idx = []
            for k in range(count):
                t = 2.0 * math.pi * k / segments if arc is None else arc[0] + (arc[1] - arc[0]) * k / segments
                idx.append(len(self.vertices))
                self.vertices.append(ring.point(t))
            out.append(idx)
        for r in range(len(out) - 1):
            lo, hi = out[r], out[r + 1]
            for k in range(count if arc is None else count - 1):
                k2 = (k + 1) % count
                self.faces.append((lo[k], lo[k2], hi[k2], hi[k]))
        return out

    def add_patch(self, grid: Sequence[Sequence[Vec3]]) -> List[List[int]]:
        """grid[row][col] points -> quads. Returns index grid."""
        out: List[List[int]] = []
        for row in grid:
            idx = []
            for p in row:
                idx.append(len(self.vertices))
                self.vertices.append(tuple(p))
            out.append(idx)
        for r in range(len(out) - 1):
            for c in range(len(out[r]) - 1):
                self.faces.append((out[r][c], out[r][c + 1], out[r + 1][c + 1], out[r + 1][c]))
        return out

    def assign(self, group: str, indices: Iterable[int], weight: float = 1.0) -> None:
        g = self.groups.setdefault(group, {})
        w = max(0.0, min(1.0, float(weight)))
        for i in indices:
            if w > g.get(i, -1.0):
                g[i] = w

    def sew(self, name: str, a: Sequence[int], b: Sequence[int], max_dist: Optional[float] = None) -> int:
        """Connect every vertex in ``a`` to its nearest vertex in ``b`` with a loose (sewing) edge."""
        b = list(b)
        if not a or not b:
            self.warnings.append(f"Seam {name} skipped: nothing to sew.")
            return 0
        added = 0
        for i in a:
            pi = self.vertices[i]
            j = min(b, key=lambda k: (self.vertices[k][0] - pi[0]) ** 2 + (self.vertices[k][1] - pi[1]) ** 2
                    + (self.vertices[k][2] - pi[2]) ** 2)
            d = dist(pi, self.vertices[j])
            if i == j or (max_dist is not None and d > max_dist):
                continue
            key = (min(i, j), max(i, j))
            if key in self._edge_set:
                continue
            self._edge_set.add(key)
            self.edges.append((i, j))
            added += 1
        self.seams.append({"name": name, "a": name.split(":")[0], "b": name.split(":")[-1], "edges": added})
        return added

    def translate(self, offset: Sequence[float]) -> None:
        if any(offset):
            self.vertices = [add(v, offset) for v in self.vertices]
