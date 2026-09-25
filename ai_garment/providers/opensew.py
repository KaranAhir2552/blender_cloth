"""OpenSew adapter (detection + user-configured operator mapping).

OpenSew is a free Blender add-on for pattern-based garment sewing. Its module
and operator names are NOT hard-coded as facts here; configure them per
PROVIDER_SETUP.md once verified in your Blender installation.
"""
from __future__ import annotations

from .external import ExternalAddonProvider


class OpenSewProvider(ExternalAddonProvider):
    name = "opensew"
    display_name = "OpenSew"
    candidate_modules = ("opensew", "open_sew", "opensew2", "opensew_2", "OpenSew")
    known_features = ("pattern_construction", "sewing")
    priority = 60
