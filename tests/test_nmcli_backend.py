import pytest

from fakes import FakeNmcliRunner
from klipper_hotspot.backend import PROFILE_NAME, HotspotSettings, NmcliBackend
from klipper_hotspot.errors import BackendError

SECRET = "s3cretpw9x2m"


@pytest.fixture
def settings():
    return HotspotSettings(
        interface="wlan0", ssid="Klipper-ABCD", password=SECRET, band="bg", channel=6,
        address="10.42.0.1/24",
    )


@pytest.fixture
def runner():
    return FakeNmcliRunner()


@pytest.fixture
def nm(runner):
    return NmcliBackend(runner=runner)


def add_call(runner):
    return next(c for c in runner.calls if c[:3] == ["nmcli", "connection", "add"])


def pairs(argv):
    """Option/value pairs after 'add', so assertions do not depend on order."""
    rest = argv[3:]
    return dict(zip(rest[::2], rest[1::2]))


def test_profile_is_built_as_a_wpa2_shared_ap_that_never_autoconnects(nm, runner, settings):
    nm.start_hotspot(settings)
    opts = pairs(add_call(runner))
    assert opts["type"] == "wifi"
    assert opts["ifname"] == "wlan0"
    assert opts["con-name"] == PROFILE_NAME
    assert opts["autoconnect"] == "no"  # a reboot must not bring the hotspot back by itself
    assert opts["ssid"] == "Klipper-ABCD"
    assert opts["802-11-wireless.mode"] == "ap"
    assert opts["802-11-wireless.band"] == "bg"
    assert opts["802-11-wireless.channel"] == "6"
    assert opts["802-11-wireless-security.key-mgmt"] == "wpa-psk"
    assert opts["802-11-wireless-security.proto"] == "rsn"
    assert opts["ipv4.method"] == "shared"
    assert opts["ipv4.addresses"] == "10.42.0.1/24"
    assert opts["802-11-wireless-security.psk"] == SECRET


def test_start_activates_the_profile_on_the_interface(nm, runner, settings):
    nm.start_hotspot(settings)
    assert ["nmcli", "connection", "up", PROFILE_NAME, "ifname", "wlan0"] in runner.calls
    assert PROFILE_NAME in runner.active


def test_start_twice_never_leaves_duplicate_profiles(nm, runner, settings):
    nm.start_hotspot(settings)
    nm.start_hotspot(settings)
    assert runner.profiles == [PROFILE_NAME]


def test_start_cleans_up_duplicates_left_by_older_runs(nm, runner, settings):
    runner.profiles = [PROFILE_NAME, PROFILE_NAME, "HomeWifi"]
    nm.start_hotspot(settings)
    assert runner.profiles.count(PROFILE_NAME) == 1
    assert "HomeWifi" in runner.profiles  # never touches profiles that are not ours


def test_failed_activation_removes_the_profile_and_redacts_the_password(nm, runner, settings):
    runner.fail_up = True
    with pytest.raises(BackendError) as excinfo:
        nm.start_hotspot(settings)
    assert runner.profiles == []
    assert SECRET not in str(excinfo.value)


def test_a_password_echoed_back_by_nmcli_is_redacted_from_errors(settings):
    # Some tools echo the offending argument in their error text. Prove we scrub it.
    def echoing_runner(args, timeout):
        if args[:3] == ["nmcli", "connection", "add"]:
            return 2, "", f"Error: invalid psk '{SECRET}'"
        return 0, "", ""

    with pytest.raises(BackendError) as excinfo:
        NmcliBackend(runner=echoing_runner).start_hotspot(settings)
    assert SECRET not in str(excinfo.value)
    assert "***" in str(excinfo.value)


def test_debug_logging_of_commands_never_contains_the_password(nm, settings, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    nm.start_hotspot(settings)
    nm.stop_hotspot()
    assert "nmcli" in caplog.text  # commands are logged...
    assert SECRET not in caplog.text  # ...but never the secret


def test_stop_removes_the_profile_and_is_idempotent(nm, runner, settings):
    nm.start_hotspot(settings)
    nm.stop_hotspot()
    nm.stop_hotspot()
    assert runner.profiles == []
    assert not nm.info("wlan0").active


def test_stop_never_touches_other_profiles(nm, runner, settings):
    runner.profiles = ["HomeWifi"]
    nm.start_hotspot(settings)
    nm.stop_hotspot()
    assert runner.profiles == ["HomeWifi"]


def test_info_reports_ip_and_client_count(nm, runner, settings):
    runner.clients = 2
    nm.start_hotspot(settings)
    info = nm.info("wlan0")
    assert info.active and info.ip == "10.42.0.1" and info.clients == 2


def test_missing_iw_means_unknown_clients_not_an_error(settings):
    runner = FakeNmcliRunner(has_iw=False)
    nm = NmcliBackend(runner=runner)
    nm.start_hotspot(settings)
    info = nm.info("wlan0")
    assert info.active and info.clients is None


def test_missing_nmcli_is_a_clear_backend_error(settings):
    runner = FakeNmcliRunner()
    runner.nmcli_missing = True
    with pytest.raises(BackendError) as excinfo:
        NmcliBackend(runner=runner).start_hotspot(settings)
    assert excinfo.value.code == "backend_unavailable"


def test_wifi_interface_detection(nm):
    assert nm.wifi_interface_present("wlan0") is True
    assert nm.wifi_interface_present("wlan9") is False
    assert nm.wifi_interface_present("eth0") is False  # exists, but is not Wi-Fi


def test_arguments_are_always_passed_as_a_list_never_a_shell_string(nm, runner, settings):
    nm.start_hotspot(settings)
    assert all(isinstance(c, list) for c in runner.calls)
