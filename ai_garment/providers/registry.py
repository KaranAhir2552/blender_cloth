"""Provider registry: detection, selection, per-capability routing, fallback."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from ..core.errors import Issue, provider_fallback_message
from ..core.logging_utils import log_event
from .base import GarmentProvider, ProviderStatus


@dataclass
class Selection:
    provider: Optional[GarmentProvider]
    status: Optional[ProviderStatus] = None
    fallback_used: bool = False
    warnings: List[str] = field(default_factory=list)
    considered: List[ProviderStatus] = field(default_factory=list)
    error: Optional[Issue] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"provider": self.provider.name if self.provider else None,
                "display_name": self.provider.display_name if self.provider else None,
                "fallback_used": self.fallback_used, "warnings": list(self.warnings),
                "considered": [s.to_dict() for s in self.considered],
                "error": self.error.to_dict() if self.error else None}


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: Dict[str, GarmentProvider] = {}

    def register(self, provider: GarmentProvider, replace: bool = False) -> None:
        if provider.name in self._providers and not replace:
            raise ValueError(f"provider '{provider.name}' already registered")
        self._providers[provider.name] = provider

    def unregister(self, name: str) -> None:
        self._providers.pop(name, None)

    def providers(self) -> List[GarmentProvider]:
        return list(self._providers.values())

    def get(self, name: Optional[str]) -> Optional[GarmentProvider]:
        return self._providers.get(name) if name else None

    @staticmethod
    def status_of(provider: GarmentProvider) -> ProviderStatus:
        try:
            return provider.available()
        except Exception as err:  # adapters must not crash the orchestrator; reported in the status
            return ProviderStatus(provider.name, provider.display_name, False,
                                  f"availability check failed: {type(err).__name__}: {err}")

    def statuses(self) -> List[ProviderStatus]:
        return [self.status_of(p) for p in self.providers()]

    def select(self, required: Iterable[str] = (), preferred: Optional[str] = None, log: bool = True) -> Selection:
        req = set(required)
        statuses = {p.name: self.status_of(p) for p in self.providers()}
        candidates = sorted((p for p in self.providers() if statuses[p.name].available and req <= p.capabilities),
                            key=lambda p: -p.priority)
        warnings: List[str] = []
        chosen = candidates[0] if candidates else None
        fallback = False
        pref = self.get(preferred)
        if preferred and pref is None:
            warnings.append(f"Preferred provider '{preferred}' is not registered.")
        if pref is not None:
            if pref in candidates:
                chosen = pref
            else:
                fallback = chosen is not None
                if chosen is not None:
                    warnings.append(provider_fallback_message(pref.display_name, chosen.display_name))
                if not statuses[pref.name].available:
                    warnings.append(f"{pref.display_name}: {statuses[pref.name].reason}")
                elif not req <= pref.capabilities:
                    warnings.append(f"{pref.display_name} lacks {sorted(req - pref.capabilities)}.")
        sel = Selection(chosen, statuses.get(chosen.name) if chosen else None, fallback, warnings,
                        list(statuses.values()))
        if chosen is None:
            reasons = "; ".join(f"{s.display_name}: {s.reason}" for s in statuses.values())
            sel.error = Issue("NO_PROVIDER_AVAILABLE", f"No available provider supports {sorted(req)}. {reasons}",
                              suggestions=["run inside Blender", "install/enable a garment add-on",
                                           "use dry_run=True to plan without Blender"])
        elif log:
            log_event("Provider", chosen.display_name)
        return sel

    def provider_for(self, capability: str, preferred: Optional[str] = None) -> Optional[GarmentProvider]:
        return self.select({capability}, preferred, log=False).provider


def default_registry() -> ProviderRegistry:
    from .blender_native import BlenderNativeProvider
    from .garment_tool import GarmentToolProvider
    from .opensew import OpenSewProvider
    from .simply_cloth import SimplyClothProvider

    reg = ProviderRegistry()
    for p in (BlenderNativeProvider(), OpenSewProvider(), SimplyClothProvider(), GarmentToolProvider()):
        reg.register(p)
    return reg
