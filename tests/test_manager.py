import logging

import pytest

from conftest import PASSWORD
from klipper_hotspot.errors import BackendError


def test_on_starts_hotspot_and_persists(backend, make_manager):
    manager, store = make_manager(backend, clock=lambda: 1000.0)
    status = manager.on()
    assert status["state"] == "on"
    assert status["ip"] == "10.42.0.1"
    assert status["ssid"] == "Klipper-TEST"
    assert status["since"] == 1000
    assert backend.last_settings.password == PASSWORD
    saved = store.load()
    assert saved.desired == "on" and saved.since == 1000.0


def test_on_is_idempotent_and_does_not_restart_the_access_point(backend, make_manager):
    manager, _ = make_manager(backend)
    manager.on()
    manager.on()
    manager.on()
    assert backend.start_calls == 1  # restarting would drop every connected client


def test_off_stops_hotspot_and_persists(backend, make_manager):
    manager, store = make_manager(backend)
    manager.on()
    status = manager.off()
    assert status["state"] == "off"
    assert status["since"] is None
    assert backend.managed_profiles() == []
    assert store.load().desired == "off"


def test_off_when_already_off_is_fine(backend, make_manager):
    manager, _ = make_manager(backend)
    assert manager.off()["state"] == "off"
    assert manager.off()["state"] == "off"


def test_status_never_contains_the_password(backend, make_manager):
    manager, _ = make_manager(backend)
    manager.on()
    assert PASSWORD not in str(manager.status())
    assert "password" not in manager.status()


def test_credentials_verb_returns_the_password(backend, make_manager):
    manager, _ = make_manager(backend)
    assert manager.credentials() == {"ssid": "Klipper-TEST", "password": PASSWORD}


def test_failed_start_reports_error_and_stays_off(backend, make_manager):
    backend.fail_start = True
    manager, _ = make_manager(backend)
    with pytest.raises(BackendError):
        manager.on()
    status = manager.status()
    assert status["state"] == "off"
    assert "simulated start failure" in status["last_error"]


def test_error_clears_after_a_successful_operation(backend, make_manager):
    backend.fail_start = True
    manager, _ = make_manager(backend)
    with pytest.raises(BackendError):
        manager.on()
    backend.fail_start = False
    assert manager.on()["last_error"] is None


def test_failed_stop_keeps_the_state_truthful(backend, make_manager):
    manager, _ = make_manager(backend)
    manager.on()
    backend.fail_stop = True
    with pytest.raises(BackendError):
        manager.off()
    assert manager.status()["state"] == "on"  # it really is still on


def test_external_changes_are_detected(backend, make_manager):
    manager, _ = make_manager(backend)
    manager.on()
    backend.active = False  # someone ran nmcli by hand
    assert manager.status()["state"] == "off"
    backend.active = True
    assert manager.status()["state"] == "on"


def test_status_reports_client_count_when_known(backend, make_manager):
    backend.clients = 3
    manager, _ = make_manager(backend)
    assert manager.on()["clients"] == 3


# -- reconcile (daemon start) ---------------------------------------------------------------


def test_reconcile_adopts_an_active_hotspot_and_keeps_its_start_time(backend, make_manager):
    first, store = make_manager(backend, clock=lambda: 500.0)
    first.on()
    second, _ = make_manager(backend, clock=lambda: 9999.0)  # daemon restarted
    second.reconcile()
    status = second.status()
    assert status["state"] == "on"
    assert status["since"] == 500
    assert backend.start_calls == 1


def test_reconcile_with_autostart_off_leaves_hotspot_off(backend, make_manager):
    manager, store = make_manager(backend, autostart=False)
    manager.reconcile()
    assert backend.start_calls == 0
    assert manager.status()["state"] == "off"
    assert store.load().desired == "off"


def test_reconcile_with_autostart_on_starts_it(backend, make_manager):
    manager, _ = make_manager(backend, autostart=True)
    manager.reconcile()
    assert backend.start_calls == 1
    assert manager.status()["state"] == "on"


def test_autostart_failure_does_not_crash_the_daemon(backend, make_manager):
    backend.fail_start = True
    manager, _ = make_manager(backend, autostart=True)
    manager.reconcile()  # must not raise
    assert manager.status()["state"] == "off"


def test_reconcile_survives_an_unreadable_network_stack(backend, make_manager):
    backend.fail_info = True
    manager, _ = make_manager(backend, autostart=True)
    manager.reconcile()  # must not raise


def test_stale_on_in_store_does_not_resurrect_the_hotspot_after_reboot(backend, make_manager):
    first, store = make_manager(backend)
    first.on()
    backend.active = False  # reboot: the profile does not autoconnect
    backend.profiles = []
    second, _ = make_manager(backend, autostart=False)
    second.reconcile()
    assert second.status()["state"] == "off"
    assert store.load().desired == "off"


# -- secrets ---------------------------------------------------------------------------------


def test_password_never_appears_in_logs(backend, make_manager, caplog):
    caplog.set_level(logging.DEBUG)
    manager, _ = make_manager(backend)
    manager.on()
    manager.status()
    manager.off()
    backend.fail_start = True
    with pytest.raises(BackendError):
        manager.on()
    assert PASSWORD not in caplog.text
