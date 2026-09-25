from ai_garment.core.results import Result
from ai_garment.providers.base import Capability, GarmentProvider, ProviderStatus
from ai_garment.providers.blender_native import BlenderNativeProvider
from ai_garment.providers.garment_tool import GarmentToolProvider
from ai_garment.providers.opensew import OpenSewProvider
from ai_garment.providers.registry import ProviderRegistry, default_registry
from ai_garment.providers.simply_cloth import SimplyClothProvider


class FakeProvider(GarmentProvider):
    def __init__(self, name="fake", display_name="Fake", priority=10, available=True, capabilities=None,
                 raise_on_available=False):
        self.name = name
        self.display_name = display_name
        self.priority = priority
        self.capabilities = frozenset(capabilities if capabilities is not None else Capability.CORE)
        self._available = available
        self._raise = raise_on_available

    def available(self):
        if self._raise:
            raise RuntimeError("adapter exploded")
        return ProviderStatus(self.name, self.display_name, self._available,
                              "ok" if self._available else "not installed", capabilities=sorted(self.capabilities))


def fake_native():
    return FakeProvider(name="blender_native", display_name="Blender Native Cloth", priority=0)


def test_external_adapters_report_unavailable_without_blender():
    for cls in (OpenSewProvider, SimplyClothProvider, GarmentToolProvider):
        st = cls().available()
        assert st.available is False
        assert "blender" in st.reason.lower()


def test_native_unavailable_without_blender():
    st = BlenderNativeProvider().available()
    assert st.available is False
    assert "blender" in st.reason.lower()


def test_fallback_to_native_with_canonical_warning():
    """Brief test 6."""
    reg = ProviderRegistry()
    reg.register(fake_native())
    reg.register(OpenSewProvider())
    sel = reg.select(required={Capability.CREATE_GARMENT}, preferred="opensew")
    assert sel.provider is not None
    assert sel.provider.name == "blender_native"
    assert sel.fallback_used
    assert ("Provider OpenSew unavailable. Fallback provider: Blender Native Cloth. "
            "Some garment construction features may be unavailable.") in sel.warnings


def test_no_provider_available_is_structured():
    reg = ProviderRegistry()
    reg.register(OpenSewProvider())
    sel = reg.select(required={Capability.CREATE_GARMENT})
    assert sel.provider is None
    assert sel.error.code == "NO_PROVIDER_AVAILABLE"
    assert sel.to_dict()["provider"] is None


def test_exception_in_available_is_contained():
    reg = ProviderRegistry()
    reg.register(FakeProvider(name="boom", raise_on_available=True, priority=100))
    reg.register(fake_native())
    statuses = {s.name: s for s in reg.statuses()}
    assert statuses["boom"].available is False
    assert "adapter exploded" in statuses["boom"].reason
    assert reg.select(required={Capability.CREATE_GARMENT}).provider.name == "blender_native"


def test_priority_and_capability_filtering():
    reg = ProviderRegistry()
    reg.register(fake_native())
    reg.register(FakeProvider(name="pattern_pro", priority=50,
                              capabilities=Capability.CORE | {Capability.PATTERN_CONSTRUCTION}))
    assert reg.select(required={Capability.CREATE_GARMENT}).provider.name == "pattern_pro"
    assert reg.select(required={Capability.WRINKLES}).provider is None


def test_capability_routing():
    reg = ProviderRegistry()
    reg.register(fake_native())
    assert reg.provider_for(Capability.WRINKLES) is None
    reg.register(FakeProvider(name="wrinkler", priority=5, capabilities={Capability.WRINKLES}))
    assert reg.provider_for(Capability.WRINKLES).name == "wrinkler"
    assert reg.provider_for(Capability.SIMULATE).name == "blender_native"


def test_supports():
    p = FakeProvider(capabilities={Capability.SEWING})
    assert p.supports("sewing")
    assert not p.supports("wrinkles")


def test_unsupported_capability_returns_structured_result():
    p = FakeProvider(capabilities={Capability.CREATE_GARMENT})
    r = p.generate_wrinkles(None, {})
    assert isinstance(r, Result)
    assert r.ok is False
    assert r.errors[0].code == "CAPABILITY_NOT_SUPPORTED"


def test_default_registry_contents():
    reg = default_registry()
    assert {p.name for p in reg.providers()} == {"blender_native", "opensew", "simply_cloth", "garment_tool"}
    for p in reg.providers():
        assert p.capabilities <= Capability.ALL
    sel = reg.select(required={Capability.CREATE_GARMENT})
    assert sel.provider is None  # no Blender here
    assert "Blender" in sel.error.message
