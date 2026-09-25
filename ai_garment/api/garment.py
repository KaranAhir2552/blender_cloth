"""The Claude-facing object API.

    from ai_garment import garment

    shirt = garment.create(type="tshirt", fit="oversized", fabric="cotton", color="black")
    shirt.fit_to_avatar()
    shirt.add_component(type="elastic_cuff", target="sleeves", strength="medium")
    shirt.simulate(mode="natural")
    shirt.bake()
    shirt.inspect()

Every method returns a structured :class:`Result` (``.ok``, ``.to_dict()``),
except ``create`` (returns a :class:`Garment`, raises GarmentError with
structured details) and ``inspect`` (returns a dict).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..blender._bpy import blender_available
from ..core.avatar_model import AvatarModel
from ..core.errors import MSG_AVATAR_NOT_FOUND, GarmentError
from ..core.fabric_presets import list_fabrics
from ..core.component_system import list_component_types
from ..core.garment_operations import list_operations, modify_kwargs_to_operations
from ..core.garment_types import list_garment_types
from ..core.logging_utils import log_event
from ..core.quality import QUALITY_LEVELS
from ..core.record import GarmentRecord
from ..core.results import Result
from ..core.vocabulary import FIT_LEVELS
from ..providers.registry import ProviderRegistry, Selection, default_registry
from . import dispatcher
from .session import GarmentStore


class Garment:
    """Handle to one garment. Thin: every change goes through the validated dispatcher."""

    def __init__(self, system: "GarmentSystem", record: GarmentRecord, result: Optional[Result] = None):
        self._system = system
        self.record = record
        self.result = result or Result(action="create")

    # identity ---------------------------------------------------------------------
    @property
    def id(self) -> str:
        return self.record.id

    @property
    def name(self) -> str:
        return self.record.name

    @property
    def object_name(self) -> Optional[str]:
        return self.record.object_name

    @property
    def spec(self):
        return self.record.spec

    @property
    def provider(self) -> str:
        return self.record.provider

    def __repr__(self) -> str:
        return f"<Garment {self.name} ({self.spec.type}) id={self.id}>"

    # generic ------------------------------------------------------------------------
    def execute(self, plan: Any, dry_run: bool = False, transactional: bool = True,
                quality_cap: Optional[str] = None) -> Result:
        return self._system.execute(plan, garment=self, dry_run=dry_run, transactional=transactional,
                                    quality_cap=quality_cap)

    def plan(self, plan: Any) -> Result:
        return self.execute(plan, dry_run=True)

    def apply(self, instruction: str, dry_run: bool = False, quality_cap: Optional[str] = None) -> Result:
        """Natural-language edit, e.g. 'Make the sleeves slightly shorter'."""
        return self.execute(instruction, dry_run=dry_run, quality_cap=quality_cap)

    def _op(self, op_name: str, dry_run: bool = False, /, **params: Any) -> Result:
        op = {"operation": op_name}
        op.update({k: v for k, v in params.items() if v is not None})
        return self.execute([op], dry_run=dry_run)

    # edits ---------------------------------------------------------------------------
    def modify(self, dry_run: bool = False, **changes: Any) -> Result:
        """modify(length="+10%"), modify(region="chest", fit="tighter"),
        modify(component="sleeves", length="-5%"), modify(component="sleeves", position="rolled_up"),
        modify(component="legs", fit="baggy"), modify(fabric="silk"), modify(color="navy")."""
        try:
            ops = modify_kwargs_to_operations(**changes)
        except GarmentError as err:
            return Result.from_error("modify", err)
        return self.execute(ops, dry_run=dry_run)

    def set_fabric(self, fabric: Any, dry_run: bool = False, **overrides: Any) -> Result:
        return self._op("set_fabric", dry_run, fabric=fabric, overrides=overrides or None)

    def set_fit(self, level: str, target: Optional[str] = None, dry_run: bool = False) -> Result:
        return self._op("set_fit", dry_run, level=level, target=target)

    def set_color(self, color: Any, dry_run: bool = False) -> Result:
        return self._op("set_color", dry_run, color=color)

    def add_component(self, type: str, target: Optional[str] = None, name: Optional[str] = None,
                      dry_run: bool = False, **params: Any) -> Result:
        return self._op("add_component", dry_run, type=type, target=target, name=name, **params)

    def remove_component(self, target: str, dry_run: bool = False) -> Result:
        return self._op("remove_component", dry_run, target=target)

    def add_elastic(self, target: str, strength: Any = "medium", width: Optional[float] = None,
                    tension: Optional[float] = None, dry_run: bool = False) -> Result:
        return self._op("set_elastic", dry_run, target=target, strength=strength, width=width, tension=tension)

    def roll(self, target: Optional[str] = None, turns: Optional[int] = None, dry_run: bool = False) -> Result:
        return self._op("roll", dry_run, target=target, turns=turns)

    def tuck(self, dry_run: bool = False) -> Result:
        return self._op("tuck", dry_run)

    def untuck(self, dry_run: bool = False) -> Result:
        return self._op("untuck", dry_run)

    def enable_self_collision(self, preset: str = "preview", dry_run: bool = False) -> Result:
        return self._op("enable_self_collision", dry_run, preset=preset)

    # scene operations --------------------------------------------------------------------
    def fit_to_avatar(self, avatar: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None,
                      collision_mode: Optional[str] = None, margin: Optional[float] = None,
                      dry_run: bool = False) -> Result:
        return self._op("fit", dry_run, avatar=avatar, metadata=metadata, collision_mode=collision_mode,
                        margin=margin)

    fit = fit_to_avatar

    def simulate(self, mode: str = "natural", quality: Optional[str] = None, dry_run: bool = False,
                 **settings: Any) -> Result:
        return self._op("simulate", dry_run, mode=mode, quality=quality, **settings)

    def settle(self, max_frames: Optional[int] = None, threshold: Optional[float] = None, apply: str = "none",
               quality: Optional[str] = None, dry_run: bool = False) -> Result:
        return self._op("settle", dry_run, max_frames=max_frames, threshold=threshold, apply=apply, quality=quality)

    def bake(self, frame_start: Optional[int] = None, frame_end: Optional[int] = None,
             dry_run: bool = False) -> Result:
        return self._op("bake", dry_run, frame_start=frame_start, frame_end=frame_end)

    def generate_wrinkles(self, intensity: Any = None, dry_run: bool = False) -> Result:
        return self._op("generate_wrinkles", dry_run, intensity=intensity)

    def reset(self, level: str = "simulation", dry_run: bool = False) -> Result:
        return self._op("reset", dry_run, level=level)

    def inspect(self) -> Dict[str, Any]:
        p = self._system.registry.get(self.provider)
        if p is None or not self._system.registry.status_of(p).available:
            return {"id": self.id, "garment": self.spec.display_name.title(), "type": self.spec.type,
                    "provider": self.provider, "fabric": self.spec.fabric.display, "fit": self.spec.fit.level,
                    "color": self.spec.color, "components": [c.name for c in self.spec.components],
                    "simulation": {"cloth": False, "collision": False, "self_collision": False, "baked": False},
                    "warnings": [f"Provider '{self.provider}' unavailable; showing the stored spec only."]}
        return p.inspect(self.record)

    def duplicate(self, name: Optional[str] = None) -> "Garment":
        new = GarmentRecord.new(self.spec, self.provider, name=name or f"{self.name} copy")
        p = self._system.registry.get(self.provider)
        r = p.duplicate_garment(self.record, new)
        if not r.ok:
            raise GarmentError(r.errors[0].code, r.errors[0].message, details={"result": r.to_dict()})
        self._system.store.add(new)
        return Garment(self._system, new, r)

    def rollback(self) -> Result:
        """Undo the most recent executed change on this garment (scene + spec)."""
        tx = self._system._last_tx.pop(self.id, None)
        if tx is None:
            return Result.failure("rollback", "NOTHING_TO_ROLL_BACK", "No recorded change to roll back.")
        rep = tx.rollback()
        r = Result(action="rollback", ok=rep.ok, data=rep.to_dict())
        for e in rep.errors:
            r.add_error("ROLLBACK_FAILED", e)
        return r

    def delete(self) -> Result:
        p = self._system.registry.get(self.provider)
        r = p.delete_garment(self.record) if p else Result.failure("delete", "NO_PROVIDER_AVAILABLE",
                                                                   "Provider missing.")
        if r.ok:
            self._system.store.remove(self.id)
            self._system._last_tx.pop(self.id, None)
        return r

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "object": self.object_name, "spec": self.spec.to_dict(),
                "provider": self.provider, "state": {k: v for k, v in self.record.state.items()
                                                     if k != "physics_groups"}}


class AvatarHandle:
    """Result of detect_avatar(): never raises; check ``.ok``."""

    def __init__(self, system: "GarmentSystem", model: Optional[AvatarModel], result: Result):
        self._system = system
        self.model = model
        self.result = result

    @property
    def ok(self) -> bool:
        return self.model is not None

    @property
    def name(self) -> Optional[str]:
        return self.model.object_name or self.model.name if self.model else None

    def _need(self) -> AvatarModel:
        if self.model is None:
            raise GarmentError("AVATAR_NOT_FOUND", MSG_AVATAR_NOT_FOUND)
        return self.model

    def get_measurements(self) -> Dict[str, float]:
        return self._need().get_measurements()

    def get_body_regions(self) -> Dict[str, Any]:
        return self._need().get_body_regions()

    def get_collision_surfaces(self, garment_type: Optional[str] = None) -> Dict[str, Any]:
        return self._need().get_collision_surfaces(garment_type)

    def _native(self):
        p = self._system.registry.provider_for("collision")
        if p is None:
            raise GarmentError("NO_PROVIDER_AVAILABLE", "No provider supports collision setup.")
        return p

    def prepare_collision(self, garment_type: Optional[str] = None, mode: str = "proxy",
                          margin: Optional[float] = None) -> Result:
        try:
            return self._native().prepare_collision(self._need(), {"garment_type": garment_type, "mode": mode,
                                                                   "margin": margin})
        except GarmentError as err:
            return Result.from_error("prepare_collision", err)

    def remove_collision(self) -> Result:
        try:
            return self._native().remove_collision(self._need())
        except GarmentError as err:
            return Result.from_error("remove_collision", err)

    def to_dict(self) -> Dict[str, Any]:
        d = self.result.to_dict()
        d["avatar"] = self.model.to_dict() if self.model else None
        return d


class GarmentSystem:
    """Entry point: ``from ai_garment import garment`` gives the default instance."""

    def __init__(self, registry: Optional[ProviderRegistry] = None):
        self.registry = registry if registry is not None else default_registry()
        self.store = GarmentStore()
        self._last_tx: Dict[str, Any] = {}

    # creation / execution ---------------------------------------------------------------
    def create(self, type: Optional[str] = None, spec: Optional[Dict[str, Any]] = None, dry_run: bool = False,
               transactional: bool = True, avatar: Optional[str] = None, provider: Optional[str] = None,
               name: Optional[str] = None, quality_cap: Optional[str] = None, **fields: Any) -> Any:
        data = dict(spec or {})
        if type is not None:
            data["type"] = type
        data.update(fields)
        op: Dict[str, Any] = {"operation": "create", "spec": data}
        for k, v in (("avatar", avatar), ("provider", provider), ("name", name)):
            if v is not None:
                op[k] = v
        r = self.execute([op], dry_run=dry_run, transactional=transactional, quality_cap=quality_cap)
        if dry_run:
            return r
        if not r.ok:
            details = {"errors": [e.to_dict() for e in r.errors], "result": r.to_dict()}
            if not r.data.get("valid", True):
                raise GarmentError("VALIDATION_FAILED", "Garment spec is invalid: " + r.errors[0].message,
                                   r.errors[0].suggestions, details)
            raise GarmentError(r.errors[0].code, r.errors[0].message, r.errors[0].suggestions, details)
        return Garment(self, self.store.get(r.data["created"]), r)

    def execute(self, plan: Any, garment: Optional[Garment] = None, dry_run: bool = False,
                transactional: bool = True, quality_cap: Optional[str] = None) -> Result:
        try:
            return dispatcher.execute_plan(self, plan, garment, dry_run, transactional, quality_cap)
        except GarmentError as err:
            return Result.from_error("execute_plan", err)

    def plan(self, plan: Any, garment: Optional[Garment] = None) -> Result:
        """Dry run: validate and describe without touching the scene."""
        return self.execute(plan, garment=garment, dry_run=True)

    def run(self, instruction: Any, garment: Optional[Garment] = None, quality_cap: Optional[str] = None,
            transactional: bool = True) -> Result:
        return self.execute(instruction, garment=garment, dry_run=False, transactional=transactional,
                            quality_cap=quality_cap)

    # discovery ----------------------------------------------------------------------------------
    def detect_provider(self, required: Optional[List[str]] = None, preferred: Optional[str] = None) -> Selection:
        return self.registry.select(set(required or ["create_garment"]), preferred)

    def providers(self) -> List[Dict[str, Any]]:
        return [s.to_dict() for s in self.registry.statuses()]

    def detect_avatar(self, name: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> AvatarHandle:
        r = Result(action="detect_avatar")
        try:
            model = self._find_avatar(name, metadata, required=True)
        except GarmentError as err:
            return AvatarHandle(self, None, Result.from_error("detect_avatar", err))
        log_event("Avatar detected", f"{model.source} ({model.name})", r)
        for w in model.warnings:
            r.warn(w)
        r.data.update({"name": model.object_name or model.name, "source": model.source, "pose": model.pose,
                       "measurements": model.get_measurements(), "evidence": model.evidence})
        return AvatarHandle(self, model, r)

    def _find_avatar(self, name: Optional[str], metadata: Optional[Dict[str, Any]], required: bool,
                     hint: Optional[str] = None) -> Optional[AvatarModel]:
        if not blender_available():
            if metadata:
                return AvatarModel.from_metadata(metadata)
            if required:
                raise GarmentError("AVATAR_NOT_FOUND", MSG_AVATAR_NOT_FOUND + " (Blender is not available.)")
            return None
        from ..blender.avatar_scan import detect_avatar
        try:
            model = detect_avatar(name=name, metadata=metadata)
        except GarmentError:
            if required:
                raise
            return None
        if hint and hint.lower() == "makehuman" and model.source != "makehuman":
            model.warnings.append(f"Requested a MakeHuman character, but '{model.name}' looks like "
                                  f"'{model.source}'. Using it anyway.")
        return model

    # garments ------------------------------------------------------------------------------------
    def list_garments(self) -> List[Dict[str, Any]]:
        return [r.summary() for r in self.store.all()]

    def get(self, key: str) -> Optional[Garment]:
        rec = self.store.get(key)
        return Garment(self, rec) if rec else None

    def load_from_scene(self) -> List[Garment]:
        from ..blender._bpy import get_bpy
        return [Garment(self, r) for r in self.store.load_from_objects(get_bpy().data.objects)]

    def capabilities(self) -> Dict[str, Any]:
        return {"garment_types": list_garment_types(), "fabrics": list_fabrics(), "fits": list(FIT_LEVELS),
                "components": list_component_types(), "operations": list_operations(),
                "quality_levels": list(QUALITY_LEVELS), "providers": self.providers()}

    def schema(self) -> Dict[str, Any]:
        from .schema import garment_spec_json_schema
        return garment_spec_json_schema()

    def tools(self) -> List[Dict[str, Any]]:
        from .schema import claude_tool_definitions
        return claude_tool_definitions()


garment = GarmentSystem()
garment_system = garment
