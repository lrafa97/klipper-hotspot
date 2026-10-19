from pathlib import Path

import pytest

from klipper_hotspot.config import SUPPORTED_CONFIG_VERSION, load_config, parse_config
from klipper_hotspot.errors import ConfigError


def test_empty_config_gives_safe_defaults():
    cfg = parse_config("")
    assert cfg.autostart is False
    assert cfg.interface == "wlan0"
    assert cfg.band == "bg"
    assert cfg.ip == "10.42.0.1"
    assert str(cfg.network) == "10.42.0.0/24"
    assert cfg.warnings == ()


def test_full_config_is_parsed():
    cfg = parse_config(
        "[general]\nautostart = true\n[hotspot]\ninterface = wlan1\nssid_prefix = Acme\n"
        "channel = 11\naddress = 192.168.50.1/24\n[paths]\nsocket_group = pi\n"
    )
    assert cfg.autostart is True
    assert cfg.interface == "wlan1"
    assert cfg.ssid_prefix == "Acme"
    assert cfg.channel == 11
    assert cfg.socket_group == "pi"


def test_unknown_keys_and_sections_warn_but_do_not_fail():
    cfg = parse_config("[general]\nfuture_key = 1\n[brand_new]\nx = 1\n")
    assert any("future_key" in w for w in cfg.warnings)
    assert any("brand_new" in w for w in cfg.warnings)


@pytest.mark.parametrize("section", ["fallback", "portal"])
def test_reserved_sections_cannot_be_enabled_yet(section):
    with pytest.raises(ConfigError, match="not implemented"):
        parse_config(f"[{section}]\nenabled = true\n")


def test_reserved_sections_may_exist_disabled():
    parse_config("[fallback]\nenabled = false\n[portal]\nenabled = false\n")


def test_newer_config_version_is_refused_with_clear_message():
    with pytest.raises(ConfigError, match="newer"):
        parse_config(f"[general]\nconfig_version = {SUPPORTED_CONFIG_VERSION + 1}\n")


@pytest.mark.parametrize(
    "text",
    [
        "[hotspot]\nband = a\n",
        "[hotspot]\nchannel = 14\n",
        "[hotspot]\nchannel = abc\n",
        "[hotspot]\naddress = 8.8.8.8/24\n",
        "[hotspot]\naddress = not-an-ip\n",
        "[hotspot]\naddress = 10.42.0.1/31\n",
        "[hotspot]\ninterface = -evil\n",
        "[hotspot]\ninterface = wlan0; reboot\n",
        "[hotspot]\nssid_prefix = " + "x" * 25 + "\n",
        "[hotspot]\nssid_prefix = bad prefix\n",
        "[general]\nautostart = maybe\n",
        "[paths]\nsocket_group = bad group\n",
        "this is not ini",
    ],
)
def test_invalid_values_are_rejected(text):
    with pytest.raises(ConfigError):
        parse_config(text)


def test_missing_default_file_means_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr("klipper_hotspot.config.DEFAULT_CONFIG_PATH", str(tmp_path / "none.conf"))
    assert load_config(None).interface == "wlan0"


def test_missing_explicit_file_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(str(tmp_path / "none.conf"))


def test_shipped_example_config_stays_valid():
    example = Path(__file__).resolve().parent.parent / "data" / "hotspot.conf.example"
    text = example.read_text().replace("@SOCKET_GROUP@", "pi").replace(
        "@MOONRAKER_CONF@", "/home/pi/printer_data/config/moonraker.conf"
    )
    cfg = parse_config(text)
    assert cfg.warnings == ()
    assert cfg.autostart is False  # decision: the hotspot is a mode, off by default
