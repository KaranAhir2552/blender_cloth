"""AI Garment Orchestrator.

A Blender add-on / extension that lets Claude (or any caller) create, fit,
modify and simulate clothing through a small, validated, high-level API
on top of Blender's native cloth tools and optional garment add-ons.

    from ai_garment import garment
    shirt = garment.create(type="tshirt", fit="oversized", fabric="cotton", color="black")
    shirt.fit_to_avatar()
    shirt.simulate(mode="natural")

Importing this package never imports bpy; Blender-specific code runs only
when called inside Blender.
"""
from __future__ import annotations

import sys

bl_info = {
    "name": "AI Garment Orchestrator",
    "author": "AI Garment contributors",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > AI Garment",
    "description": "High-level, validated garment creation / fitting / simulation API for AI assistants",
    "category": "Physics",
}

from .api import commands  # noqa: E402
from .api.garment import AvatarHandle, Garment, GarmentSystem, garment, garment_system  # noqa: E402
from .core.errors import GarmentError  # noqa: E402
from .core.garment_spec import GarmentSpec  # noqa: E402
from .core.nl_mapping import parse_instruction  # noqa: E402
from .core.results import Result  # noqa: E402

__all__ = ["garment", "garment_system", "Garment", "GarmentSystem", "AvatarHandle", "GarmentSpec", "GarmentError",
           "Result", "parse_instruction", "commands", "register", "unregister", "bl_info"]

_ALIASED = False


def register() -> None:
    """Blender entry point. Also makes ``import ai_garment`` work when installed as an
    extension (where the real module name is ``bl_ext.<repo>.ai_garment``)."""
    global _ALIASED
    from .blender import ui

    ui.register()
    if __name__ != "ai_garment" and "ai_garment" not in sys.modules:
        sys.modules["ai_garment"] = sys.modules[__name__]
        _ALIASED = True


def unregister() -> None:
    global _ALIASED
    from .blender import ui

    ui.unregister()
    if _ALIASED and sys.modules.get("ai_garment") is sys.modules.get(__name__):
        del sys.modules["ai_garment"]
        _ALIASED = False
