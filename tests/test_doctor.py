import ipaddress

import pytest

from fakes import FakeBackend
from klipper_hotspot.config import Config
from klipper_hotspot.credentials import create_credentials
from klipper_hotspot.doctor import FAIL, OK, WARN, run_checks, trusted_clients_cover

NET = ipaddress.ip_network("10.42.0.0/24")

MAINSAIL_DEFAULT = """
[server]
host: 0.0.0.0

[authorization]
trusted_clients:
    10.0.0.0/8
    127.0.0.0/8
    169.254.0.0/16
    172.16.0.0/12
    192.168.0.0/16
    FE80::/10
    ::1/128
cors_domains:
    *.local
"""


def test_default_mainsail_trusted_clients_already_cover_the_hotspot_subnet():
    # 10.42.0.0/24 sits inside 10.0.0.0/8, which MainsailOS trusts by default.
    assert trusted_clients_cover(MAINSAIL_DEFAULT, NET) is True


def test_custom_trusted_clients_that_exclude_the_subnet_are_flagged():
    text = "[authorization]\ntrusted_clients:\n    192.168.1.0/24\n    127.0.0.1\n"
    assert trusted_clients_cover(text, NET) is False


def test_missing_authorization_section_is_unknown_not_a_verdict():
    assert trusted_clients_cover("[server]\nhost: 0.0.0.0\n", NET) is None


def test_comments_and_hostnames_do_not_break_parsing():
    text = "[authorization]\ntrusted_clients:\n    # lan\n    *.local\n    10.42.0.0/16  # hotspot\n"
    assert trusted_clients_cover(text, NET) is True


def test_unparseable_file_is_unknown():
    assert trusted_clients_cover("this is [not valid\n", NET) is None


@pytest.fixture
def healthy(tmp_path):
    creds = tmp_path / "credentials"
    create_credentials(str(creds), "Klipper")
    moonraker = tmp_path / "moonraker.conf"
    moonraker.write_text(MAINSAIL_DEFAULT)
    return Config(
        credentials_file=str(creds),
        moonraker_conf=str(moonraker),
        socket_path=str(tmp_path / "none.sock"),
    )


def by_name(checks):
    return {c.name: c for c in checks}


def test_healthy_setup_has_no_failures(healthy):
    checks = by_name(run_checks(healthy, FakeBackend()))
    assert checks["wifi interface"].level == OK
    assert checks["credentials"].level == OK
    assert checks["moonraker trusted_clients"].level == OK
    assert checks["daemon"].level == WARN  # nothing is listening in this test
    assert not any(c.level == FAIL for c in checks.values())


def test_missing_wifi_interface_fails(healthy):
    cfg = Config(**{**healthy.__dict__, "interface": "wlan7"})
    assert by_name(run_checks(cfg, FakeBackend()))["wifi interface"].level == FAIL


def test_missing_credentials_fail(healthy, tmp_path):
    cfg = Config(**{**healthy.__dict__, "credentials_file": str(tmp_path / "nope")})
    assert by_name(run_checks(cfg, FakeBackend()))["credentials"].level == FAIL


def test_untrusted_subnet_fails(healthy, tmp_path):
    bad = tmp_path / "bad.conf"
    bad.write_text("[authorization]\ntrusted_clients:\n    192.168.1.0/24\n")
    cfg = Config(**{**healthy.__dict__, "moonraker_conf": str(bad)})
    assert by_name(run_checks(cfg, FakeBackend()))["moonraker trusted_clients"].level == FAIL


def test_unset_moonraker_path_warns(healthy):
    cfg = Config(**{**healthy.__dict__, "moonraker_conf": ""})
    assert by_name(run_checks(cfg, FakeBackend()))["moonraker trusted_clients"].level == WARN


def test_respond_module_found_in_an_included_file(healthy, tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "mainsail.cfg").write_text("[virtual_sdcard]\npath: x\n\n[respond]\n")
    assert by_name(run_checks(healthy, FakeBackend()))["klipper respond module"].level == OK


def test_respond_module_missing_warns_with_the_fix(healthy, tmp_path):
    (tmp_path / "printer.cfg").write_text("[mcu]\nserial: x\n")
    check = by_name(run_checks(healthy, FakeBackend()))["klipper respond module"]
    assert check.level == WARN and "[respond]" in check.detail


def test_a_commented_out_respond_section_does_not_count(healthy, tmp_path):
    (tmp_path / "printer.cfg").write_text("#[respond]\n")
    assert by_name(run_checks(healthy, FakeBackend()))["klipper respond module"].level == WARN
