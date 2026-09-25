import sys

from mocks.mock_bpy import build_humanoid_scene


def test_register_and_unregister(mock_bpy):
    import ai_garment
    ai_garment.register()
    try:
        names = {c.__name__ for c in mock_bpy.utils.registered}
        assert "AI_GARMENT_PT_panel" in names
        assert {"AI_GARMENT_OT_preview_plan", "AI_GARMENT_OT_execute_instruction", "AI_GARMENT_OT_detect_avatar",
                "AI_GARMENT_OT_bake_garment", "AI_GARMENT_OT_inspect_garment"} <= names
        assert hasattr(mock_bpy.types.Scene, "ai_garment_instruction")
        assert sys.modules.get("ai_garment") is ai_garment
        from ai_garment import garment  # the documented import works
        assert garment is not None
    finally:
        ai_garment.unregister()
    assert mock_bpy.utils.registered == []
    assert not hasattr(mock_bpy.types.Scene, "ai_garment_instruction")


def test_operators_execute(mock_bpy, humanoid):
    import types

    import ai_garment
    from ai_garment.blender import ui

    build_humanoid_scene(mock_bpy, humanoid)
    ai_garment.register()
    try:
        scene = mock_bpy.context.scene
        scene.ai_garment_instruction = "Create a black cotton t-shirt"
        ctx = types.SimpleNamespace(scene=scene)
        assert ui.AI_GARMENT_OT_preview_plan().execute(ctx) == {"FINISHED"}
        assert ui.AI_GARMENT_OT_detect_avatar().execute(ctx) == {"FINISHED"}
        assert ui.AI_GARMENT_OT_execute_instruction().execute(ctx) == {"FINISHED"}
        assert any(o.get("ai_garment_role") == "garment" for o in mock_bpy.data.objects)
        scene.ai_garment_instruction = "Sing me a song"
        assert ui.AI_GARMENT_OT_execute_instruction().execute(ctx) == {"CANCELLED"}
        assert any(level == ("WARNING",) or level == ("ERROR",) for level, _ in mock_bpy.reports)
    finally:
        ai_garment.unregister()
