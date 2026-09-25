"""GarmentRecord: runtime + persisted state of one garment (pure data)."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .garment_spec import GarmentSpec


@dataclass
class GarmentRecord:
    id: str
    spec: GarmentSpec
    provider: str
    name: str
    object_name: Optional[str] = None
    avatar_name: Optional[str] = None
    proxy_name: Optional[str] = None
    unit_scale: float = 1.0
    state: Dict[str, Any] = field(default_factory=lambda: {"fitted": False, "collision": False, "simulated": False,
                                                            "settled": False, "baked": False})
    history: List[str] = field(default_factory=list)
    created: float = field(default_factory=time.time)

    @classmethod
    def new(cls, spec: GarmentSpec, provider: str, name: Optional[str] = None) -> "GarmentRecord":
        gid = "g_" + uuid.uuid4().hex[:10]
        return cls(gid, spec.copy(), provider, name or spec.name or spec.display_name)

    def summary(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "type": self.spec.type, "provider": self.provider,
                "object": self.object_name, "avatar": self.avatar_name, "state": dict(self.state)}

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "spec": self.spec.to_dict(), "provider": self.provider, "name": self.name,
                "object_name": self.object_name, "avatar_name": self.avatar_name, "proxy_name": self.proxy_name,
                "unit_scale": self.unit_scale, "state": dict(self.state), "history": list(self.history[-50:]),
                "created": self.created}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "GarmentRecord":
        return cls(d["id"], GarmentSpec.from_dict(d["spec"]), d.get("provider", "blender_native"),
                   d.get("name") or d["id"], d.get("object_name"), d.get("avatar_name"), d.get("proxy_name"),
                   float(d.get("unit_scale", 1.0)), dict(d.get("state", {})), list(d.get("history", [])),
                   float(d.get("created", time.time())))
