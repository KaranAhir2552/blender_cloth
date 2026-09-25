from ai_garment.providers.base import Capability
from ai_garment.providers.blender_native import BlenderNativeProvider
from ai_garment.providers.opensew import OpenSewProvider
from ai_garment.providers.registry import ProviderRegistry
from ai_garment.providers.simply_cloth import SimplyClothProvider
from mocks.mock_bpy import _OpNamespace


def test_not_installed(mock_bpy):
    st = OpenSewProvider().available()
    assert st.available is False
    assert "not installed" in st.reason.lower() or "not enabled" in st.reason.lower()
    assert st.details["installed"] is False


def test_installed_without_mapping_is_unavailable(mock_bpy):
    mock_bpy.context.preferences.addons["opensew"] = object()
    st = OpenSewProvider().available()
    assert st.details["installed"] is True
    assert st.available is False
    assert "operator mapping" in st.reason.lower()


def test_extension_style_module_names_detected(mock_bpy):
    mock_bpy.context.preferences.addons["bl_ext.user_default.simply_cloth_studio"] = object()
    st = SimplyClothProvider().available()
    assert st.details["installed"] is True
    assert st.details["module"] == "bl_ext.user_default.simply_cloth_studio"


def test_mapped_operator_missing(mock_bpy):
    mock_bpy.context.preferences.addons["opensew"] = object()
    st = OpenSewProvider(operator_map={Capability.CREATE_GARMENT: "opensew.nope"}).available()
    assert st.available is False
    assert "opensew.nope" in st.reason


def test_mapped_operator_routes_and_native_fills_gaps(mock_bpy):
    called = []
    mock_bpy.context.preferences.addons["opensew"] = object()
    mock_bpy.ops.opensew = _OpNamespace("opensew", {"make_garment": lambda **kw: called.append(kw) or {"FINISHED"}})
    sew = OpenSewProvider(operator_map={Capability.CREATE_GARMENT: "opensew.make_garment"},
                          operator_kwargs={Capability.CREATE_GARMENT: {"preset": "{type}"}})
    st = sew.available()
    assert st.available, st.reason
    assert sew.capabilities == frozenset({Capability.CREATE_GARMENT})

    reg = ProviderRegistry()
    reg.register(BlenderNativeProvider())
    reg.register(sew)
    sel = reg.select(required={Capability.CREATE_GARMENT}, preferred="opensew")
    assert sel.provider is sew and not sel.fallback_used
    assert reg.provider_for(Capability.SIMULATE, preferred="opensew").name == "blender_native"

    from ai_garment.api.session import GarmentRecord
    from ai_garment.core.garment_spec import GarmentSpec
    rec = GarmentRecord.new(GarmentSpec.from_dict({"type": "tshirt"}), provider="opensew")
    r = sew.create_garment(rec, avatar=None)
    assert r.ok, r.to_dict()
    assert called == [{"preset": "tshirt"}]
    assert any("verify" in w.lower() for w in r.warnings)
