"""The only gateway to bpy / mathutils.

Resolved at call time (never at import time) so that:
  * the package imports cleanly outside Blender,
  * tests can inject a mock by placing it in ``sys.modules``.
"""
from __future__ import annotations

import importlib
from typing import Any, Optional, Tuple

from ..core.errors import MSG_BLENDER_UNAVAILABLE, GarmentError


def get_bpy() -> Any:
    try:
        return importlib.import_module("bpy")
    except ImportError as err:
        raise GarmentError("BLENDER_UNAVAILABLE", MSG_BLENDER_UNAVAILABLE) from err


def get_mathutils() -> Any:
    try:
        return importlib.import_module("mathutils")
    except ImportError as err:
        raise GarmentError("BLENDER_UNAVAILABLE", MSG_BLENDER_UNAVAILABLE) from err


def get_bvhtree_class() -> Any:
    try:
        return importlib.import_module("mathutils.bvhtree").BVHTree
    except ImportError as err:
        raise GarmentError("BLENDER_UNAVAILABLE", MSG_BLENDER_UNAVAILABLE) from err


def blender_available() -> bool:
    try:
        get_bpy()
        return True
    except GarmentError:
        return False


def blender_version() -> Optional[Tuple[int, ...]]:
    try:
        return tuple(get_bpy().app.version)
    except GarmentError:
        return None


def is_mock() -> bool:
    try:
        return bool(getattr(get_bpy(), "__is_mock__", False))
    except GarmentError:
        return False
