"""Plan execution: validate EVERYTHING first, then dry-run or execute transactionally.

    plan (text | op dicts) -> normalise -> validate + apply to spec COPIES
        -> invalid: structured errors, provider never called, scene untouched
        -> dry_run: descriptions + final spec + simulation plan, scene untouched
        -> execute: Transaction; spec edits accumulate "effects" and are flushed
           as ONE provider.update_garment before each scene operation; any
           failure rolls back the journal (when transactional=True).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from ..core.errors import MSG_WRINKLES_UNAVAILABLE, GarmentError, Issue
from ..core.garment_operations import OpApplication, Operation, apply_operation, get_operation_def, normalize_operation
from ..core.garment_spec import GarmentSpec
from ..core.logging_utils import log_event
from ..core.nl_mapping import ParseResult, parse_instruction
from ..core.planning import plan_simulation, resolve_simulation_settings
from ..core.quality import cap_quality
from ..core.record import GarmentRecord
from ..core.results import Result
from ..core.transaction import Transaction
from ..providers.base import Capability

SCENE_CAPABILITY = {"fit": Capability.FIT, "prepare_collision": Capability.COLLISION, "simulate": Capability.SIMULATE,
                    "settle": Capability.SETTLE, "bake": Capability.BAKE, "reset": Capability.SIMULATE,
                    "inspect": Capability.INSPECT, "generate_wrinkles": Capability.WRINKLES}


class _StepFailed(Exception):
    def __init__(self, result: Result):
        super().__init__(result.errors[0].message if result.errors else "step failed")
        self.result = result


def _to_ops(plan: Any, garment: Any, res: Result) -> List[Any]:
    if isinstance(plan, str):
        ctx = {"type": garment.spec.type} if garment is not None else None
        parsed = parse_instruction(plan, context=ctx)
        return _from_parse(parsed, res)
    if isinstance(plan, ParseResult):
        return _from_parse(plan, res)
    if isinstance(plan, (dict, Operation)):
        return [plan]
    if isinstance(plan, (list, tuple)):
        return list(plan)
    raise GarmentError("INVALID_PLAN", "A plan must be text, an operation or a list of operations.")


def _from_parse(parsed: ParseResult, res: Result) -> List[Any]:
    res.data["parsed"] = parsed.to_dict()
    for w in parsed.warnings:
        res.warn(w)
    if not parsed.operations:
        res.add_error("UNRECOGNIZED_INSTRUCTION", "Could not map the instruction to any garment operation.",
                      ["rephrase, e.g. 'Make the sleeves slightly shorter'", "send structured operations"])
    return list(parsed.operations)


def validate_plan(plan: Any, garment: Any = None) -> Tuple[List[Tuple[Operation, OpApplication]], Result]:
    """Normalise + validate every step against evolving spec copies (pure)."""
    res = Result(action="execute_plan")
    raw_ops = _to_ops(plan, garment, res)
    spec: Optional[GarmentSpec] = garment.spec.copy() if garment is not None else None
    steps: List[Tuple[Operation, OpApplication]] = []
    for i, raw in enumerate(raw_ops):
        try:
            op = normalize_operation(raw)
        except GarmentError as err:
            res.errors.append(Issue(err.code, err.message, "error", f"plan[{i}]", err.suggestions))
            continue
        defn = get_operation_def(op.name)
        if op.name != "create" and spec is None and defn.requires_garment:
            res.errors.append(Issue("NO_GARMENT", f"Operation '{op.name}' needs a garment: add a 'create' step first "
                                                  "or call it on an existing garment.", "error", f"plan[{i}]"))
            continue
        try:
            app = apply_operation(spec, op)
        except GarmentError as err:
            issues = err.details.get("issues") if isinstance(err.details, dict) else None
            if issues:
                for d in issues:
                    res.errors.append(Issue(d["code"], d["message"], "error", d.get("path") or f"plan[{i}]",
                                            d.get("suggestions", [])))
            else:
                res.errors.append(Issue(err.code, err.message, "error", err.path or f"plan[{i}]", err.suggestions))
            continue
        spec = app.spec
        steps.append((op, app))
        res.operations.extend(app.description)
    if res.errors:
        res.ok = False
    res.data["valid"] = res.ok
    res.data["plan"] = [op.to_dict() for op, _ in steps]
    if spec is not None:
        res.data["final_spec"] = spec.to_dict()
    return steps, res


def execute_plan(system: Any, plan: Any, garment: Any = None, dry_run: bool = False, transactional: bool = True,
                 quality_cap: Optional[str] = None) -> Result:
    steps, res = validate_plan(plan, garment)
    res.dry_run = dry_run
    if not res.ok:
        return res
    if dry_run:
        _describe_execution(system, steps, res, quality_cap)
        return res

    tx = Transaction("plan")
    for p in system.registry.providers():
        p.bind_transaction(tx)
    record: Optional[GarmentRecord] = garment.record if garment is not None else None
    pending: Set[str] = set()
    try:
        for op, app in steps:
            defn = get_operation_def(op.name)
            if op.name == "create":
                if record is not None:
                    _flush(system, record, pending, res)
                record = _create(system, app.spec, op.params, tx, res, quality_cap)
                continue
            if defn.transform is not None:
                old = record.spec
                record.spec = app.spec
                tx.record(f"restore spec of {record.id}", lambda r=record, s=old: setattr(r, "spec", s))
                pending |= set(app.effects)
                continue
            _flush(system, record, pending, res)
            _scene_op(system, record, op, res, quality_cap)
        _flush(system, record, pending, res)
    except Exception as err:  # every failure becomes a structured error; scene is rolled back if requested
        if isinstance(err, _StepFailed):
            res.errors.extend(err.result.errors)
            res.merge(Result(warnings=err.result.warnings, logs=err.result.logs))
        elif isinstance(err, GarmentError):
            res.errors.append(err.to_issue())
        else:
            res.errors.append(Issue("PROVIDER_ERROR", f"{type(err).__name__}: {err}"))
        res.ok = False
        if transactional:
            rep = tx.rollback()
            res.data["rolled_back"] = True
            res.data["rollback"] = rep.to_dict()
            for e in rep.errors:
                res.warn(f"Rollback problem: {e}")
            log_event("Rollback", "scene restored" if rep.ok else "completed with problems", res)
        else:
            res.data["rolled_back"] = False
            tx.commit()
        return res
    finally:
        for p in system.registry.providers():
            p.bind_transaction(None)
    kept = tx.commit(keep=True)
    if record is not None:
        system._last_tx[record.id] = kept
        res.data["garment"] = record.summary()
        record.history.extend(res.operations)
    res.data["rolled_back"] = False
    return res


def _describe_execution(system: Any, steps, res: Result, quality_cap: Optional[str]) -> None:
    creates = any(op.name == "create" for op, _ in steps)
    sel = system.registry.select({Capability.CREATE_GARMENT} if creates else {Capability.INSPECT}, log=False)
    res.data["provider"] = sel.provider.name if sel.provider else None
    res.data["executable"] = sel.provider is not None
    for w in sel.warnings:
        res.warn(w)
    if sel.provider is None and sel.error is not None:
        res.warn("Not executable here: " + sel.error.message)
    for op, app in steps:
        if op.name == "simulate":
            q = cap_quality(op.params.get("quality") or app.spec.simulation.quality, quality_cap)
            sp = plan_simulation(app.spec, op.params.get("mode"), q, sel.provider.name if sel.provider else None,
                                 **{k: op.params.get(k) for k in ("settle", "bake", "self_collision", "frames")})
            res.data["simulation_plan"] = sp.to_dict()
        if op.name == "generate_wrinkles" and system.registry.provider_for(Capability.WRINKLES) is None:
            res.warn(MSG_WRINKLES_UNAVAILABLE)


def _provider(system: Any, record: GarmentRecord, capability: Optional[str] = None):
    own = system.registry.get(record.provider)
    if capability is None or (own is not None and own.supports(capability) and
                              system.registry.status_of(own).available):
        if own is None:
            raise GarmentError("NO_PROVIDER_AVAILABLE", f"Provider '{record.provider}' is not registered.")
        return own
    p = system.registry.provider_for(capability)
    if p is None:
        raise GarmentError("NO_PROVIDER_AVAILABLE", f"No available provider supports '{capability}'.")
    return p


def _check(r: Result) -> Result:
    if not r.ok:
        raise _StepFailed(r)
    return r


def _flush(system: Any, record: Optional[GarmentRecord], pending: Set[str], res: Result) -> None:
    if record is None or not pending:
        pending.clear()
        return
    p = _provider(system, record, Capability.COMPONENTS)
    if p.name != record.provider and "geometry" in pending:
        raise GarmentError("CAPABILITY_NOT_SUPPORTED",
                           f"Provider '{record.provider}' cannot regenerate this garment's geometry and the native "
                           "fallback would replace it with proxy geometry.",
                           ["recreate the garment with provider='blender_native'",
                            "limit edits to fabric / color / physics for add-on garments"])
    r = _check(p.update_garment(record, frozenset(pending)))
    res.merge(r)
    pending.clear()


def _create(system: Any, spec: GarmentSpec, params: Dict[str, Any], tx: Transaction, res: Result,
            quality_cap: Optional[str]) -> GarmentRecord:
    sel = system.registry.select({Capability.CREATE_GARMENT}, preferred=params.get("provider"))
    for w in sel.warnings:
        res.warn(w)
    if sel.provider is None:
        raise GarmentError(sel.error.code, sel.error.message, sel.error.suggestions)
    record = GarmentRecord.new(spec, sel.provider.name, name=params.get("name"))
    avatar = system._find_avatar(params.get("avatar"), params.get("metadata"), required=False)
    ctx = {"quality": cap_quality(spec.simulation.quality, quality_cap)}
    r = _check(sel.provider.create_garment(record, avatar, ctx))
    system.store.add(record)
    tx.record(f"register garment {record.id}", lambda: system.store.remove(record.id))
    res.merge(r)
    res.data["created"] = record.id
    return record


def _scene_op(system: Any, record: GarmentRecord, op: Operation, res: Result, quality_cap: Optional[str]) -> None:
    name, prm = op.name, op.params
    cap = SCENE_CAPABILITY.get(name)
    if name == "generate_wrinkles":
        p = system.registry.provider_for(Capability.WRINKLES)
        if p is None:
            r = Result(action="generate_wrinkles", data={"applied": False})
            r.warn(MSG_WRINKLES_UNAVAILABLE)
        else:
            r = p.generate_wrinkles(record, prm)
            if not r.ok and prm.get("optional"):
                r = Result(action="generate_wrinkles", data={"applied": False}, warnings=[e.message for e in r.errors])
        res.merge(_check(r))
        res.data.update(r.data)
        return
    p = _provider(system, record, cap)
    if name == "fit":
        avatar = system._find_avatar(prm.get("avatar"), prm.get("metadata"), required=True, hint=prm.get("avatar_hint"))
        r = p.fit_garment(record, avatar, {"collision_mode": prm.get("collision_mode"), "margin": prm.get("margin")})
    elif name == "prepare_collision":
        avatar = system._find_avatar(record.avatar_name, None, required=True)
        r = p.prepare_collision(avatar, {"garment_type": record.spec.type, "mode": prm.get("mode"),
                                         "margin": prm.get("margin")})
    elif name in ("simulate", "settle"):
        q = cap_quality(prm.get("quality") or record.spec.simulation.quality, quality_cap)
        if name == "simulate":
            settings = resolve_simulation_settings(record.spec, prm.get("mode"), q, frames=prm.get("frames"),
                                                   settle=prm.get("settle"), bake=prm.get("bake"),
                                                   self_collision=prm.get("self_collision"))
        else:
            settings = resolve_simulation_settings(record.spec, "preview", q)
            if prm.get("max_frames"):
                settings["settle_frames"] = int(prm["max_frames"])
            if prm.get("threshold") is not None:
                settings["settle_threshold"] = float(prm["threshold"])
            settings["apply"] = prm.get("apply") or "none"
        avatar = system._find_avatar(record.avatar_name, None, required=False) if record.avatar_name else None
        r = p.simulate(record, settings, avatar) if name == "simulate" else p.settle(record, settings, avatar)
    elif name == "bake":
        r = p.bake(record, prm)
    elif name == "reset":
        r = p.reset(record, prm.get("level") or "simulation")
    elif name == "inspect":
        r = Result(action="inspect", data={"inspection": p.inspect(record)})
    else:
        raise GarmentError("UNKNOWN_OPERATION", f"No executor for '{name}'.")
    res.merge(_check(r))
    res.data.update(r.data)
