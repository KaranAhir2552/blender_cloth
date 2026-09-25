"""Registry of geometry recipes ("builders") used by garment types.

A recipe is ``fn(ctx: BuildContext) -> None``: it adds panels to
``ctx.mb`` and records them in ``ctx.panels``. Built-ins (top, pants, skirt,
dress) are registered by geometry.builder.
"""
from __future__ import annotations

import importlib
from typing import Callable, Dict

from ..errors import GarmentError

_RECIPES: Dict[str, Callable] = {}


def register_builder_recipe(name: str, fn: Callable, replace: bool = False) -> None:
    if name in _RECIPES and not replace:
        raise GarmentError("DUPLICATE_RECIPE", f"Builder recipe '{name}' already registered.")
    _RECIPES[name] = fn


def _ensure_builtins() -> None:
    if not _RECIPES:
        importlib.import_module(".builder", __package__)  # registers built-in recipes on import


def has_recipe(name: str) -> bool:
    _ensure_builtins()
    return name in _RECIPES


def get_recipe(name: str) -> Callable:
    _ensure_builtins()
    if name not in _RECIPES:
        raise GarmentError("UNKNOWN_RECIPE", f"No geometry recipe named '{name}'.", suggestions=sorted(_RECIPES))
    return _RECIPES[name]
