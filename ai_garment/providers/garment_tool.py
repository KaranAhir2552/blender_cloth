"""Garment Tool adapter (detection + user-configured operator mapping).

Garment Tool is a commercial pattern-based garment add-on. Operator names are
not hard-coded; configure them per PROVIDER_SETUP.md once verified.
"""
from __future__ import annotations

from .external import ExternalAddonProvider


class GarmentToolProvider(ExternalAddonProvider):
    name = "garment_tool"
    display_name = "Garment Tool"
    candidate_modules = ("garment_tool", "garmenttool", "garment_tool_2", "GarmentTool")
    known_features = ("pattern_construction", "sewing", "create_garment")
    priority = 60
