"""Control API: newline-delimited JSON over a Unix socket. Fixed verbs, no free-form arguments."""
from __future__ import annotations

import grp
import json
import logging
import os
import socket
import socketserver
import stat
from pathlib import Path
from typing import Any, Dict, Optional

from .errors import ConfigError, HotspotError, ProtocolError
from .manager import Manager

log = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 4096
VERBS = ("on", "off", "status", "credentials")


def _error(code: str, message: str) -> Dict[str, Any]:
    return {"v": PROTOCOL_VERSION, "ok": False, "error": {"code": code, "message": message}}


def _parse(raw: bytes) -> str:
    if not raw:
        raise ProtocolError("empty request")
    if len(raw) > MAX_REQUEST_BYTES:
        raise ProtocolError("request too large")
    try:
        request = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ProtocolError("invalid JSON")
    if not isinstance(request, dict):
        raise ProtocolError("request must be a JSON object")
    if request.get("v") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol version", code="unsupported_version")
    cmd = request.get("cmd")
    if not isinstance(cmd, str) or cmd not in VERBS:
        raise ProtocolError("unknown command", code="unknown_command")
    # Any other field is ignored on purpose: verbs take no arguments.
    return cmd


def handle_request(manager: Manager, raw: bytes) -> Dict[str, Any]:
    """Pure request -> response. Testable without sockets."""
    try:
        cmd = _parse(raw)
        result = getattr(manager, cmd)()
        return {"v": PROTOCOL_VERSION, "ok": True, "result": result}
    except HotspotError as exc:
        return _error(exc.code, str(exc))
    except Exception:  # noqa: BLE001 - never leak internals to the client
        log.exception("unhandled error while serving a request")
        return _error("internal_error", "internal error")


class _Handler(socketserver.StreamRequestHandler):
    timeout = 5

    def handle(self) -> None:
        try:
            raw = self.rfile.readline(MAX_REQUEST_BYTES + 1)
        except OSError:
            return
        response = handle_request(self.server.manager, raw)  # type: ignore[attr-defined]
        try:
            self.wfile.write(json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n")
        except OSError:
            pass


def _prepare_socket_path(path: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() and not target.is_symlink():
        return
    if not stat.S_ISSOCK(target.lstat().st_mode):
        raise HotspotError(f"{path} exists and is not a socket", code="socket_conflict")
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(1.0)
    try:
        probe.connect(path)
    except OSError:
        target.unlink()  # stale socket from a crashed run
    else:
        raise HotspotError(
            "another klipper-hotspot instance is already listening", code="socket_conflict"
        )
    finally:
        probe.close()


class ControlServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(self, path: str, manager: Manager, group: Optional[str] = None) -> None:
        self.manager = manager
        self._path = path
        self._group = group
        _prepare_socket_path(path)
        super().__init__(path, _Handler)

    def server_bind(self) -> None:
        old_umask = os.umask(0o177)
        try:
            super().server_bind()
        finally:
            os.umask(old_umask)
        try:
            if self._group:
                try:
                    gid = grp.getgrnam(self._group).gr_gid
                except KeyError:
                    raise ConfigError(f"socket group {self._group!r} does not exist")
                os.chown(self._path, -1, gid)
            os.chmod(self._path, 0o660)
        except BaseException:
            try:
                os.unlink(self._path)
            except OSError:
                pass
            raise

    def server_close(self) -> None:
        super().server_close()
        try:
            os.unlink(self._path)
        except OSError:
            pass
