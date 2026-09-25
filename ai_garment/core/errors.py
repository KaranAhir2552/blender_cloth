"""Error types and canonical user-facing messages.

Every failure in ai_garment is reported with a stable machine-readable
``code`` plus a human-readable message and, where possible, suggestions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

MSG_AVATAR_NOT_FOUND = "No supported avatar detected. Please select a character or provide avatar metadata."
MSG_COLLISION_ISSUE = "Potential collision issue detected."
MSG_WRINKLES_UNAVAILABLE = ("Wrinkle provider unavailable. "
                            "Simulation can continue without generated wrinkle enhancement.")
MSG_BLENDER_UNAVAILABLE = ("Blender (bpy) is not available in this Python environment. "
                           "Use dry_run=True to plan without Blender, or run inside Blender.")
COLLISION_SUGGESTIONS = ["increase collision margin", "increase simulation quality"]


def provider_fallback_message(unavailable: str, fallback: str) -> str:
    return (f"Provider {unavailable} unavailable. Fallback provider: {fallback}. "
            "Some garment construction features may be unavailable.")


@dataclass
class Issue:
    """A single validation / runtime problem."""

    code: str
    message: str
    severity: str = "error"
    path: Optional[str] = None
    suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"code": self.code, "message": self.message, "severity": self.severity}
        if self.path:
            d["path"] = self.path
        if self.suggestions:
            d["suggestions"] = list(self.suggestions)
        return d


class GarmentError(Exception):
    """Structured exception. ``code`` is stable; ``message`` is for humans."""

    def __init__(self, code: str, message: str, suggestions: Optional[List[str]] = None,
                 details: Optional[Dict[str, Any]] = None, path: Optional[str] = None):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.suggestions = list(suggestions or [])
        self.details = dict(details or {})
        self.path = path

    def to_issue(self) -> Issue:
        return Issue(self.code, self.message, "error", self.path, list(self.suggestions))

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, "suggestions": list(self.suggestions),
                "details": self.details, "path": self.path}
