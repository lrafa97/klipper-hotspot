"""One contract, three implementations.

* FakeBackend         - the double used by the manager tests. If it breaks the contract, those tests lie.
* NmcliBackend + sim  - the real command logic against a simulated nmcli (our assumptions).
* NmcliBackend + real - only with HOTSPOT_HW_TESTS=1 on a Raspberry Pi. This is the one that checks
                        our assumptions about nmcli and NetworkManager against reality.
"""
import os

import pytest

from fakes import FakeBackend, FakeNmcliRunner
from klipper_hotspot.backend import PROFILE_NAME, HotspotSettings, NmcliBackend

HW = os.environ.get("HOTSPOT_HW_TESTS") == "1"


def _settings():
    return HotspotSettings(
        interface=os.environ.get("HOTSPOT_HW_IFACE", "wlan0"),
        ssid="Klipper-TEST",
        password="s3cretpw9x2m",
        band="bg",
        channel=6,
        address="10.42.0.1/24",
    )


@pytest.fixture(
    params=[
        "fake",
        "nmcli-simulated",
        pytest.param("nmcli-real", marks=[pytest.mark.hardware, pytest.mark.skipif(not HW, reason="HOTSPOT_HW_TESTS != 1")]),
    ]
)
def backend(request):
    if request.param == "fake":
        yield FakeBackend()
    elif request.param == "nmcli-simulated":
        yield NmcliBackend(runner=FakeNmcliRunner())
    else:
        real = NmcliBackend()
        yield real
        real.stop_hotspot()  # always leave the Pi the way we found it


def test_start_makes_the_hotspot_active_with_one_profile(backend):
    s = _settings()
    backend.start_hotspot(s)
    info = backend.info(s.interface)
    assert info.active
    assert info.ip == "10.42.0.1"
    assert backend.managed_profiles() == [PROFILE_NAME]


def test_start_is_idempotent(backend):
    s = _settings()
    backend.start_hotspot(s)
    backend.start_hotspot(s)
    assert backend.managed_profiles() == [PROFILE_NAME]
    assert backend.info(s.interface).active


def test_stop_removes_everything(backend):
    s = _settings()
    backend.start_hotspot(s)
    backend.stop_hotspot()
    assert not backend.info(s.interface).active
    assert backend.managed_profiles() == []


def test_stop_when_nothing_is_running_succeeds(backend):
    backend.stop_hotspot()
    backend.stop_hotspot()
    assert backend.managed_profiles() == []


def test_clients_is_unknown_or_a_non_negative_integer(backend):
    s = _settings()
    backend.start_hotspot(s)
    clients = backend.info(s.interface).clients
    assert clients is None or (isinstance(clients, int) and clients >= 0)


def test_no_profile_accumulation_over_many_cycles(backend):
    s = _settings()
    cycles = 50 if not HW else 5  # real radios need time to settle
    for _ in range(cycles):
        backend.start_hotspot(s)
        backend.stop_hotspot()
    backend.start_hotspot(s)
    assert backend.managed_profiles() == [PROFILE_NAME]
    backend.stop_hotspot()
    assert backend.managed_profiles() == []


def test_interface_detection_is_boolean(backend):
    assert isinstance(backend.wifi_interface_present("definitely-not-an-interface"), bool)
    assert backend.wifi_interface_present("definitely-not-an-interface") is False
