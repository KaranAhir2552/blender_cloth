"""Blender-native provider: built-in Cloth, Collision, sewing springs,
shrink/stiffness/pin vertex groups, PointCache baking.

Always registered; always the fallback. Garment geometry comes from the pure
proxy builder (core.geometry.builder) because native Blender has no garment
pattern tool.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from ..blender import modifiers as bmods
from ..blender import physics as bphys
from ..blender import scene as bscene
from ..blender import simulation as bsim
from ..blender._bpy import get_bpy, is_mock
from ..blender.avatar_scan import detect_avatar
from ..blender.materials import ensure_material
from ..blender.objects import create_mesh_object, duplicate_object, replace_geometry
from ..blender.spatial import body_nearest, push_out_points, signed_distances
from ..core.avatar_model import AvatarModel
from ..core.diagnostics import analyze_penetration, analyze_stability
from ..core.errors import MSG_AVATAR_NOT_FOUND, GarmentError
from ..core.fabric_presets import resolve_fabric
from ..core.geometry.builder import CLEARANCE, build_garment_mesh
from ..core.geometry.tube import GarmentMeshData
from ..core.logging_utils import log_event
from ..core.physics_mapping import map_fabric_to_native
from ..core.quality import get_quality, self_collision_preset
from ..core.results import Result
from .base import Capability, GarmentProvider, ProviderStatus

PROXY_ROLE = "collision_proxy"
REGION_GROUP = "AIG_collision_region"
PROXY_MAX_VERTS = 30000


def default_avatar() -> AvatarModel:
    return AvatarModel.from_metadata({"height": 1.75}, name="default_proportions")


class BlenderNativeProvider(GarmentProvider):
    name = "blender_native"
    display_name = "Blender Native Cloth"
    priority = 0
    capabilities = Capability.CORE

    def available(self) -> ProviderStatus:
        try:
            bpy = get_bpy()
        except GarmentError as err:
            return ProviderStatus(self.name, self.display_name, False, err.message)
        ver = ".".join(str(v) for v in bpy.app.version)
        return ProviderStatus(self.name, self.display_name, True, f"Blender {ver} native cloth", ver,
                              sorted(self.capabilities), {"mock": is_mock()})

    # ------------------------------------------------------------------ helpers
    def _obj(self, record: Any) -> Any:
        obj = get_bpy().data.objects.get(record.object_name or "")
        if obj is None:
            raise GarmentError("OBJECT_MISSING", f"Garment object '{record.object_name}' no longer exists in the "
                                                 "scene.", suggestions=["reset the garment", "create it again"])
        return obj

    @staticmethod
    def _cloth(obj: Any) -> Optional[Any]:
        mod = obj.modifiers.get(bmods.CLOTH)
        return mod if mod is not None and mod.type == "CLOTH" else None

    @staticmethod
    def _avatar_obj(avatar: Optional[AvatarModel]) -> Optional[Any]:
        if avatar is None or not avatar.object_name:
            return None
        return get_bpy().data.objects.get(avatar.object_name)

    def _resolve_avatar(self, record: Any, avatar: Optional[AvatarModel]) -> AvatarModel:
        if avatar is not None:
            return avatar
        if record.avatar_name:
            try:
                return detect_avatar(name=record.avatar_name)
            except GarmentError as err:
                record.history.append(f"avatar '{record.avatar_name}' unavailable ({err.code}); "
                                      "using default proportions")
        return default_avatar()

    def _build(self, record: Any, avatar: AvatarModel, quality: str, r: Result) -> GarmentMeshData:
        fabric = resolve_fabric(record.spec.fabric)
        data = build_garment_mesh(record.spec, avatar, quality, fabric.thickness_mm)
        unit = avatar.unit_scale or 1.0
        data = data.scaled(1.0 / unit)
        for w in data.warnings:
            r.warn(w)
        body = self._avatar_obj(avatar)
        if body is not None:
            nearest = body_nearest(body)
            moved = push_out_points(nearest, data.vertices, (CLEARANCE * 0.5) / unit)
            if moved:
                r.log(f"pushed {moved} garment vertices out of the body before simulation")
        record.unit_scale = unit
        record.state["physics_groups"] = data.physics
        return data

    def _apply_physics(self, record: Any, obj: Any, quality: Optional[str] = None,
                       self_collision: Optional[bool] = None) -> Any:
        spec = record.spec
        q = get_quality(quality or spec.simulation.quality).name
        use_self = spec.simulation.self_collision if self_collision is None else self_collision
        fabric = resolve_fabric(spec.fabric)
        mapping = map_fabric_to_native(fabric, q, record.unit_scale, use_self)
        cloth, _ = bmods.get_or_add(obj, bmods.CLOTH, "CLOTH", self.tx)
        bphys.apply_cloth(cloth, mapping, record.state.get("physics_groups") or {}, spec.simulation.gravity)
        if mapping["cloth_collision"]["use_self_collision"]:
            preset_name = spec.metadata.get("self_collision_preset") or ("production" if q in ("medium", "production")
                                                                          else q)
            bphys.apply_self_collision(cloth, self_collision_preset(preset_name), record.unit_scale)
        else:
            bphys.apply_self_collision(cloth, None)
        rnd = mapping["render"]
        bmods.ensure_post_cloth(obj, rnd["solidify_thickness"], rnd["subdivision_viewport"],
                                rnd["subdivision_render"], self.tx)
        return cloth

    def _persist(self, record: Any, obj: Any) -> None:
        obj[bscene.TAG_SPEC] = json.dumps(record.spec.to_dict())
        obj[bscene.TAG_RECORD] = json.dumps(record.to_dict())

    def _invalidate(self, record: Any, obj: Any, cloth: Any, r: Result) -> None:
        was = record.state.get("simulated") or record.state.get("baked") or cloth.point_cache.is_baked
        if cloth.point_cache.is_baked:
            bsim.free_bake(obj, cloth)
        bsim.remove_settled_shape(obj)
        record.state.update({"simulated": False, "settled": False, "baked": False})
        if was:
            r.warn("Simulation cache invalidated by the change; run simulate() again.")

    # ------------------------------------------------------------------ garment lifecycle
    def create_garment(self, record: Any, avatar: Any, context: Optional[Dict[str, Any]] = None) -> Result:
        ctx = context or {}
        r = Result(action="create_garment")
        if avatar is None:
            r.warn("No avatar supplied: garment built for default proportions (1.75 m). "
                   "Call fit_to_avatar() once a character is available.")
        av = avatar or default_avatar()
        quality = ctx.get("quality") or record.spec.simulation.quality
        data = self._build(record, av, quality, r)
        coll = bscene.ensure_collection(self.tx)
        obj = create_mesh_object(f"AIG_{record.name}", data, coll, record.id, "garment", self.tx)
        record.object_name = obj.name
        record.avatar_name = av.object_name
        ensure_material(obj, record.id, record.spec.color, resolve_fabric(record.spec.fabric), self.tx)
        cloth = self._apply_physics(record, obj, quality)
        sim = record.spec.simulation
        bsim.configure_cache(cloth, sim.frame_start, sim.frame_end or sim.frame_start + get_quality(quality).bake_frames)
        self._persist(record, obj)
        log_event("Garment", record.spec.display_name, r)
        log_event("Fabric", record.spec.fabric.display, r)
        log_event("Fit", record.spec.fit.level, r)
        r.step(f"Create {record.spec.display_name}")
        r.data.update({"object": obj.name, "vertices": len(data.vertices), "sewing_edges": len(data.edges),
                       "seams": data.seams, "components": data.components})
        return r

    def update_garment(self, record: Any, effects: Any, avatar: Any = None,
                       context: Optional[Dict[str, Any]] = None) -> Result:
        r = Result(action="update_garment")
        obj = self._obj(record)
        effects = set(effects)
        cloth = self._cloth(obj)
        if effects & {"geometry", "fit"}:
            av = self._resolve_avatar(record, avatar)
            data = self._build(record, av, record.spec.simulation.quality, r)
            replace_geometry(obj, data, self.tx)
            r.step("Regenerate garment geometry")
        if effects & {"geometry", "fit", "physics", "simulation"} or cloth is None:
            cloth = self._apply_physics(record, obj)
            r.step("Apply fabric / physics settings")
        if "material" in effects:
            ensure_material(obj, record.id, record.spec.color, resolve_fabric(record.spec.fabric), self.tx)
            r.step("Update material")
        if effects & {"geometry", "fit", "physics", "simulation"}:
            self._invalidate(record, obj, cloth, r)
        self._persist(record, obj)
        return r

    def fit_garment(self, record: Any, avatar: Any, context: Optional[Dict[str, Any]] = None) -> Result:
        ctx = context or {}
        if avatar is None:
            return Result.failure("fit_garment", "AVATAR_NOT_FOUND", MSG_AVATAR_NOT_FOUND)
        r = Result(action="fit_garment")
        record.avatar_name = avatar.object_name
        log_event("Avatar detected", f"{avatar.source_display} ({avatar.name})", r)
        r.merge(self.update_garment(record, {"fit"}, avatar))
        col = self.prepare_collision(avatar, {"garment_type": record.spec.type, "mode": ctx.get("collision_mode"),
                                              "margin": ctx.get("margin")})
        r.merge(col, "collision")
        record.state.update({"fitted": True, "collision": col.ok})
        r.step("Fit to avatar")
        self._persist(record, self._obj(record))
        return r

    # ------------------------------------------------------------------ collision
    def prepare_collision(self, avatar: Any, settings: Optional[Dict[str, Any]] = None) -> Result:
        s = dict(settings or {})
        r = Result(action="prepare_collision")
        body = self._avatar_obj(avatar)
        if body is None:
            return r.add_error("AVATAR_NOT_FOUND", MSG_AVATAR_NOT_FOUND)
        unit = avatar.unit_scale or 1.0
        mode = s.get("mode") or "proxy"
        surfaces = avatar.get_collision_surfaces(s.get("garment_type"))
        margin_m = s.get("margin") if s.get("margin") is not None else get_quality("preview").collider_thickness
        margin = margin_m / unit
        collider = {"thickness_outer": margin, "cloth_friction": 5.0}
        if mode == "direct":
            existing = [m for m in body.modifiers if m.type == "COLLISION" and m.name != bmods.COLLISION]
            if existing:
                r.warn(f"Avatar '{body.name}' already has an existing collision modifier '{existing[0].name}'; "
                       "using it unchanged.")
            else:
                bmods.get_or_add(body, bmods.COLLISION, "COLLISION", self.tx)
                bphys.apply_collider(body, collider, margin)
            r.data.update({"mode": "direct", "object": body.name})
        else:
            proxy = self._ensure_proxy(body, avatar, surfaces, unit, r)
            bphys.apply_collider(proxy, collider, margin)
            r.data.update({"mode": "proxy", "object": proxy.name})
        r.data.update({"regions": surfaces["regions"], "margin": margin_m})
        log_event("Collision", f"Enabled ({mode}, margin {margin_m * 1000:.0f} mm)", r)
        r.step("Enable collision")
        return r

    def _find_proxy(self, body: Any) -> Optional[Any]:
        for o in bscene.find_tagged(role=PROXY_ROLE):
            if o.get(bscene.TAG_AVATAR_SOURCE) == body.name:
                return o
        return None

    def _ensure_proxy(self, body: Any, avatar: AvatarModel, surfaces: Dict[str, Any], unit: float, r: Result) -> Any:
        proxy = self._find_proxy(body)
        if proxy is None:
            proxy = body.copy()
            proxy.data = body.data.copy()
            proxy.name = f"AIG_Collision_{body.name}"
            for key in (bscene.TAG_ID, bscene.TAG_ROLE, "ai_garment_avatar"):
                if key in proxy.keys():
                    del proxy[key]
            for m in list(proxy.modifiers):
                if m.type in ("COLLISION", "CLOTH"):
                    proxy.modifiers.remove(m)  # proxy is ours; the avatar is untouched
            bscene.link_new_object(proxy, bscene.ensure_collection(self.tx), f"avatar:{body.name}", PROXY_ROLE,
                                   self.tx)
            proxy[bscene.TAG_AVATAR_SOURCE] = body.name
            proxy.hide_render = True
            proxy.display_type = "WIRE"
            r.log(f"created collision proxy '{proxy.name}' (avatar object left unchanged)")
        # region mask: keep only the body parts this garment touches
        lo, hi = surfaces["z_range"]
        lo, hi = (lo - 0.05) / unit, (hi + 0.05) / unit
        coords = bscene.world_coords(body, evaluated=True)
        if len(coords) != len(proxy.data.vertices):
            coords = bscene.world_coords(proxy, evaluated=False)
            r.warn("Avatar modifiers change its vertex count; collision region computed from the rest pose.")
        keep = [i for i, c in enumerate(coords) if lo <= c[2] <= hi]
        vg = proxy.vertex_groups.get(REGION_GROUP) or proxy.vertex_groups.new(name=REGION_GROUP)
        vg.remove(list(range(len(coords))))
        if keep:
            vg.add(keep, 1.0, "REPLACE")
        if 0 < len(keep) < 0.9 * len(coords):
            mask, _ = bmods.get_or_add(proxy, bmods.MASK, "MASK", self.tx)
            mask.mode = "VERTEX_GROUP"
            mask.vertex_group = REGION_GROUP
        if len(keep) > PROXY_MAX_VERTS:
            dec, _ = bmods.get_or_add(proxy, bmods.DECIMATE, "DECIMATE", self.tx)
            dec.ratio = PROXY_MAX_VERTS / float(len(keep))
        existing = proxy.modifiers.get(bmods.COLLISION)
        if existing is not None and list(proxy.modifiers)[-1] is not existing:
            proxy.modifiers.remove(existing)  # collision must evaluate after mask/decimate
        bmods.get_or_add(proxy, bmods.COLLISION, "COLLISION", self.tx)
        return proxy

    def remove_collision(self, avatar: Any) -> Result:
        r = Result(action="remove_collision")
        body = self._avatar_obj(avatar)
        if body is None:
            return r.add_error("AVATAR_NOT_FOUND", MSG_AVATAR_NOT_FOUND)
        proxy = self._find_proxy(body)
        if proxy is not None:
            bscene.safe_remove_object(proxy, f"avatar:{body.name}")
            r.step("Remove collision proxy")
        if bmods.remove_own(body, bmods.COLLISION):
            r.step("Remove AIG_Collision modifier from avatar")
        return r

    def enable_self_collision(self, record: Any, preset: str = "preview") -> Result:
        r = Result(action="enable_self_collision")
        obj = self._obj(record)
        cloth = self._cloth(obj) or self._apply_physics(record, obj)
        p = self_collision_preset(preset)
        bphys.apply_self_collision(cloth, p, record.unit_scale)
        record.spec.simulation.self_collision = p is not None
        record.spec.metadata["self_collision_preset"] = preset
        log_event("Self Collision", "Enabled" if p else "Disabled", r)
        self._persist(record, obj)
        return r

    # ------------------------------------------------------------------ simulation
    def simulate(self, record: Any, settings: Dict[str, Any], avatar: Any = None) -> Result:
        r = Result(action="simulate")
        obj = self._obj(record)
        scene = bscene.current_scene()
        s = settings
        if s.get("gravity", True):
            bscene.set_attr(scene, "use_gravity", True, self.tx, "scene gravity")
            log_event("Gravity", "Enabled", r)
        if s.get("collision", True):
            if avatar is not None and self._avatar_obj(avatar) is not None:
                if not record.state.get("collision"):
                    r.merge(self.prepare_collision(avatar, {"garment_type": record.spec.type}), "collision")
                    record.state["collision"] = True
            else:
                r.warn("No avatar available: simulating without body collision.")
        cloth = self._apply_physics(record, obj, s["quality"], s["self_collision"])
        if cloth.point_cache.is_baked:
            bsim.free_bake(obj, cloth)
        bsim.configure_cache(cloth, s["frame_start"], s["frame_end"], s.get("use_disk_cache", False))
        log_event("Self Collision", "Enabled" if s["self_collision"] else "Disabled", r)
        log_event("Simulation", f"Started ({s['mode']}, {s['quality']})", r)
        r.step("Simulate")
        unit = record.unit_scale or 1.0
        if s.get("settle", True):
            res = bsim.settle(obj, cloth, s["frame_start"], int(s["settle_frames"]), s["settle_threshold"] / unit,
                              int(s["settle_window"]))
            res.pop("final_local_coords", None)
            r.data["settle"] = res
            record.state["settled"] = res["settled"]
            if res["settled"]:
                log_event("Simulation", f"Settled at frame {res['settled_frame']}", r)
            else:
                r.warn("Cloth did not fully settle within the frame budget; increase settle frames or damping.")
        r.data["diagnostics"] = self._diagnose(obj, avatar, unit, r)
        if s.get("bake"):
            b = bsim.bake(obj, cloth, s["frame_start"], s["frame_end"])
            r.data["bake"] = b
            r.data["baked"] = b["baked"]
            record.state["baked"] = b["baked"]
            if b["baked"]:
                log_event("Bake", "Complete", r)
            else:
                r.warn("Bake could not be finalised: " + "; ".join(b.get("errors", [])))
        else:
            r.data["baked"] = False
        record.state["simulated"] = True
        r.data["settings"] = {k: v for k, v in s.items()}
        self._persist(record, obj)
        return r

    def _diagnose(self, obj: Any, avatar: Optional[AvatarModel], unit: float, r: Result) -> Dict[str, Any]:
        body = self._avatar_obj(avatar)
        pts = bsim.evaluated_world(obj)
        out: Dict[str, Any] = {}
        if body is not None:
            pen = analyze_penetration(signed_distances(body_nearest(body), pts), tolerance=0.002 / unit)
            (bmin, bmax) = avatar.bounds
            stab = analyze_stability(bscene.bbox(pts), (tuple(c / unit for c in bmin), tuple(c / unit for c in bmax)),
                                     has_nan=any(c != c for p in pts for c in p))
            out = {"penetration": pen.to_dict(), "stability": stab.to_dict()}
            for diag in (pen, stab):
                for issue in diag.issues:
                    r.warn(f"{issue.message} Suggested action: {' or '.join(issue.suggestions)}")
        else:
            out["note"] = "no avatar: penetration check skipped"
        return out

    def settle(self, record: Any, settings: Dict[str, Any], avatar: Any = None) -> Result:
        r = Result(action="settle")
        obj = self._obj(record)
        cloth = self._cloth(obj) or self._apply_physics(record, obj)
        if cloth.point_cache.is_baked:
            bsim.free_bake(obj, cloth)
        bsim.remove_settled_shape(obj)
        unit = record.unit_scale or 1.0
        fs = int(settings.get("frame_start", record.spec.simulation.frame_start))
        res = bsim.settle(obj, cloth, fs, int(settings["settle_frames"]), settings["settle_threshold"] / unit,
                          int(settings["settle_window"]))
        coords = res.pop("final_local_coords")
        r.data.update(res)
        record.state["settled"] = res["settled"]
        if not res["settled"]:
            r.warn("Cloth did not fully settle within the frame budget; increase max_frames or damping.")
        if settings.get("apply") == "shape_key" and res["settled"]:
            r.data["shape_key"] = bsim.apply_settled_shape(obj, coords)
            bsim.scene_frame(fs)
            r.step("Store settled drape as shape key AIG_Settled")
        log_event("Simulation", "Settled" if res["settled"] else "Not settled", r)
        r.step("Settle under gravity")
        self._persist(record, obj)
        return r

    def bake(self, record: Any, settings: Optional[Dict[str, Any]] = None) -> Result:
        r = Result(action="bake")
        obj = self._obj(record)
        cloth = self._cloth(obj) or self._apply_physics(record, obj)
        s = settings or {}
        fs = int(s.get("frame_start") or cloth.point_cache.frame_start)
        fe = int(s.get("frame_end") or cloth.point_cache.frame_end)
        b = bsim.bake(obj, cloth, fs, fe)
        r.data.update(b)
        record.state["baked"] = b["baked"]
        if b["baked"]:
            log_event("Bake", "Complete", r)
        else:
            r.add_error("BAKE_FAILED", "Bake could not be finalised: " + "; ".join(b.get("errors", [])),
                        ["bake from the Physics properties panel", "check the cache frame range"])
        self._persist(record, obj)
        return r

    def reset(self, record: Any, level: str = "simulation") -> Result:
        r = Result(action="reset")
        obj = self._obj(record)
        cloth = self._cloth(obj)
        if cloth is not None and cloth.point_cache.is_baked:
            bsim.free_bake(obj, cloth)
            r.step("Free bake")
        if bsim.remove_settled_shape(obj):
            r.step("Remove settled shape key")
        record.state.update({"simulated": False, "settled": False, "baked": False})
        bsim.scene_frame(record.spec.simulation.frame_start)
        if level in ("geometry", "all"):
            r.merge(self.update_garment(record, {"geometry"}))
        self._persist(record, obj)
        return r

    # ------------------------------------------------------------------ inspection / housekeeping
    def inspect(self, record: Any) -> Dict[str, Any]:
        spec = record.spec
        info: Dict[str, Any] = {"id": record.id, "name": record.name, "garment": spec.display_name.title(),
                                "type": spec.type, "provider": self.display_name, "fabric": spec.fabric.display,
                                "fit": spec.fit.level, "color": spec.color, "length": spec.length,
                                "components": [c.name for c in spec.components], "object": record.object_name,
                                "avatar": record.avatar_name, "state": {k: v for k, v in record.state.items()
                                                                        if k != "physics_groups"},
                                "warnings": []}
        try:
            obj = self._obj(record)
        except GarmentError as err:
            info["warnings"].append(err.message)
            info["simulation"] = {"cloth": False, "collision": False, "self_collision": False, "baked": False}
            return info
        cloth = self._cloth(obj)
        body = get_bpy().data.objects.get(record.avatar_name or "")
        collision = False
        if body is not None:
            collision = self._find_proxy(body) is not None or any(m.type == "COLLISION" for m in body.modifiers)
        elif record.avatar_name:
            info["warnings"].append(f"Avatar '{record.avatar_name}' is no longer in the scene.")
        info["simulation"] = {"cloth": cloth is not None, "collision": collision,
                              "self_collision": bool(cloth and cloth.collision_settings.use_self_collision),
                              "baked": bool(cloth and cloth.point_cache.is_baked)}
        if cloth is not None:
            info["physics"] = bphys.cloth_summary(cloth)
        info["modifiers"] = [m.name for m in obj.modifiers]
        info["vertex_groups"] = [g.name for g in obj.vertex_groups]
        if not collision and record.state.get("simulated"):
            info["warnings"].append("Simulated without body collision.")
        return info

    def delete_garment(self, record: Any) -> Result:
        r = Result(action="delete_garment")
        bpy = get_bpy()
        for obj in bscene.find_tagged(record.id):
            name = obj.name
            bscene.safe_remove_object(obj, record.id)
            r.step(f"Deleted {name}")
        for mat in [m for m in bpy.data.materials if m.get(bscene.TAG_ID) == record.id]:
            bpy.data.materials.remove(mat)
        return r

    def duplicate_garment(self, record: Any, new_record: Any) -> Result:
        r = Result(action="duplicate_garment")
        obj = self._obj(record)
        new = duplicate_object(obj, f"AIG_{new_record.name}", bscene.ensure_collection(self.tx), new_record.id,
                               self.tx)
        new_record.object_name = new.name
        new_record.avatar_name = record.avatar_name
        new_record.unit_scale = record.unit_scale
        new_record.state = dict(record.state, baked=False)
        self._persist(new_record, new)
        r.data["object"] = new.name
        return r
