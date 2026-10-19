"""On-screen feedback: a Klipper action prompt, sent through Moonraker on this machine.

KlipperScreen (and Mainsail) draw action prompts as a dialog, so the person standing at the
machine sees the result of a button press instead of text buried in the console.

Everything that ends up inside a G-code line goes through clean(): a message that contains a
newline, a quote or a semicolon must never be able to become a second G-code command.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .errors import HotspotError

# Real failures were cut at 80 and then at 200 characters, each time right where nmcli says WHY
# it failed (its errors are about 250 characters), so these are generous. The dialog is
# 800x480, wraps text and scrolls vertically.
MAX_LINE = 400  # one part of the text (an SSID, a password, an error)
MAX_TEXT = 500  # the whole text of one prompt
MAX_TITLE = 40

# Whitelist, not blacklist. Anything else becomes "?".
# The apostrophe is allowed on purpose: nmcli quotes names in nearly every error message, and
# inside the double-quoted MSG it is a plain character. The double quote is what must never pass.
_UNSAFE = re.compile(r"[^A-Za-z0-9 .,:/_()+'-]")

_PROMPT = 'RESPOND TYPE=command MSG="action:{}"'
_CLOSE = "Close|RESPOND TYPE=command MSG=action:prompt_end|primary"


def clean(value: Any, limit: int = MAX_LINE) -> str:
    return _UNSAFE.sub("?", str(value))[:limit]


def prompt_script(title: str, lines: List[str]) -> str:
    # KlipperScreen keeps only the LAST prompt_text (its source overwrites the text each time;
    # seen on a real screen: Mainsail showed both lines, KlipperScreen only the second). So all
    # lines go into ONE text. KlipperScreen wraps long text, so a longer line is fine.
    text = " - ".join(clean(line) for line in lines)[:MAX_TEXT]
    out = [_PROMPT.format(f"prompt_begin {clean(title, MAX_TITLE)}")]
    out.append(_PROMPT.format(f"prompt_text {text}"))
    out.append(_PROMPT.format(f"prompt_footer_button {_CLOSE}"))
    out.append(_PROMPT.format("prompt_show"))
    return "\n".join(out)


def describe(
    cmd: str, result: Dict[str, Any], credentials: Optional[Dict[str, Any]] = None
) -> Tuple[str, List[str]]:
    """The title and lines to show for a finished command."""
    on = result.get("state") == "on"
    ip = result.get("ip")
    address = f"Address: http://{ip}" if ip else "Address: unknown"

    if cmd == "on":
        if not on:
            return "Hotspot", ["The hotspot is not active."]
        lines = [f"SSID: {result.get('ssid')}"]
        if credentials:
            lines.append(f"Password: {credentials.get('password')}")
        lines.append(f"Open http://{ip}" if ip else "Address: unknown")
        return "Hotspot ON", lines

    if cmd == "off":
        return "Hotspot OFF", ["Returning to the usual Wi-Fi network."]

    if cmd == "credentials":
        return "Hotspot Wi-Fi", [f"SSID: {result.get('ssid')}", f"Password: {result.get('password')}"]

    lines = [f"State: {'ON' if on else 'OFF'}", f"SSID: {result.get('ssid')}"]
    if on:
        clients = result.get("clients")
        lines += [address, f"Clients: {'unknown' if clients is None else clients}"]
    if result.get("last_error"):
        lines.append(f"Last error: {result['last_error']}")
    return "Hotspot status", lines


def send_script(moonraker_url: str, script: str, timeout: float = 5.0) -> None:
    """POST a G-code script to Moonraker. Raises HotspotError(notify_failed) on any problem."""
    request = urllib.request.Request(
        moonraker_url.rstrip("/") + "/printer/gcode/script",
        data=json.dumps({"script": script}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # Never go through an HTTP proxy from the environment: this is always this machine.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            response.read(1024)
    except urllib.error.HTTPError as exc:
        raise HotspotError(f"Moonraker answered HTTP {exc.code}", code="notify_failed")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        raise HotspotError(f"cannot reach Moonraker at {moonraker_url}: {reason}", code="notify_failed")
