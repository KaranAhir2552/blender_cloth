"""Tiny 3D vector helpers (tuples) so core stays free of mathutils."""
from __future__ import annotations

import math
from typing import Sequence, Tuple

Vec3 = Tuple[float, float, float]


def add(a: Sequence[float], b: Sequence[float]) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Sequence[float], b: Sequence[float]) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def scale(a: Sequence[float], k: float) -> Vec3:
    return (a[0] * k, a[1] * k, a[2] * k)


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Sequence[float], b: Sequence[float]) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def length(a: Sequence[float]) -> float:
    return math.sqrt(dot(a, a))


def normalize(a: Sequence[float]) -> Vec3:
    n = length(a)
    return (0.0, 0.0, 1.0) if n < 1e-12 else (a[0] / n, a[1] / n, a[2] / n)


def lerp(a: Sequence[float], b: Sequence[float], t: float) -> Vec3:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def dist(a: Sequence[float], b: Sequence[float]) -> float:
    return length(sub(a, b))


def lerp1(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def basis_for_axis(axis: Sequence[float]) -> Tuple[Vec3, Vec3]:
    """(u, v) with u x v = axis; u is the sideways (+X) direction projected off the axis.

    Quads lofted ring-by-ring along +axis with points ``c + a cos t u + b sin t v``
    then have outward-facing normals.
    """
    ax = normalize(axis)
    for prefer in ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)):
        u = sub(prefer, scale(ax, dot(prefer, ax)))
        if dot(u, u) > 0.01:
            u = normalize(u)
            return u, cross(ax, u)
    raise ValueError("degenerate axis")


def is_finite(v: Sequence[float]) -> bool:
    return all(math.isfinite(c) for c in v)
