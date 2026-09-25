"""Sidebar panel + operators. Imported only from register() (needs bpy.types at import)."""
from __future__ import annotations

import json

import bpy

from ..api.garment import garment as default_system
from . import scene as bscene

REPORT_TEXT = "AI_Garment_Report"


def _write_report(title: str, payload) -> None:
    text = bpy.data.texts.get(REPORT_TEXT) if hasattr(bpy.data.texts, "get") else None
    if text is None:
        text = bpy.data.texts.new(REPORT_TEXT)
    text.clear()
    text.write(f"# {title}\n{json.dumps(payload, indent=2, default=str)}\n")


def _report_result(op, result, success_msg: str):
    for w in result.warnings[:5]:
        op.report({"WARNING"}, w)
    if not result.ok:
        for e in result.errors[:5]:
            op.report({"ERROR"}, f"{e.code}: {e.message}")
        return {"CANCELLED"}
    op.report({"INFO"}, success_msg)
    return {"FINISHED"}


class AI_GARMENT_OT_preview_plan(bpy.types.Operator):
    """Dry run: show what the instruction would do (no scene changes)"""
    bl_idname = "ai_garment.preview_plan"
    bl_label = "Preview Plan"

    def execute(self, context):
        text = context.scene.ai_garment_instruction
        result = default_system.plan(text)
        _write_report("Plan preview", result.to_dict())
        return _report_result(self, result, "Plan: " + "; ".join(result.operations)[:200])


class AI_GARMENT_OT_execute_instruction(bpy.types.Operator):
    """Execute the instruction (transactional: rolled back on failure)"""
    bl_idname = "ai_garment.execute_instruction"
    bl_label = "Execute"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        text = context.scene.ai_garment_instruction
        result = default_system.run(text)
        _write_report("Execution", result.to_dict())
        return _report_result(self, result, "Done: " + "; ".join(result.operations)[:200])


class AI_GARMENT_OT_detect_avatar(bpy.types.Operator):
    """Detect the character and report measurements"""
    bl_idname = "ai_garment.detect_avatar"
    bl_label = "Detect Avatar"

    def execute(self, context):
        handle = default_system.detect_avatar()
        _write_report("Avatar", handle.to_dict())
        if not handle.ok:
            self.report({"ERROR"}, handle.result.errors[0].message)
            return {"CANCELLED"}
        self.report({"INFO"}, f"Avatar: {handle.name} ({handle.model.source})")
        return {"FINISHED"}


def _active_garment(context):
    obj = getattr(context, "active_object", None)
    if obj is not None and obj.get(bscene.TAG_ROLE) == "garment":
        g = default_system.get(obj.get(bscene.TAG_ID))
        if g is not None:
            return g
    items = default_system.list_garments()
    return default_system.get(items[-1]["id"]) if items else None


class AI_GARMENT_OT_inspect_garment(bpy.types.Operator):
    """Write the active (or last) garment's state to the AI_Garment_Report text"""
    bl_idname = "ai_garment.inspect_garment"
    bl_label = "Inspect Garment"

    def execute(self, context):
        g = _active_garment(context)
        if g is None:
            self.report({"WARNING"}, "No AI garment in this session.")
            return {"CANCELLED"}
        _write_report("Inspection", g.inspect())
        self.report({"INFO"}, f"Inspected {g.name}")
        return {"FINISHED"}


class AI_GARMENT_OT_bake_garment(bpy.types.Operator):
    """Bake the active (or last) garment"""
    bl_idname = "ai_garment.bake_garment"
    bl_label = "Bake Garment"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        g = _active_garment(context)
        if g is None:
            self.report({"WARNING"}, "No AI garment in this session.")
            return {"CANCELLED"}
        return _report_result(self, g.bake(), f"Baked {g.name}")


class AI_GARMENT_PT_panel(bpy.types.Panel):
    bl_idname = "AI_GARMENT_PT_panel"
    bl_label = "AI Garment"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AI Garment"

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "ai_garment_instruction", text="")
        row = layout.row(align=True)
        row.operator("ai_garment.preview_plan")
        row.operator("ai_garment.execute_instruction")
        layout.operator("ai_garment.detect_avatar")
        row = layout.row(align=True)
        row.operator("ai_garment.inspect_garment")
        row.operator("ai_garment.bake_garment")


CLASSES = (AI_GARMENT_OT_preview_plan, AI_GARMENT_OT_execute_instruction, AI_GARMENT_OT_detect_avatar,
           AI_GARMENT_OT_inspect_garment, AI_GARMENT_OT_bake_garment, AI_GARMENT_PT_panel)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ai_garment_instruction = bpy.props.StringProperty(
        name="Instruction", description="Describe the garment or change, e.g. 'Create a loose black hoodie'",
        default="")


def unregister() -> None:
    if hasattr(bpy.types.Scene, "ai_garment_instruction"):
        del bpy.types.Scene.ai_garment_instruction
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
