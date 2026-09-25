"""Shared adapter for third-party garment add-ons.

We do NOT know (and cannot verify here) the Python module names or operator
ids of OpenSew, Simply Cloth Studio or Garment Tool. Instead of inventing an
API, adapters:

  1. detect the add-on by comparing enabled add-on module names (including
     Blender 4.2 extension names ``bl_ext.<repo>.<id>``) with configurable
     candidate names;
  2. expose ONLY the capabilities for which the user configured a *verified*
     operator mapping (``operator_map={capability: "namespace.operator"}``),
     optionally with keyword templates (``{type}``, ``{fabric}``, ``{fit}``,
     ``{color}``);
  3. report "unavailable" with a clear reason otherwise, so the registry
     falls back to Blender native cloth.

Mappings can also come from a JSON file named by ``AI_GARMENT_PROVIDER_CONFIG``:
``{"opensew": {"modules": [...], "operators": {...}, "kwargs": {...}}}``.
The add-on is never imported directly.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from ..core.errors import GarmentError
from ..core.results import Result
from ..core.vocabulary import normalize
from ..blender import scene as bscene
from ..blender._bpy import get_bpy
from .base import GarmentProvider, ProviderStatus

CONFIG_ENV = "AI_GARMENT_PROVIDER_CONFIG"


def _load_config(name: str) -> Dict[str, Any]:
    path = os.environ.get(CONFIG_ENV)
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return dict(data.get(name, {}))


def operator_exists(bpy: Any, idname: str) -> bool:
    """True if ``bpy.ops.<ns>.<op>`` is registered.

    Real Blender returns an operator wrapper for ANY attribute name, so we also
    ask for its RNA type, which raises if the operator is not registered.
    """
    try:
        ns, op = idname.split(".", 1)
    except ValueError:
        return False
    mod = getattr(bpy.ops, ns, None)
    fn = getattr(mod, op, None) if mod is not None else None
    if fn is None:
        return False
    get_rna = getattr(fn, "get_rna_type", None)
    if get_rna is None:
        return True
    try:
        get_rna()
        return True
    except (KeyError, RuntimeError, AttributeError):
        return False


class ExternalAddonProvider(GarmentProvider):
    candidate_modules: Tuple[str, ...] = ()
    known_features: Tuple[str, ...] = ()  # what the add-on is known for (documentation only)
    homepage: str = ""
    priority = 50

    def __init__(self, operator_map: Optional[Dict[str, str]] = None,
                 operator_kwargs: Optional[Dict[str, Dict[str, Any]]] = None,
                 candidate_modules: Optional[Tuple[str, ...]] = None):
        cfg = _load_config(self.name)
        self.operator_map: Dict[str, str] = dict(cfg.get("operators", {}))
        self.operator_map.update(operator_map or {})
        self.operator_kwargs: Dict[str, Dict[str, Any]] = dict(cfg.get("kwargs", {}))
        self.operator_kwargs.update(operator_kwargs or {})
        if candidate_modules or cfg.get("modules"):
            self.candidate_modules = tuple(candidate_modules or cfg.get("modules"))

    @property
    def capabilities(self) -> FrozenSet[str]:  # type: ignore[override]
        return frozenset(self.operator_map)

    def find_module(self) -> Optional[str]:
        bpy = get_bpy()
        wanted = {normalize(c).replace("_", "") for c in self.candidate_modules}
        for key in bpy.context.preferences.addons.keys():
            base = key.split(".")[-1]
            if normalize(base).replace("_", "") in wanted:
                return key
        return None

    def available(self) -> ProviderStatus:
        try:
            bpy = get_bpy()
        except GarmentError:
            return ProviderStatus(self.name, self.display_name, False,
                                  f"Blender (bpy) is not available; cannot detect {self.display_name}.",
                                  details={"installed": False})
        module = self.find_module()
        if module is None:
            return ProviderStatus(self.name, self.display_name, False,
                                  f"{self.display_name} add-on is not installed or not enabled "
                                  f"(looked for modules {list(self.candidate_modules)}).",
                                  details={"installed": False})
        details = {"installed": True, "module": module, "known_features": list(self.known_features)}
        if not self.operator_map:
            return ProviderStatus(self.name, self.display_name, False,
                                  f"{self.display_name} add-on detected (module '{module}') but no verified operator "
                                  "mapping is configured. See PROVIDER_SETUP.md.", details=details)
        missing = [op for op in self.operator_map.values() if not operator_exists(bpy, op)]
        if missing:
            return ProviderStatus(self.name, self.display_name, False,
                                  f"{self.display_name}: mapped operator(s) {missing} not found in this Blender "
                                  "session.", details=details)
        return ProviderStatus(self.name, self.display_name, True, f"{self.display_name} detected via '{module}'",
                              capabilities=sorted(self.capabilities), details=details)

    # --- operator invocation ----------------------------------------------------
    def _kwargs(self, capability: str, record: Any) -> Dict[str, Any]:
        spec = getattr(record, "spec", None)
        values = {"type": getattr(spec, "type", ""), "fabric": getattr(getattr(spec, "fabric", None), "name", ""),
                  "fit": getattr(getattr(spec, "fit", None), "level", ""), "color": str(getattr(spec, "color", "")),
                  "name": getattr(record, "name", "")}
        out = {}
        for k, v in self.operator_kwargs.get(capability, {}).items():
            out[k] = v.format(**values) if isinstance(v, str) else v
        return out

    def _call(self, capability: str, record: Any, action: str) -> Result:
        if capability not in self.operator_map:
            return self._unsupported(action, capability)
        bpy = get_bpy()
        idname = self.operator_map[capability]
        ns, op = idname.split(".", 1)
        before = {o.name for o in bpy.data.objects}
        kwargs = self._kwargs(capability, record)
        r = Result(action=action)
        try:
            ret = getattr(getattr(bpy.ops, ns), op)(**kwargs)
        except (RuntimeError, TypeError) as err:
            return r.add_error("PROVIDER_ERROR", f"{self.display_name} operator {idname} failed: {err}")
        if "FINISHED" not in set(ret or ()):
            return r.add_error("PROVIDER_ERROR", f"{self.display_name} operator {idname} returned {ret}.")
        r.step(f"{self.display_name}: {idname}")
        r.warn(f"{self.display_name} integration uses a user-configured operator mapping; verify the result "
               "visually.")
        new = [o for o in bpy.data.objects if o.name not in before and o.type == "MESH"]
        if capability == "create_garment":
            if len(new) == 1:
                bscene.tag(new[0], record.id, "garment")
                record.object_name = new[0].name
                r.data["object"] = new[0].name
            else:
                r.warn(f"{self.display_name} created {len(new)} new mesh objects; garment object not tracked.")
        return r

    def create_garment(self, record: Any, avatar: Any, context: Optional[Dict[str, Any]] = None) -> Result:
        return self._call("create_garment", record, "create_garment")

    def fit_garment(self, record: Any, avatar: Any, context: Optional[Dict[str, Any]] = None) -> Result:
        return self._call("fit", record, "fit_garment")

    def sew(self, record: Any, seams: Optional[List[str]] = None) -> Result:
        return self._call("sewing", record, "sew")

    def simulate(self, record: Any, settings: Dict[str, Any], avatar: Any = None) -> Result:
        return self._call("simulate", record, "simulate")

    def bake(self, record: Any, settings: Optional[Dict[str, Any]] = None) -> Result:
        return self._call("bake", record, "bake")

    def generate_wrinkles(self, record: Any, settings: Optional[Dict[str, Any]] = None) -> Result:
        r = self._call("wrinkles", record, "generate_wrinkles")
        r.data.setdefault("applied", r.ok)
        return r
