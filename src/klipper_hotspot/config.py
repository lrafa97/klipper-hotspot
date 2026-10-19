"""Configuration: one INI file, validated strictly, versioned."""
from __future__ import annotations

import configparser
import ipaddress
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from .errors import ConfigError

SUPPORTED_CONFIG_VERSION = 1
DEFAULT_CONFIG_PATH = "/etc/klipper-hotspot/hotspot.conf"

# Sections reserved for future features. They are part of the schema so a config
# written for a later version is recognised, but enabling them now is an error
# rather than a silent no-op.
RESERVED_SECTIONS = ("fallback", "portal")

_KNOWN_KEYS = {
    "general": {"config_version", "autostart"},
    "hotspot": {"interface", "ssid_prefix", "band", "channel", "address"},
    "paths": {"socket", "socket_group", "state_file", "credentials_file"},
    "integration": {"moonraker_conf", "moonraker_url"},
    "fallback": {"enabled"},
    "portal": {"enabled"},
}

_IFACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,14}$")
_PREFIX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,23}$")
_GROUP_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,31}$")
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


@dataclass(frozen=True)
class Config:
    config_version: int = 1
    autostart: bool = False
    interface: str = "wlan0"
    ssid_prefix: str = "Klipper"
    band: str = "bg"
    channel: int = 6
    address: str = "10.42.0.1/24"
    socket_path: str = "/run/klipper-hotspot/control.sock"
    socket_group: str = ""
    state_file: str = "/var/lib/klipper-hotspot/state.json"
    credentials_file: str = "/etc/klipper-hotspot/credentials"
    moonraker_conf: str = ""
    moonraker_url: str = "http://127.0.0.1:7125"
    warnings: Tuple[str, ...] = ()

    @property
    def ip(self) -> str:
        return str(ipaddress.ip_interface(self.address).ip)

    @property
    def network(self) -> ipaddress.IPv4Network:
        return ipaddress.ip_interface(self.address).network  # type: ignore[return-value]


def _get_int(parser: configparser.ConfigParser, section: str, key: str, default: int) -> int:
    raw = parser.get(section, key, fallback=None)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError:
        raise ConfigError(f"[{section}] {key} must be an integer, got {raw!r}")


def _get_bool(parser: configparser.ConfigParser, section: str, key: str, default: bool) -> bool:
    try:
        return parser.getboolean(section, key, fallback=default)
    except ValueError:
        raise ConfigError(f"[{section}] {key} must be true or false")


def _get_str(parser: configparser.ConfigParser, section: str, key: str, default: str) -> str:
    raw = parser.get(section, key, fallback=None)
    if raw is None:
        return default
    return raw.strip()


def _validate_moonraker_url(raw: str) -> str:
    message = "[integration] moonraker_url must look like http://127.0.0.1:7125 (this machine only)"
    try:
        parts = urllib.parse.urlsplit(raw)
        parts.port  # raises ValueError on a bad port
    except ValueError:
        raise ConfigError(message)
    if (
        parts.scheme != "http"
        or parts.hostname not in _LOOPBACK_HOSTS
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
        or parts.username
        or parts.password
    ):
        raise ConfigError(message)
    return raw.rstrip("/")


def parse_config(text: str) -> Config:
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(text)
    except configparser.Error as exc:
        raise ConfigError(f"cannot parse config: {exc}")

    warnings = []
    for section in parser.sections():
        known = _KNOWN_KEYS.get(section)
        if known is None:
            warnings.append(f"unknown section [{section}] ignored")
            continue
        for key in parser[section]:
            if key not in known:
                warnings.append(f"unknown key '{key}' in [{section}] ignored")

    version = _get_int(parser, "general", "config_version", 1)
    if version < 1:
        raise ConfigError("[general] config_version must be 1 or higher")
    if version > SUPPORTED_CONFIG_VERSION:
        raise ConfigError(
            f"config_version {version} is newer than this program supports "
            f"({SUPPORTED_CONFIG_VERSION}); update klipper-hotspot"
        )

    for section in RESERVED_SECTIONS:
        if _get_bool(parser, section, "enabled", False):
            raise ConfigError(
                f"[{section}] is not implemented in this version; set enabled = false"
            )

    defaults = Config()
    interface = _get_str(parser, "hotspot", "interface", defaults.interface)
    if not _IFACE_RE.match(interface):
        raise ConfigError(f"[hotspot] interface {interface!r} is not a valid interface name")

    prefix = _get_str(parser, "hotspot", "ssid_prefix", defaults.ssid_prefix)
    if not _PREFIX_RE.match(prefix):
        raise ConfigError(
            "[hotspot] ssid_prefix must be 1-24 characters: letters, digits, '-' or '_'"
        )

    band = _get_str(parser, "hotspot", "band", defaults.band)
    if band != "bg":
        raise ConfigError("[hotspot] band must be 'bg' (2.4 GHz) in this version")

    channel = _get_int(parser, "hotspot", "channel", defaults.channel)
    if not 1 <= channel <= 13:
        raise ConfigError("[hotspot] channel must be between 1 and 13")

    address = _get_str(parser, "hotspot", "address", defaults.address)
    try:
        iface_addr = ipaddress.IPv4Interface(address)
    except ValueError:
        raise ConfigError(f"[hotspot] address {address!r} is not a valid IPv4 address/prefix")
    if not iface_addr.ip.is_private:
        raise ConfigError("[hotspot] address must be a private (RFC 1918) address")
    if iface_addr.network.prefixlen > 30:
        raise ConfigError("[hotspot] address prefix must be /30 or wider")

    group = _get_str(parser, "paths", "socket_group", defaults.socket_group)
    if group and not _GROUP_RE.match(group):
        raise ConfigError(f"[paths] socket_group {group!r} is not a valid group name")

    return Config(
        config_version=version,
        autostart=_get_bool(parser, "general", "autostart", defaults.autostart),
        interface=interface,
        ssid_prefix=prefix,
        band=band,
        channel=channel,
        address=address,
        socket_path=_get_str(parser, "paths", "socket", defaults.socket_path),
        socket_group=group,
        state_file=_get_str(parser, "paths", "state_file", defaults.state_file),
        credentials_file=_get_str(parser, "paths", "credentials_file", defaults.credentials_file),
        moonraker_conf=_get_str(parser, "integration", "moonraker_conf", defaults.moonraker_conf),
        moonraker_url=_validate_moonraker_url(
            _get_str(parser, "integration", "moonraker_url", defaults.moonraker_url)
        ),
        warnings=tuple(warnings),
    )


def load_config(path: Optional[str] = None) -> Config:
    """Load the config file. A missing default file means defaults; a missing explicit file is an error."""
    if path is None:
        candidate = Path(DEFAULT_CONFIG_PATH)
        if not candidate.exists():
            return parse_config("")
        path = str(candidate)
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc.strerror or exc}")
    return parse_config(text)
