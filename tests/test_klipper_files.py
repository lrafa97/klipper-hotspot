"""The macros, the KlipperScreen menu and the daemon's verbs must not drift apart."""
import configparser
import json
import re
from pathlib import Path

from klipper_hotspot.api import VERBS

DATA = Path(__file__).resolve().parent.parent / "data"


def macro_names():
    text = (DATA / "klipper-hotspot.cfg").read_text()
    return set(re.findall(r"^\[gcode_macro (\w+)\]", text, flags=re.MULTILINE))


def menu():
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.read_string((DATA / "klipperscreen-menu.conf").read_text())
    return parser


def test_every_macro_runs_one_fixed_command_with_a_real_api_verb():
    text = (DATA / "klipper-hotspot.cfg").read_text()
    calls = re.findall(r"RUN_SHELL_COMMAND (.*)", text)
    assert calls, "macros must call the CLI"
    for call in calls:
        assert "CMD=hotspot_cmd" in call
        verb = re.fullmatch(r'CMD=hotspot_cmd PARAMS="(\w+) --screen"', call.strip())
        assert verb, f"PARAMS must be a fixed literal verb plus --screen, got: {call}"
        assert verb.group(1) in VERBS


def test_every_menu_button_points_at_an_existing_macro():
    parser = menu()
    macros = macro_names()
    buttons = [s for s in parser.sections() if parser.has_option(s, "method")]
    assert buttons
    for section in buttons:
        params = json.loads(parser.get(section, "params"))
        assert params["script"] in macros, f"[{section}] calls unknown macro {params['script']}"
        assert params["script"] in parser.get(section, "enable"), f"[{section}] enable must test its macro"


def test_menu_follows_the_documented_structure():
    parser = menu()
    for section in parser.sections():
        # inside the More menu, which KlipperScreen defines itself (main_menu.conf)
        assert section.startswith("menu __main more hotspot"), section
        # panel cannot be combined with method/params/confirm (KlipperScreen docs)
        assert not parser.has_option(section, "panel")
        parent = section.rsplit(" ", 1)[0]
        if parent != "menu __main more":
            assert parent in parser.sections(), f"[{section}] has no parent menu item"
        assert parser.has_option(section, "name")


def test_only_section_headers_contain_square_brackets():
    # KlipperScreen rejected the whole config ("Section headers have extra information after
    # brackets") because a comment line contained a bracket. Real screen, real failure.
    for number, line in enumerate((DATA / "klipperscreen-menu.conf").read_text().splitlines(), 1):
        if "[" in line or "]" in line:
            assert re.fullmatch(r"\[menu [\w ]+\]", line), f"line {number} has a stray bracket: {line!r}"


def test_dangerous_button_asks_for_confirmation():
    parser = menu()
    assert parser.has_option("menu __main more hotspot on", "confirm")
