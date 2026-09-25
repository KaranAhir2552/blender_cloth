"""REAL-Blender test suite for ai_garment.  *** REQUIRES BLENDER ***

Run from the repository root:

    blender --background --factory-startup --python tests/blender/run_blender_tests.py

Optional: ``-- --keep`` keeps the generated scene objects (no cleanup) and
``-- --save /tmp/ai_garment_test.blend`` saves the resulting file for inspection.

Exit code 0 = all steps passed, 1 = at least one step failed.
A JSON report is written to tests/blender/last_run.json.

This file is never collected by pytest and must never be reported as passed
unless it was actually executed by Blender.
"""
import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (ROOT, os.path.join(ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    import bpy  # must be real Blender
except ImportError:
    print("run_blender_tests.py must be executed by Blender: blender --background --python " + __file__)
    sys.exit(2)

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
RESULTS = []
STATE = {}


def step(name, depends=()):
    def deco(fn):
        def run():
            missing = [d for d in depends if not any(r["name"] == d and r["status"] == "PASS" for r in RESULTS)]
            if missing:
                RESULTS.append({"name": name, "status": "SKIP", "detail": f"depends on failed step(s) {missing}"})
                print(f"[SKIP] {name}: depends on {missing}")
                return
            t0 = time.time()
            try:
                detail = fn()
                RESULTS.append({"name": name, "status": "PASS", "detail": detail, "seconds": round(time.time() - t0, 2)})
                print(f"[PASS] {name} ({time.time() - t0:.1f}s) {detail or ''}")
            except Exception as err:  # report everything; never hide a failure
                RESULTS.append({"name": name, "status": "FAIL", "detail": f"{type(err).__name__}: {err}",
                                "traceback": traceback.format_exc()})
                print(f"[FAIL] {name}: {type(err).__name__}: {err}")
                traceback.print_exc()
        run.step_name = name
        return run
    return deco


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ----------------------------------------------------------------------------
@step("01 extension registration")
def t_register():
    import ai_garment
    ai_garment.register()
    STATE["pkg"] = ai_garment
    check(hasattr(bpy.types, "AI_GARMENT_PT_panel"), "panel not registered")
    check(hasattr(bpy.types.Scene, "ai_garment_instruction"), "scene property missing")
    check(bpy.ops.ai_garment.preview_plan.get_rna_type() is not None, "operator missing")
    return "panel + 5 operators registered"


@step("02 Blender API contract (hasattr on real RNA)", depends=("01 extension registration",))
def t_contract():
    from ai_garment.blender.api_contract import CONTRACT, MODIFIER_TYPES, OPERATORS
    from ai_garment.providers.external import operator_exists
    missing = []
    for cls_name, attrs in CONTRACT.items():
        cls = getattr(bpy.types, cls_name, None)
        if cls is None:
            missing.append(f"bpy.types.{cls_name}")
            continue
        rna = cls.bl_rna
        names = set()
        while rna is not None:
            names |= set(rna.properties.keys()) | set(rna.functions.keys())
            rna = rna.base
        for a in attrs:
            if a not in names and not hasattr(cls, a):
                missing.append(f"{cls_name}.{a}")
    enum = set(bpy.types.Modifier.bl_rna.properties["type"].enum_items.keys())
    missing += [f"modifier type {m}" for m in MODIFIER_TYPES if m not in enum]
    missing += [f"operator {o}" for o in OPERATORS if not operator_exists(bpy, o)]
    check(not operator_exists(bpy, "ptcache.this_operator_does_not_exist"),
          "operator_exists() returned True for a missing operator (detection assumption wrong)")
    check(not missing, f"missing API: {missing}")
    return f"{sum(len(v) for v in CONTRACT.values())} attributes, {len(OPERATORS)} operators verified"


@step("03 build synthetic rigged humanoid")
def t_humanoid():
    from fixtures.humanoid import make_humanoid
    h = make_humanoid(rig="makehuman")
    scene = bpy.context.scene
    arm_data = bpy.data.armatures.new("TestHuman_rig")
    arm = bpy.data.objects.new("TestHuman_rig", arm_data)
    scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for name, (head, tail) in h["bones"].items():
        eb = arm_data.edit_bones.new(name)
        eb.head, eb.tail = head, tail
    bpy.ops.object.mode_set(mode="OBJECT")
    mesh = bpy.data.meshes.new("TestHuman")
    mesh.from_pydata(h["vertices"], [], h["faces"])
    mesh.update()
    body = bpy.data.objects.new("TestHuman", mesh)
    scene.collection.objects.link(body)
    for gname, idx in h["vertex_groups"].items():
        body.vertex_groups.new(name=gname).add(idx, 1.0, "REPLACE")
    mod = body.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    body.parent = arm
    body["MPFB_GEN_object_type"] = "Basemesh"
    bpy.context.view_layer.objects.active = body
    STATE.update(body=body, arm=arm, fixture=h,
                 body_snapshot=([m.name for m in body.modifiers], [g.name for g in body.vertex_groups]))
    return f"{len(h['vertices'])} vertices, {len(h['bones'])} bones"


@step("04 provider detection", depends=("01 extension registration",))
def t_provider():
    from ai_garment import garment
    sel = garment.detect_provider()
    check(sel.provider is not None and sel.provider.name == "blender_native", f"selection: {sel.to_dict()}")
    others = {s["name"]: s["available"] for s in garment.providers()}
    return f"selected {sel.provider.display_name}; statuses {others}"


@step("05 avatar detection", depends=("03 build synthetic rigged humanoid",))
def t_avatar():
    from ai_garment import garment
    av = garment.detect_avatar()
    check(av.ok, f"avatar not found: {av.result.to_dict()}")
    check(av.name == "TestHuman", f"wrong avatar {av.name}")
    m = av.get_measurements()
    exp = STATE["fixture"]["expected"]
    for k in ("chest_circumference", "waist_circumference", "hip_circumference"):
        check(abs(m[k] - exp[k]) / exp[k] < 0.15, f"{k} {m[k]:.3f} vs {exp[k]:.3f}")
    STATE["avatar"] = av
    return f"source={av.model.source} pose={av.model.pose} chest={m['chest_circumference']:.3f}"


@step("06 garment creation", depends=("05 avatar detection",))
def t_create():
    from ai_garment import garment
    shirt = garment.create(type="tshirt", fit="oversized", fabric="cotton", color="black")
    obj = bpy.data.objects[shirt.object_name]
    types = [m.type for m in obj.modifiers]
    check("CLOTH" in types, f"no cloth modifier: {types}")
    check(types.index("CLOTH") < types.index("SOLIDIFY"), f"modifier order {types}")
    check(obj.vertex_groups.get("AIG_left_sleeve") is not None, "component groups missing")
    check(len(obj.data.materials) == 1, "material missing")
    STATE["shirt"] = shirt
    return f"{shirt.object_name}: {len(obj.data.vertices)} verts, modifiers {types}"


@step("07 fitting + collision setup", depends=("06 garment creation",))
def t_fit():
    shirt = STATE["shirt"]
    r = shirt.fit_to_avatar()
    check(r.ok, json.dumps(r.to_dict())[:2000])
    proxies = [o for o in bpy.data.objects if o.get("ai_garment_role") == "collision_proxy"]
    check(len(proxies) == 1, f"{len(proxies)} collision proxies")
    check(proxies[0].modifiers[-1].type == "COLLISION", "collision modifier must be last on the proxy")
    body = STATE["body"]
    check(([m.name for m in body.modifiers], [g.name for g in body.vertex_groups]) == STATE["body_snapshot"],
          "avatar object was modified")
    return f"proxy {proxies[0].name}, margin {proxies[0].collision.thickness_outer:.4f}"


@step("08 cloth + elastic + sewing configuration", depends=("07 fitting + collision setup",))
def t_cloth():
    shirt = STATE["shirt"]
    r = shirt.add_component(type="elastic_cuff", target="sleeves", strength="medium")
    check(r.ok, json.dumps(r.to_dict())[:2000])
    obj = bpy.data.objects[shirt.object_name]
    cloth = obj.modifiers["AIG_Cloth"]
    s = cloth.settings
    check(s.use_sewing_springs and s.sewing_force_max > 0, "sewing springs not enabled")
    check(s.vertex_group_shrink == "AIG_shrink" and s.shrink_max > 0, "elastic shrink not configured")
    loose = len(obj.data.edges) - len({tuple(sorted(e)) for p in obj.data.polygons for e in p.edge_keys})
    check(loose > 0, "no loose (sewing) edges")
    return f"mass={s.mass:.3f} tension={s.tension_stiffness} shrink_max={s.shrink_max:.3f} sewing edges={loose}"


@step("09 simulation + settle (draft)", depends=("08 cloth + elastic + sewing configuration",))
def t_simulate():
    shirt = STATE["shirt"]
    r = shirt.simulate(mode="preview", quality="draft")
    check(r.ok, json.dumps(r.to_dict())[:3000])
    diag = r.data["diagnostics"]
    stab = diag["stability"]
    check(stab["ok"], f"unstable / fell: {stab}")
    pen = diag["penetration"]
    STATE["penetration"] = pen
    return (f"settled={r.data['settle']['settled']} frames={r.data['settle']['frames_run']} "
            f"penetrating={pen['penetrating_fraction']:.3f} extent_ratio={stab['ratio']}")


@step("10 baking", depends=("09 simulation + settle (draft)",))
def t_bake():
    shirt = STATE["shirt"]
    r = shirt.bake(frame_start=1, frame_end=20)
    check(r.ok, json.dumps(r.to_dict())[:2000])
    cloth = bpy.data.objects[shirt.object_name].modifiers["AIG_Cloth"]
    check(cloth.point_cache.is_baked, "point cache not baked")
    return f"method={r.data.get('method')}"


@step("11 modify / refabric / settle shape key", depends=("10 baking",))
def t_modify():
    shirt = STATE["shirt"]
    r = shirt.modify(component="sleeves", length="-20%")
    check(r.ok, json.dumps(r.to_dict())[:2000])
    r = shirt.set_fabric("heavy denim")
    check(r.ok, json.dumps(r.to_dict())[:2000])
    r = shirt.settle(max_frames=30, apply="shape_key")
    check(r.ok, json.dumps(r.to_dict())[:2000])
    info = shirt.inspect()
    check(info["fabric"] == "heavy denim", info)
    return f"inspect={json.dumps(info['simulation'])} settled={r.data.get('settled')}"


@step("12 pants + dry run + invalid spec safety", depends=("05 avatar detection",))
def t_pants():
    from ai_garment import GarmentError, garment
    before = sorted(o.name for o in bpy.data.objects)
    plan = garment.plan("Create loose cargo pants with elastic cuffs and let them settle")
    check(plan.to_dict()["valid"], plan.to_dict())
    try:
        garment.create(type="tshirt", fabric="unicorn_skin")
        raise AssertionError("invalid spec accepted")
    except GarmentError as err:
        check(err.code == "VALIDATION_FAILED", err.code)
    check(sorted(o.name for o in bpy.data.objects) == before, "dry run / invalid spec mutated the scene")
    pants = garment.create(type="pants", fit="loose")
    check(pants.fit_to_avatar().ok, "pants fit failed")
    r = pants.simulate(mode="draft")
    check(r.ok, json.dumps(r.to_dict())[:2000])
    STATE["pants"] = pants
    return f"pants stability {r.data['diagnostics']['stability']['ok']}"


@step("13 cleanup (only tagged objects removed)", depends=("06 garment creation",))
def t_cleanup():
    if "--keep" in ARGS:
        return "skipped (--keep)"
    for key in ("shirt", "pants"):
        g = STATE.get(key)
        if g is not None:
            check(g.delete().ok, f"delete {key} failed")
    av = STATE.get("avatar")
    if av is not None:
        check(av.remove_collision().ok, "remove_collision failed")
    leftovers = [o.name for o in bpy.data.objects if o.get("ai_garment_id")]
    check(not leftovers, f"leftover tagged objects {leftovers}")
    check(bpy.data.objects.get("TestHuman") is not None, "avatar was deleted!")
    STATE["pkg"].unregister()
    check(not hasattr(bpy.types, "AI_GARMENT_PT_panel"), "unregister failed")
    return "garments, proxy removed; avatar intact; unregistered"


def main():
    for fn in (t_register, t_contract, t_humanoid, t_provider, t_avatar, t_create, t_fit, t_cloth, t_simulate,
               t_bake, t_modify, t_pants, t_cleanup):
        fn()
    if "--save" in ARGS:
        path = ARGS[ARGS.index("--save") + 1]
        bpy.ops.wm.save_as_mainfile(filepath=path)
    passed = sum(r["status"] == "PASS" for r in RESULTS)
    failed = sum(r["status"] == "FAIL" for r in RESULTS)
    skipped = sum(r["status"] == "SKIP" for r in RESULTS)
    report = {"blender": bpy.app.version_string, "passed": passed, "failed": failed, "skipped": skipped,
              "results": RESULTS}
    with open(os.path.join(HERE, "last_run.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print("\n==== ai_garment REAL BLENDER TESTS ====")
    print(f"Blender {bpy.app.version_string}: {passed} passed, {failed} failed, {skipped} skipped")
    print("Real Blender tests:", "PASS" if failed == 0 and skipped == 0 else "FAIL")
    sys.exit(0 if failed == 0 and skipped == 0 else 1)


main()
