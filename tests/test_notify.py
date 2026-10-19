import pytest

from conftest import PASSWORD
from klipper_hotspot.errors import HotspotError
from klipper_hotspot.notify import clean, describe, prompt_script, send_script

PREFIX = 'RESPOND TYPE=command MSG="action:'


def test_clean_keeps_normal_text():
    assert clean("SSID: Klipper-7DJA (http://10.42.0.1)") == "SSID: Klipper-7DJA (http://10.42.0.1)"


def test_clean_removes_everything_that_could_end_a_message_or_start_a_command():
    dirty = 'a"b;c\nd|e#f{g}h\'i=j\\k%l'
    cleaned = clean(dirty)
    assert not any(ch in cleaned for ch in '";\n|#{}\'=\\%')


def test_clean_limits_length():
    assert len(clean("x" * 500)) == 80
    assert len(clean("x" * 500, 10)) == 10


def test_prompt_script_has_the_documented_shape():
    lines = prompt_script("Hotspot ON", ["SSID: A", "Password: B"]).split("\n")
    assert lines[0] == PREFIX + 'prompt_begin Hotspot ON"'
    assert lines[1] == PREFIX + 'prompt_text SSID: A - Password: B"'
    assert lines[2].startswith(PREFIX + "prompt_footer_button Close|")
    assert lines[-1] == PREFIX + 'prompt_show"'


def test_all_information_goes_into_one_prompt_text():
    # Seen on a real KlipperScreen: it keeps only the LAST prompt_text, Mainsail shows all of them.
    # With one line per fact the screen showed the SSID and lost the state (and would lose the
    # password). Everything must be in a single prompt_text.
    script = prompt_script("Hotspot ON", ["SSID: A", "Password: B", "Open http://10.42.0.1"])
    assert script.count("prompt_text") == 1
    assert "SSID: A - Password: B - Open http://10.42.0.1" in script


def test_the_whole_text_is_length_limited():
    script = prompt_script("t", ["x" * 80] * 10)
    text = [l for l in script.split("\n") if "prompt_text" in l][0]
    assert len(text) <= len(PREFIX) + len("prompt_text ") + 240 + 1


def test_text_can_never_become_a_second_gcode_command():
    hostile = ['x"\nM112', "y; FIRMWARE_RESTART", 'z"\nRESPOND MSG="pwned']
    script = prompt_script('title"\nM112', hostile)
    for line in script.split("\n"):
        assert line.startswith(PREFIX), f"unexpected command line: {line!r}"
        assert line.count('"') == 2 or "prompt_footer_button" in line
    assert "M112" not in [l.strip() for l in script.split("\n")]


def test_describe_on_shows_ssid_password_and_address():
    result = {"state": "on", "ssid": "Klipper-TEST", "ip": "10.42.0.1"}
    title, lines = describe("on", result, {"ssid": "Klipper-TEST", "password": PASSWORD})
    assert title == "Hotspot ON"
    text = "\n".join(lines)
    assert "Klipper-TEST" in text and PASSWORD in text and "Open http://10.42.0.1" in text


def test_describe_on_without_credentials_omits_the_password_line():
    title, lines = describe("on", {"state": "on", "ssid": "S", "ip": "10.42.0.1"}, None)
    assert not any("Password" in l for l in lines)


def test_describe_status_never_shows_the_password():
    result = {"state": "on", "ssid": "S", "ip": "10.42.0.1", "clients": 2, "last_error": None}
    title, lines = describe("status", result, {"password": PASSWORD})
    assert PASSWORD not in "\n".join(lines)
    assert "Clients: 2" in lines


def test_describe_status_off_and_error_and_unknown_clients():
    assert describe("status", {"state": "off", "ssid": "S"})[1][0] == "State: OFF"
    _, lines = describe("status", {"state": "on", "ssid": "S", "ip": None, "clients": None, "last_error": "boom"})
    assert "Address: unknown" in lines and "Clients: unknown" in lines and "Last error: boom" in lines


def test_describe_off_and_credentials():
    assert describe("off", {"state": "off"})[0] == "Hotspot OFF"
    title, lines = describe("credentials", {"ssid": "S", "password": "P"})
    assert "Password: P" in lines


def test_send_script_posts_json_to_the_gcode_endpoint(moonraker):
    send_script(moonraker.url, "G28")
    assert moonraker.paths == ["/printer/gcode/script"]
    assert moonraker.scripts == ["G28"]


def test_send_script_ignores_proxy_environment_variables(moonraker, monkeypatch):
    # A NO_PROXY that happens to cover loopback would hide the bug, so clear it first.
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    send_script(moonraker.url, "G28")
    assert moonraker.scripts == ["G28"]


def test_send_script_failure_is_a_notify_error(moonraker):
    moonraker.status = 500
    with pytest.raises(HotspotError) as excinfo:
        send_script(moonraker.url, "G28")
    assert excinfo.value.code == "notify_failed" and "500" in str(excinfo.value)


def test_send_script_to_a_closed_port_is_a_notify_error():
    with pytest.raises(HotspotError) as excinfo:
        send_script("http://127.0.0.1:9", "G28", timeout=2)
    assert excinfo.value.code == "notify_failed"
