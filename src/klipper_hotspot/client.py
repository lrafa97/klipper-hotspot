"""Client for the control socket. Used by the CLI, and therefore by the Klipper macros."""
from __future__ import annotations

import json
import socket
from typing import Any, Dict

from .api import PROTOCOL_VERSION
from .errors import HotspotError

_MAX_RESPONSE_BYTES = 65536


def send_request(socket_path: str, cmd: str, timeout: float = 90.0) -> Dict[str, Any]:
    payload = json.dumps({"v": PROTOCOL_VERSION, "cmd": cmd}).encode("utf-8") + b"\n"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(socket_path)
        sock.sendall(payload)
        buf = b""
        while not buf.endswith(b"\n") and len(buf) < _MAX_RESPONSE_BYTES:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
    except (FileNotFoundError, ConnectionRefusedError):
        raise HotspotError(
            f"the klipper-hotspot daemon is not reachable at {socket_path} "
            "(check: systemctl status klipper-hotspot)",
            code="daemon_unreachable",
        )
    except PermissionError:
        raise HotspotError(
            f"permission denied on {socket_path}; the calling user must be in the socket group",
            code="permission_denied",
        )
    except socket.timeout:
        raise HotspotError("the daemon did not answer in time", code="timeout")
    finally:
        sock.close()

    try:
        response = json.loads(buf.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise HotspotError("invalid response from daemon", code="bad_response")
    if not isinstance(response, dict):
        raise HotspotError("invalid response from daemon", code="bad_response")
    if not response.get("ok"):
        err = response.get("error") or {}
        raise HotspotError(str(err.get("message", "unknown error")), code=str(err.get("code", "error")))
    return response.get("result", {})
