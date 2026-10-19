import pytest

from fakes import FakeBackend
from klipper_hotspot.config import Config
from klipper_hotspot.credentials import Credentials
from klipper_hotspot.manager import Manager
from klipper_hotspot.policy import ManualPolicy
from klipper_hotspot.store import StateStore

PASSWORD = "s3cretpw9x2m"  # distinctive so log/secret-leak tests can search for it


@pytest.fixture
def credentials():
    return Credentials(ssid="Klipper-TEST", password=PASSWORD)


@pytest.fixture
def backend():
    return FakeBackend()


@pytest.fixture
def make_manager(tmp_path, credentials):
    def _make(backend, *, autostart=False, clock=None):
        config = Config(autostart=autostart, state_file=str(tmp_path / "state.json"))
        kwargs = {"clock": clock} if clock else {}
        store = StateStore(config.state_file)
        manager = Manager(
            config=config,
            credentials=credentials,
            backend=backend,
            store=store,
            policy=ManualPolicy(autostart),
            **kwargs,
        )
        return manager, store

    return _make
