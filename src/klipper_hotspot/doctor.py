"""Read-only health checks. Run after install and whenever something looks wrong."""
from __future__ import annotations

import configparser
import ipaddress
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .backend import NetworkBackend
from .client import send_request
from .config import Config
from .credentials import load_credentials
from .errors import BackendError, CredentialsError, HotspotError

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass(frozen=True)
class Check:
    name: str
    level: str
    detail: str


def trusted_clients_cover(conf_text: str, network: ipaddress.IPv4Network) -> Optional[bool]:
    """True/False if moonraker.conf's trusted_clients covers the network, None if it cannot tell."""
    parser = configparser.ConfigParser(
        strict=False, interpolation=None, allow_no_value=True, inline_comment_prefixes=("#", ";")
    )
    try:
        parser.read_string(conf_text)
    except configparser.Error:
        return None
    raw = parser.get("authorization", "trusted_clients", fallback=None)
    if raw is None:
        return None
    for token in raw.replace(",", "\n").splitlines():
        token = token.strip()
        if not token:
            continue
        try:
            candidate = ipaddress.ip_network(token, strict=False)
        except ValueError:
            continue  # hostnames or wildcards: cannot reason about them
        if candidate.version == network.version and network.subnet_of(candidate):  # type: ignore[arg-type]
            return True
    return False


def _check_moonraker(config: Config) -> Check:
    name = "moonraker trusted_clients"
    path = config.moonraker_conf
    if not path:
        return Check(name, WARN, "no [integration] moonraker_conf set; cannot verify")
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return Check(name, WARN, f"cannot read {path}: {exc.strerror or exc}")
    verdict = trusted_clients_cover(text, config.network)
    if verdict is None:
        return Check(
            name, WARN,
            f"could not determine; make sure {config.network} is trusted in {path} "
            "or Mainsail will not connect over the hotspot",
        )
    if verdict:
        return Check(name, OK, f"{config.network} is trusted")
    return Check(
        name, FAIL,
        f"{config.network} is NOT in trusted_clients ({path}); Mainsail will not connect over the hotspot",
    )


def run_checks(config: Config, backend: NetworkBackend) -> List[Check]:
    checks: List[Check] = []

    try:
        present = backend.wifi_interface_present(config.interface)
        checks.append(
            Check("wifi interface", OK if present else FAIL,
                  f"{config.interface} found" if present else f"{config.interface} not found")
        )
    except BackendError as exc:
        checks.append(Check("networkmanager", FAIL, str(exc)))

    try:
        creds = load_credentials(config.credentials_file)
        checks.append(Check("credentials", OK, f"SSID {creds.ssid}"))
    except CredentialsError as exc:
        checks.append(Check("credentials", FAIL, str(exc)))

    try:
        send_request(config.socket_path, "status", timeout=3.0)
        checks.append(Check("daemon", OK, "reachable"))
    except HotspotError as exc:
        checks.append(Check("daemon", WARN, str(exc)))

    checks.append(_check_moonraker(config))
    return checks
