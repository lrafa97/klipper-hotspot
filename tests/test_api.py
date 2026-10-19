import json
import os
import socket
import threading

import pytest

from conftest import PASSWORD
from klipper_hotspot.api import MAX_REQUEST_BYTES, ControlServer, handle_request
from klipper_hotspot.client import send_request
from klipper_hotspot.errors import HotspotError


def req(cmd="status", **extra):
    return json.dumps({"v": 1, "cmd": cmd, **extra}).encode() + b"\n"


# -- pure request handling ---------------------------------------------------------------------


def test_status_roundtrip(backend, make_manager):
    manager, _ = make_manager(backend)
    resp = handle_request(manager, req("status"))
    assert resp["ok"] is True and resp["v"] == 1
    assert resp["result"]["state"] == "off"


def test_on_and_off(backend, make_manager):
    manager, _ = make_manager(backend)
    assert handle_request(manager, req("on"))["result"]["state"] == "on"
    assert handle_request(manager, req("off"))["result"]["state"] == "off"


def test_extra_fields_are_ignored_never_executed(backend, make_manager):
    manager, _ = make_manager(backend)
    resp = handle_request(manager, req("status", argv=["rm", "-rf", "/"], ssid="evil", password="x"))
    assert resp["ok"] is True
    assert backend.start_calls == 0


@pytest.mark.parametrize(
    "raw, code",
    [
        (b"", "bad_request"),
        (b"not json\n", "bad_request"),
        (b"[1,2,3]\n", "bad_request"),
        (b'{"v": 2, "cmd": "status"}\n', "unsupported_version"),
        (b'{"cmd": "status"}\n', "unsupported_version"),
        (b'{"v": 1, "cmd": "reboot"}\n', "unknown_command"),
        (b'{"v": 1, "cmd": 5}\n', "unknown_command"),
        (b'{"v": 1}\n', "unknown_command"),
        (b"x" * (MAX_REQUEST_BYTES + 1), "bad_request"),
    ],
)
def test_bad_requests_get_a_stable_error_code(backend, make_manager, raw, code):
    manager, _ = make_manager(backend)
    resp = handle_request(manager, raw)
    assert resp["ok"] is False
    assert resp["error"]["code"] == code


def test_backend_failure_becomes_an_error_response(backend, make_manager):
    backend.fail_start = True
    manager, _ = make_manager(backend)
    resp = handle_request(manager, req("on"))
    assert resp["ok"] is False
    assert resp["error"]["code"] == "backend_error"


def test_unexpected_exceptions_do_not_leak_details(backend, make_manager, monkeypatch):
    manager, _ = make_manager(backend)

    def boom():
        raise RuntimeError("secret internal detail /etc/shadow")

    monkeypatch.setattr(manager, "status", boom)
    resp = handle_request(manager, req("status"))
    assert resp["error"] == {"code": "internal_error", "message": "internal error"}


def test_status_response_has_no_password_but_credentials_verb_does(backend, make_manager):
    manager, _ = make_manager(backend)
    assert PASSWORD not in json.dumps(handle_request(manager, req("status")))
    assert handle_request(manager, req("credentials"))["result"]["password"] == PASSWORD


# -- over a real Unix socket ---------------------------------------------------------------------


@pytest.fixture
def server(backend, make_manager, tmp_path):
    manager, _ = make_manager(backend)
    path = str(tmp_path / "c.sock")
    srv = ControlServer(path, manager)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield path
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def test_client_server_roundtrip(server):
    assert send_request(server, "status", timeout=5)["state"] == "off"
    assert send_request(server, "on", timeout=5)["state"] == "on"
    assert send_request(server, "off", timeout=5)["state"] == "off"


def test_client_surfaces_server_errors_with_code(server, backend):
    backend.fail_start = True
    with pytest.raises(HotspotError) as excinfo:
        send_request(server, "on", timeout=5)
    assert excinfo.value.code == "backend_error"


def test_socket_is_not_world_accessible(server):
    mode = os.stat(server).st_mode & 0o777
    assert mode == 0o660


def test_oversized_request_is_rejected_over_the_socket(server):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(5)
    sock.connect(server)
    sock.sendall(b"x" * (MAX_REQUEST_BYTES + 100) + b"\n")
    data = b""
    while not data.endswith(b"\n"):
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    sock.close()
    assert json.loads(data)["error"]["code"] == "bad_request"


def test_client_reports_missing_daemon_clearly(tmp_path):
    with pytest.raises(HotspotError) as excinfo:
        send_request(str(tmp_path / "missing.sock"), "status", timeout=1)
    assert excinfo.value.code == "daemon_unreachable"


def test_stale_socket_file_is_replaced(backend, make_manager, tmp_path):
    path = str(tmp_path / "c.sock")
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(path)
    stale.close()  # leaves the socket file behind, nobody listening
    manager, _ = make_manager(backend)
    srv = ControlServer(path, manager)
    srv.server_close()


def test_second_instance_is_refused(backend, make_manager, tmp_path):
    path = str(tmp_path / "c.sock")
    manager, _ = make_manager(backend)
    first = ControlServer(path, manager)
    thread = threading.Thread(target=first.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(HotspotError, match="already listening"):
            ControlServer(path, manager)
    finally:
        first.shutdown()
        first.server_close()
        thread.join(timeout=5)


def test_regular_file_at_socket_path_is_never_deleted(backend, make_manager, tmp_path):
    path = tmp_path / "c.sock"
    path.write_text("precious")
    manager, _ = make_manager(backend)
    with pytest.raises(HotspotError, match="not a socket"):
        ControlServer(str(path), manager)
    assert path.read_text() == "precious"
