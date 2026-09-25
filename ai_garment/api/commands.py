"""Flat, JSON-in / JSON-out commands for tool-calling (never raise).

Each function returns a dict with at least ``ok``, ``errors`` and ``warnings``.
``COMMANDS`` maps command names to functions (matches api/schema.py tools).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from ..core.errors import GarmentError
from ..core.nl_mapping import parse_instruction as _parse
from ..core.results import Result


def _system():
    from .garment import garment
    return garment


def _wrap(action: str, fn: Callable[[], Any]) -> Dict[str, Any]:
    try:
        out = fn()
    except GarmentError as err:
        nested = err.details.get("result") if isinstance(err.details, dict) else None
        if isinstance(nested, dict):
            return nested
        return Result.from_error(action, err).to_dict()
    except Exception as err:  # command boundary: convert anything unexpected into a structured error
        return Result.failure(action, "INTERNAL_ERROR", f"{type(err).__name__}: {err}").to_dict()
    if isinstance(out, Result):
        return out.to_dict()
    return out


def _garment(key: str):
    g = _system().get(key)
    if g is None:
        names = [r["name"] for r in _system().list_garments()]
        raise GarmentError("GARMENT_NOT_FOUND", f"No garment '{key}'.", suggestions=names)
    return g


def create_garment(spec: Dict[str, Any], dry_run: bool = False, avatar: Optional[str] = None,
                   provider: Optional[str] = None, transactional: bool = True) -> Dict[str, Any]:
    """Create a garment from a spec dict (type, fit, fabric, color, length, sleeves, components...)."""
    def run():
        out = _system().create(spec=spec, dry_run=dry_run, avatar=avatar, provider=provider,
                               transactional=transactional)
        if dry_run:
            return out
        d = out.result.to_dict()
        d["garment"] = out.id
        return d
    return _wrap("create_garment", run)


def fit_garment(garment: str, avatar: Optional[str] = None, dry_run: bool = False) -> Dict[str, Any]:
    """Fit a garment to the (detected or named) avatar and prepare body collision."""
    return _wrap("fit_garment", lambda: _garment(garment).fit_to_avatar(avatar=avatar, dry_run=dry_run))


def modify_garment(garment: str, dry_run: bool = False, **changes: Any) -> Dict[str, Any]:
    """High-level modify: length='+10%', region='chest', fit='tighter', component='sleeves', position='rolled_up'."""
    return _wrap("modify_garment", lambda: _garment(garment).modify(dry_run=dry_run, **changes))


def set_fabric(garment: str, fabric: Any, dry_run: bool = False) -> Dict[str, Any]:
    """Change fabric preset, e.g. 'heavy denim'."""
    return _wrap("set_fabric", lambda: _garment(garment).set_fabric(fabric, dry_run=dry_run))


def add_component(garment: str, type: str, target: Optional[str] = None, dry_run: bool = False,
                  **params: Any) -> Dict[str, Any]:
    """Add a component, e.g. type='elastic_cuff', target='sleeves', strength='medium'."""
    return _wrap("add_component", lambda: _garment(garment).add_component(type=type, target=target,
                                                                          dry_run=dry_run, **params))


def set_fit(garment: str, level: str, target: Optional[str] = None, dry_run: bool = False) -> Dict[str, Any]:
    """Set an absolute fit level (tight..oversized) for the garment or a component group."""
    return _wrap("set_fit", lambda: _garment(garment).set_fit(level, target=target, dry_run=dry_run))


def simulate_garment(garment: str, mode: str = "natural", quality: Optional[str] = None,
                     dry_run: bool = False) -> Dict[str, Any]:
    """Run the simulation pipeline (gravity, collision, self collision, settle, bake per mode)."""
    return _wrap("simulate_garment", lambda: _garment(garment).simulate(mode=mode, quality=quality, dry_run=dry_run))


def settle_garment(garment: str, max_frames: Optional[int] = None, apply: str = "none") -> Dict[str, Any]:
    """Let the garment fall onto the body until it stops moving (optionally store as shape key)."""
    return _wrap("settle_garment", lambda: _garment(garment).settle(max_frames=max_frames, apply=apply))


def bake_simulation(garment: str, frame_start: Optional[int] = None, frame_end: Optional[int] = None
                    ) -> Dict[str, Any]:
    """Bake the cloth cache."""
    return _wrap("bake_simulation", lambda: _garment(garment).bake(frame_start=frame_start, frame_end=frame_end))


def inspect_garment(garment: str) -> Dict[str, Any]:
    """Structured state of a garment (type, provider, fabric, fit, components, simulation flags, warnings)."""
    def run():
        info = _garment(garment).inspect()
        return {"ok": True, "errors": [], "warnings": info.get("warnings", []), "data": info}
    return _wrap("inspect_garment", run)


def reset_garment(garment: str, level: str = "simulation") -> Dict[str, Any]:
    """Free bake / settled shape ('simulation') or also regenerate geometry ('geometry', 'all')."""
    return _wrap("reset_garment", lambda: _garment(garment).reset(level=level))


def delete_garment(garment: str) -> Dict[str, Any]:
    """Delete ONLY the objects ai_garment created for this garment."""
    return _wrap("delete_garment", lambda: _garment(garment).delete())


def execute_plan(plan: List[Dict[str, Any]], garment: Optional[str] = None, dry_run: bool = False,
                 transactional: bool = True) -> Dict[str, Any]:
    """Validate and run a list of operations (dry_run=True to preview without touching the scene)."""
    return _wrap("execute_plan", lambda: _system().execute(plan, garment=_garment(garment) if garment else None,
                                                           dry_run=dry_run, transactional=transactional))


def apply_instruction(text: str, garment: Optional[str] = None, dry_run: bool = True) -> Dict[str, Any]:
    """Natural-language instruction -> operations -> dry run (default) or execution."""
    return _wrap("apply_instruction", lambda: _system().execute(text, garment=_garment(garment) if garment else None,
                                                                dry_run=dry_run))


def parse_instruction(text: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Map English to structured operations without executing anything."""
    def run():
        p = _parse(text, context)
        return dict(p.to_dict(), ok=bool(p.operations), errors=[], warnings=p.warnings)
    return _wrap("parse_instruction", run)


def detect_avatar(name: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Find the character (MakeHuman/MPFB, Rigify, Mixamo, generic) and report measurements."""
    return _wrap("detect_avatar", lambda: _system().detect_avatar(name=name, metadata=metadata).to_dict())


def detect_provider(required: Optional[List[str]] = None, preferred: Optional[str] = None) -> Dict[str, Any]:
    """Which garment provider would be used (with fallback warnings)."""
    def run():
        sel = _system().detect_provider(required, preferred)
        d = sel.to_dict()
        d.update(ok=sel.provider is not None, errors=[sel.error.to_dict()] if sel.error else [])
        return d
    return _wrap("detect_provider", run)


def list_garments() -> Dict[str, Any]:
    """Garments known to this session."""
    return _wrap("list_garments", lambda: {"ok": True, "errors": [], "warnings": [],
                                           "data": _system().list_garments()})


def list_capabilities() -> Dict[str, Any]:
    """Supported garment types, fabrics, fits, components, operations, quality levels and providers."""
    return _wrap("list_capabilities", lambda: {"ok": True, "errors": [], "warnings": [],
                                               "data": _system().capabilities()})


def describe_schema() -> Dict[str, Any]:
    """JSON schemas for garment specs and operations plus Claude tool definitions."""
    def run():
        from .schema import claude_tool_definitions, garment_spec_json_schema, operation_json_schema
        return {"ok": True, "errors": [], "warnings": [],
                "data": {"garment_spec": garment_spec_json_schema(), "operation": operation_json_schema(),
                         "tools": claude_tool_definitions()}}
    return _wrap("describe_schema", run)


COMMANDS: Dict[str, Callable[..., Dict[str, Any]]] = {f.__name__: f for f in (
    create_garment, fit_garment, modify_garment, set_fabric, add_component, set_fit, simulate_garment,
    settle_garment, bake_simulation, inspect_garment, reset_garment, delete_garment, execute_plan,
    apply_instruction, parse_instruction, detect_avatar, detect_provider, list_garments, list_capabilities,
    describe_schema)}


def run_command(name: str, **kwargs: Any) -> Dict[str, Any]:
    fn = COMMANDS.get(name)
    if fn is None:
        return Result.failure("run_command", "UNKNOWN_COMMAND", f"Unknown command '{name}'.",
                              sorted(COMMANDS)).to_dict()
    return _wrap(name, lambda: fn(**kwargs))
