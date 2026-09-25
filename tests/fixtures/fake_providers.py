"""Pure-Python fake providers used by planner / dispatcher tests."""
from ai_garment.core.results import Result
from ai_garment.providers.base import Capability, GarmentProvider, ProviderStatus


class RecordingProvider(GarmentProvider):
    """Available provider that records every call; performs no scene work."""

    def __init__(self, name="fake_native", display_name="Fake Native", priority=0, capabilities=None):
        self.name = name
        self.display_name = display_name
        self.priority = priority
        self.capabilities = frozenset(capabilities if capabilities is not None else Capability.CORE)
        self.calls = []

    def available(self):
        return ProviderStatus(self.name, self.display_name, True, "fake", capabilities=sorted(self.capabilities))

    def _record(self, name, *args):
        self.calls.append(name)
        return Result(action=name)

    def create_garment(self, record, avatar, context=None):
        return self._record("create_garment")

    def update_garment(self, record, effects, avatar=None, context=None):
        return self._record("update_garment")

    def fit_garment(self, record, avatar, context=None):
        return self._record("fit_garment")

    def simulate(self, record, settings, avatar=None):
        return self._record("simulate")

    def bake(self, record, settings=None):
        return self._record("bake")
