"""Simply Cloth Studio adapter (detection + user-configured operator mapping).

Simply Cloth is a commercial Blender cloth workflow add-on. Operator names are
not hard-coded; configure them per PROVIDER_SETUP.md once verified.
"""
from __future__ import annotations

from .external import ExternalAddonProvider


class SimplyClothProvider(ExternalAddonProvider):
    name = "simply_cloth"
    display_name = "Simply Cloth Studio"
    candidate_modules = ("simply_cloth", "simplycloth", "simply_cloth_studio", "simplyclothstudio",
                         "simply_cloth_pro", "SimplyCloth")
    known_features = ("simulate", "wrinkles", "pinning", "sewing")
    priority = 55
