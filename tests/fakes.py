"""Test doubles: a fake NetworkBackend and a simulated nmcli."""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from klipper_hotspot.backend import HotspotInfo, HotspotSettings, NetworkBackend, PROFILE_NAME
from klipper_hotspot.errors import BackendError


class FakeBackend(NetworkBackend):
    def __init__(self) -> None:
        self.profiles: List[str] = []
        self.active = False
        self.clients: Optional[int] = 0
        self.fail_start = False
        self.fail_stop = False
        self.fail_info = False
        self.start_calls = 0
        self.stop_calls = 0
        self.last_settings: Optional[HotspotSettings] = None
        self._address = "10.42.0.1/24"

    def start_hotspot(self, settings: HotspotSettings) -> None:
        self.start_calls += 1
        if self.fail_start:
            raise BackendError("simulated start failure")
        self.last_settings = settings
        self._address = settings.address
        self.profiles = [PROFILE_NAME]
        self.active = True

    def stop_hotspot(self) -> None:
        self.stop_calls += 1
        if self.fail_stop:
            raise BackendError("simulated stop failure")
        self.profiles = []
        self.active = False

    def info(self, interface: str) -> HotspotInfo:
        if self.fail_info:
            raise BackendError("simulated info failure")
        if not self.active:
            return HotspotInfo(active=False)
        return HotspotInfo(active=True, ip=self._address.split("/")[0], clients=self.clients)

    def managed_profiles(self) -> List[str]:
        return list(self.profiles)

    def wifi_interface_present(self, interface: str) -> bool:
        return interface == "wlan0"


class FakeNmcliRunner:
    """Simulates just enough nmcli/iw for NmcliBackend. Encodes OUR assumptions about nmcli output;
    the hardware-gated contract tests are what check those assumptions against the real thing."""

    def __init__(self, interface: str = "wlan0", has_iw: bool = True) -> None:
        self.interface = interface
        self.has_iw = has_iw
        self.profiles: List[str] = []
        self.active: set = set()
        self.address = "10.42.0.1/24"
        self.fail_up = False
        self.nmcli_missing = False
        self.clients = 0
        self.calls: List[List[str]] = []

    def __call__(self, args: Sequence[str], timeout: float) -> Tuple[int, str, str]:
        a = list(args)
        self.calls.append(a)
        if a[0] == "nmcli" and self.nmcli_missing:
            raise BackendError("nmcli not found", code="backend_unavailable")
        if a[0] == "iw":
            if not self.has_iw:
                raise BackendError("iw not found", code="backend_unavailable")
            if not self.active:
                return 237, "", "command failed: No such device (-19)"
            rows = "".join(f"Station aa:bb:cc:dd:ee:{i:02x} (on {self.interface})\n\tinactive time: 10 ms\n"
                           for i in range(self.clients))
            return 0, rows, ""
        if a[:5] == ["nmcli", "-t", "-f", "NAME", "connection"] and a[5] == "show":
            names = self.profiles if "--active" not in a else [p for p in self.profiles if p in self.active]
            return 0, "".join(f"{n}\n" for n in names), ""
        if a[:2] == ["nmcli", "connection"] and a[2] == "add":
            name = a[a.index("con-name") + 1]
            self.address = a[a.index("ipv4.addresses") + 1]
            self.profiles.append(name)
            return 0, f"Connection '{name}' (uuid) successfully added.\n", ""
        if a[:3] == ["nmcli", "connection", "up"]:
            name = a[3]
            if self.fail_up:
                return 4, "", "Error: Connection activation failed: simulated"
            if name not in self.profiles:
                return 10, "", f"Error: unknown connection '{name}'."
            self.active.add(name)
            return 0, "Connection successfully activated\n", ""
        if a[:4] == ["nmcli", "connection", "delete", "id"]:
            name = a[4]
            if name not in self.profiles:
                return 10, "", f"Error: unknown connection '{name}'."
            self.profiles.remove(name)
            if name not in self.profiles:
                self.active.discard(name)
            return 0, f"Connection '{name}' successfully deleted.\n", ""
        if a[:5] == ["nmcli", "-t", "-f", "DEVICE,TYPE", "device"]:
            return 0, f"{self.interface}:wifi\neth0:ethernet\nlo:loopback\n", ""
        if a[:4] == ["nmcli", "-g", "IP4.ADDRESS", "device"]:
            return (0, f"{self.address}\n", "") if self.active else (0, "", "")
        return 2, "", f"simulator: unsupported command {a}"


class FakeMoonraker:
    """A tiny HTTP server that records the G-code scripts POSTed to /printer/gcode/script."""

    def __init__(self) -> None:
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        outer = self
        self.scripts: List[str] = []
        self.paths: List[str] = []
        self.status = 200

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                outer.paths.append(self.path)
                if outer.status == 200:
                    outer.scripts.append(body.get("script", ""))
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"result": "ok"}')

            def log_message(self, *args):  # silence
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
