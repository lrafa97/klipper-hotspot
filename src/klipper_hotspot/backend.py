"""Network backends. The rest of the program only knows the NetworkBackend interface."""
from __future__ import annotations

import abc
import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple

from .errors import BackendError

log = logging.getLogger(__name__)

PROFILE_NAME = "klipper-hotspot"

# (argv, timeout_seconds) -> (returncode, stdout, stderr)
Runner = Callable[[Sequence[str], float], Tuple[int, str, str]]


@dataclass(frozen=True, repr=False)
class HotspotSettings:
    interface: str
    ssid: str
    password: str
    band: str
    channel: int
    address: str

    def __repr__(self) -> str:
        return (
            f"HotspotSettings(interface={self.interface!r}, ssid={self.ssid!r}, "
            f"band={self.band!r}, channel={self.channel!r}, address={self.address!r}, "
            "password=***)"
        )


@dataclass(frozen=True)
class HotspotInfo:
    active: bool
    ip: Optional[str] = None
    clients: Optional[int] = None  # None = unknown


class NetworkBackend(abc.ABC):
    """What the manager needs from the network stack. Implementations must be idempotent."""

    @abc.abstractmethod
    def start_hotspot(self, settings: HotspotSettings) -> None:
        """Bring the hotspot up. Calling it again must not leave a second profile behind."""

    @abc.abstractmethod
    def stop_hotspot(self) -> None:
        """Bring the hotspot down and remove its profile. Must succeed if it is already down."""

    @abc.abstractmethod
    def info(self, interface: str) -> HotspotInfo:
        """Live state of the hotspot."""

    @abc.abstractmethod
    def managed_profiles(self) -> List[str]:
        """Names of the profiles this program owns (used by tests and uninstall)."""

    @abc.abstractmethod
    def wifi_interface_present(self, interface: str) -> bool:
        """Whether the given Wi-Fi interface exists."""

    @abc.abstractmethod
    def ap_supported(self, interface: str) -> Optional[bool]:
        """Whether the Wi-Fi interface can act as an access point. None if that cannot be told."""


def redact(text: str, secret: Optional[str]) -> str:
    if secret:
        return text.replace(secret, "***")
    return text


def default_runner(args: Sequence[str], timeout: float) -> Tuple[int, str, str]:
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    try:
        proc = subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except FileNotFoundError:
        raise BackendError(f"{args[0]} not found", code="backend_unavailable")
    except subprocess.TimeoutExpired:
        raise BackendError(f"{args[0]} timed out after {timeout:.0f}s", code="backend_timeout")
    return proc.returncode, proc.stdout, proc.stderr


class NmcliBackend(NetworkBackend):
    """NetworkManager through nmcli. Assumes Raspberry Pi OS Bookworm (NetworkManager)."""

    def __init__(self, runner: Runner = default_runner, profile_name: str = PROFILE_NAME) -> None:
        self._runner = runner
        self._profile = profile_name

    # -- helpers ---------------------------------------------------------------------------

    def _run(
        self,
        args: Sequence[str],
        *,
        timeout: float = 30.0,
        secret: Optional[str] = None,
        check: bool = True,
    ) -> str:
        # The password is on argv for the duration of the call (visible in the process list to
        # local users). Never log argv unredacted.
        log.debug("run: %s", redact(" ".join(args), secret))
        rc, out, err = self._runner(args, timeout)
        if check and rc != 0:
            detail = redact((err or out).strip(), secret)
            raise BackendError(f"{' '.join(args[:3])} failed (exit {rc}): {detail}")
        return out

    def _profile_names(self, *, active_only: bool = False) -> List[str]:
        args = ["nmcli", "-t", "-f", "NAME", "connection", "show"]
        if active_only:
            args.append("--active")
        out = self._run(args)
        return [line.strip() for line in out.splitlines() if line.strip()]

    def _delete_profiles(self) -> None:
        # Loop: if an older run left duplicates, remove every one of them.
        for _ in range(10):
            if self._profile not in self._profile_names():
                return
            self._run(["nmcli", "connection", "delete", "id", self._profile])
        raise BackendError("could not remove all hotspot profiles")

    # -- interface -------------------------------------------------------------------------

    def start_hotspot(self, settings: HotspotSettings) -> None:
        # Seen on a real machine: the Wi-Fi adapter reported AP: no, and nmcli only said "profile is
        # not compatible with device". Say the real reason before touching any profile.
        if self.ap_supported(settings.interface) is False:
            raise BackendError(
                f"{settings.interface} cannot be a hotspot: NetworkManager reports that this Wi-Fi "
                "adapter does not support access point mode (AP: no). Use a Wi-Fi adapter that does.",
                code="ap_unsupported",
            )
        self._delete_profiles()
        add = [
            "nmcli", "connection", "add",
            "type", "wifi",
            "ifname", settings.interface,
            "con-name", self._profile,
            "autoconnect", "no",
            "ssid", settings.ssid,
            "802-11-wireless.mode", "ap",
            "802-11-wireless.band", settings.band,
            "802-11-wireless.channel", str(settings.channel),
            "802-11-wireless-security.key-mgmt", "wpa-psk",
            "802-11-wireless-security.proto", "rsn",
            "802-11-wireless-security.pairwise", "ccmp",
            "802-11-wireless-security.group", "ccmp",
            "802-11-wireless-security.psk", settings.password,
            "ipv4.method", "shared",
            "ipv4.addresses", settings.address,
            "ipv6.method", "ignore",
        ]
        self._run(add, secret=settings.password)
        try:
            self._run(
                ["nmcli", "connection", "up", self._profile, "ifname", settings.interface],
                timeout=45.0,
                secret=settings.password,
            )
        except BackendError:
            # Do not leave a half-working profile behind.
            try:
                self._delete_profiles()
            except BackendError as cleanup_exc:
                log.warning("cleanup after failed start also failed: %s", cleanup_exc)
            raise

    def stop_hotspot(self) -> None:
        # Deleting the profile also deactivates it, and keeps the password out of NetworkManager
        # while the hotspot is off. NetworkManager then autoconnects a known Wi-Fi again.
        self._delete_profiles()

    def info(self, interface: str) -> HotspotInfo:
        if self._profile not in self._profile_names(active_only=True):
            return HotspotInfo(active=False)
        return HotspotInfo(active=True, ip=self._ip(interface), clients=self._clients(interface))

    def managed_profiles(self) -> List[str]:
        return [name for name in self._profile_names() if name == self._profile]

    def wifi_interface_present(self, interface: str) -> bool:
        out = self._run(["nmcli", "-t", "-f", "DEVICE,TYPE", "device", "status"])
        for line in out.splitlines():
            device, _, kind = line.strip().partition(":")
            if device == interface and kind == "wifi":
                return True
        return False

    def ap_supported(self, interface: str) -> Optional[bool]:
        out = self._run(
            ["nmcli", "-g", "WIFI-PROPERTIES.AP", "device", "show", interface], check=False
        ).strip().lower()
        if out == "yes":
            return True
        if out == "no":
            return False
        return None

    def _ip(self, interface: str) -> Optional[str]:
        out = self._run(["nmcli", "-g", "IP4.ADDRESS", "device", "show", interface], check=False)
        for line in out.splitlines():
            value = line.strip()
            if value:
                return value.split("/")[0]
        return None

    def _clients(self, interface: str) -> Optional[int]:
        try:
            rc, out, _ = self._runner(["iw", "dev", interface, "station", "dump"], 10.0)
        except BackendError:
            return None
        if rc != 0:
            return None
        return sum(1 for line in out.splitlines() if line.startswith("Station "))
