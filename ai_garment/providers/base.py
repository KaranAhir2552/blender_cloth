"""Provider interface. A provider is any system that can build or simulate
garments: Blender native cloth, or an adapter around an installed add-on.

Every method returns a structured Result. Unsupported capabilities return a
CAPABILITY_NOT_SUPPORTED failure; nothing fails silently.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional

from ..core.results import Result
from ..core.transaction import Transaction


class Capability:
    CREATE_GARMENT = "create_garment"
    PATTERN_CONSTRUCTION = "pattern_construction"
    SEWING = "sewing"
    FIT = "fit"
    FABRIC = "fabric"
    COMPONENTS = "components"
    ELASTIC = "elastic"
    COLLISION = "collision"
    SELF_COLLISION = "self_collision"
    SIMULATE = "simulate"
    SETTLE = "settle"
    BAKE = "bake"
    WRINKLES = "wrinkles"
    PINNING = "pinning"
    MATERIALS = "materials"
    INSPECT = "inspect"
    ALL: FrozenSet[str] = frozenset({
        "create_garment", "pattern_construction", "sewing", "fit", "fabric", "components", "elastic", "collision",
        "self_collision", "simulate", "settle", "bake", "wrinkles", "pinning", "materials", "inspect"})
    CORE: FrozenSet[str] = frozenset({
        "create_garment", "sewing", "fit", "fabric", "components", "elastic", "collision", "self_collision",
        "simulate", "settle", "bake", "pinning", "materials", "inspect"})


@dataclass
class ProviderStatus:
    name: str
    display_name: str
    available: bool
    reason: str
    version: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "display_name": self.display_name, "available": self.available,
                "reason": self.reason, "version": self.version, "capabilities": list(self.capabilities),
                "details": dict(self.details)}


class GarmentProvider(ABC):
    name: str = "base"
    display_name: str = "Base provider"
    priority: int = 0
    capabilities: FrozenSet[str] = frozenset()
    _tx: Optional[Transaction] = None

    @abstractmethod
    def available(self) -> ProviderStatus:
        """Must never raise; report problems in the status."""

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    def bind_transaction(self, tx: Optional[Transaction]) -> None:
        self._tx = tx

    @property
    def tx(self) -> Transaction:
        if self._tx is None:
            self._tx = Transaction(f"{self.name}-untracked")
        return self._tx

    def _unsupported(self, action: str, capability: str) -> Result:
        return Result.failure(action, "CAPABILITY_NOT_SUPPORTED",
                              f"{self.display_name} does not support '{capability}'.",
                              ["use a provider that supports it", "the orchestrator routes to Blender native "
                                                                 "cloth when possible"])

    # --- operations (override what you support) -----------------------------------
    def create_garment(self, record: Any, avatar: Any, context: Optional[Dict[str, Any]] = None) -> Result:
        return self._unsupported("create_garment", Capability.CREATE_GARMENT)

    def update_garment(self, record: Any, effects: Any, avatar: Any = None,
                       context: Optional[Dict[str, Any]] = None) -> Result:
        return self._unsupported("update_garment", Capability.COMPONENTS)

    def fit_garment(self, record: Any, avatar: Any, context: Optional[Dict[str, Any]] = None) -> Result:
        return self._unsupported("fit_garment", Capability.FIT)

    def sew(self, record: Any, seams: Optional[List[str]] = None) -> Result:
        return self._unsupported("sew", Capability.SEWING)

    def set_fabric(self, record: Any, fabric: Any = None) -> Result:
        return self.update_garment(record, frozenset({"physics", "material"}))

    def add_component(self, record: Any, component: Any = None) -> Result:
        return self.update_garment(record, frozenset({"geometry", "physics"}))

    def prepare_collision(self, avatar: Any, settings: Optional[Dict[str, Any]] = None) -> Result:
        return self._unsupported("prepare_collision", Capability.COLLISION)

    def remove_collision(self, avatar: Any) -> Result:
        return self._unsupported("remove_collision", Capability.COLLISION)

    def enable_self_collision(self, record: Any, preset: str = "preview") -> Result:
        return self._unsupported("enable_self_collision", Capability.SELF_COLLISION)

    def simulate(self, record: Any, settings: Dict[str, Any], avatar: Any = None) -> Result:
        return self._unsupported("simulate", Capability.SIMULATE)

    def settle(self, record: Any, settings: Dict[str, Any], avatar: Any = None) -> Result:
        return self._unsupported("settle", Capability.SETTLE)

    def bake(self, record: Any, settings: Optional[Dict[str, Any]] = None) -> Result:
        return self._unsupported("bake", Capability.BAKE)

    def reset(self, record: Any, level: str = "simulation") -> Result:
        return self._unsupported("reset", Capability.SIMULATE)

    def generate_wrinkles(self, record: Any, settings: Optional[Dict[str, Any]] = None) -> Result:
        return self._unsupported("generate_wrinkles", Capability.WRINKLES)

    def inspect(self, record: Any) -> Dict[str, Any]:
        return {"id": getattr(record, "id", None), "provider": self.display_name,
                "warnings": [f"{self.display_name} does not implement inspection."]}

    def delete_garment(self, record: Any) -> Result:
        return self._unsupported("delete_garment", Capability.CREATE_GARMENT)

    def duplicate_garment(self, record: Any, new_record: Any) -> Result:
        return self._unsupported("duplicate_garment", Capability.CREATE_GARMENT)
