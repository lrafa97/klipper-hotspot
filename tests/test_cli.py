import json
import threading

import pytest

from conftest import PASSWORD
from klipper_hotspot.api import ControlServer
from klipper_hotspot.cli import format_status, main


@pytest.fixture
def running(backend, make_manager, tmp_path):
    manager, _ = make_manager(backend)
    sock = str(tmp_path / "c.sock")
    cfg = tmp_path / "hotspot.conf"
    cfg.write_text(f"[paths]\nsocket = {sock}\ncredentials_file = {tmp_path / 'credentials'}\n")
    srv = ControlServer(sock, manager)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield str(cfg)
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def test_status_off(running, capsys):
    assert main(["--config", running, "status"]) == 0
    out = capsys.readouterr().out
    assert "Hotspot: OFF" in out and "SSID: Klipper-TEST" in out


def test_on_prints_ssid_ip_and_clients_but_not_the_password(running, capsys):
    assert main(["--config", running, "on"]) == 0
    out = capsys.readouterr().out
    assert "Hotspot: ON" in out and "IP: 10.42.0.1" in out and "Clients:" in out
    assert PASSWORD not in out


def test_credentials_command_prints_the_password(running, capsys):
    assert main(["--config", running, "credentials"]) == 0
    assert f"Password: {PASSWORD}" in capsys.readouterr().out


def test_json_output(running, capsys):
    assert main(["--config", running, "--json", "status"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "off"


def test_error_goes_to_stderr_with_exit_code_1(running, backend, capsys):
    backend.fail_start = True
    assert main(["--config", running, "on"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("ERROR:")


def test_daemon_not_running_is_a_readable_error(tmp_path, capsys):
    cfg = tmp_path / "hotspot.conf"
    cfg.write_text(f"[paths]\nsocket = {tmp_path / 'missing.sock'}\n")
    assert main(["--config", str(cfg), "status"]) == 1
    assert "not reachable" in capsys.readouterr().err


def test_init_creates_credentials_once(tmp_path, capsys):
    cfg = tmp_path / "hotspot.conf"
    cfg.write_text(f"[paths]\ncredentials_file = {tmp_path / 'etc' / 'credentials'}\n")
    assert main(["--config", str(cfg), "init"]) == 0
    first = capsys.readouterr().out
    assert "created" in first
    assert main(["--config", str(cfg), "init"]) == 0
    second = capsys.readouterr().out
    assert "already exist" in second
    assert first.split("SSID: ")[1] == second.split("SSID: ")[1]  # never rotates silently


def test_invalid_config_is_reported_not_a_traceback(tmp_path, capsys):
    cfg = tmp_path / "hotspot.conf"
    cfg.write_text("[hotspot]\nband = a\n")
    assert main(["--config", str(cfg), "status"]) == 1
    assert "band must be" in capsys.readouterr().err


def test_unknown_command_is_rejected_by_argparse():
    with pytest.raises(SystemExit):
        main(["reboot"])


def test_format_status_handles_unknown_clients():
    text = format_status({"state": "on", "ssid": "X", "ip": "10.42.0.1", "clients": None})
    assert "Clients: unknown" in text
