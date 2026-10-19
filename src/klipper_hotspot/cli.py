"""Command line interface. The Klipper macros call this; so can a human over SSH."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any, Dict, List, Optional

from .backend import NmcliBackend
from .client import send_request
from .config import Config, load_config
from .credentials import create_credentials, load_credentials
from .doctor import FAIL, run_checks
from .errors import CredentialsError, HotspotError

COMMANDS = ("daemon", "on", "off", "status", "credentials", "init", "doctor", "cleanup")


def format_status(result: Dict[str, Any]) -> str:
    on = result.get("state") == "on"
    lines = [f"Hotspot: {'ON' if on else 'OFF'}", f"SSID: {result.get('ssid')}"]
    if on:
        lines.append(f"IP: {result.get('ip') or 'unknown'}")
        clients = result.get("clients")
        lines.append(f"Clients: {'unknown' if clients is None else clients}")
    if result.get("last_error"):
        lines.append(f"Last error: {result['last_error']}")
    return "\n".join(lines)


def format_credentials(result: Dict[str, Any]) -> str:
    return f"SSID: {result['ssid']}\nPassword: {result['password']}"


def _emit(args: argparse.Namespace, result: Dict[str, Any], text: str) -> None:
    print(json.dumps(result) if args.json else text)


def _run(args: argparse.Namespace, config: Config) -> int:
    cmd = args.command
    if cmd == "daemon":
        from .daemon import run_daemon

        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        return run_daemon(config)

    if cmd in ("on", "off", "status"):
        result = send_request(config.socket_path, cmd)
        _emit(args, result, format_status(result))
        return 0

    if cmd == "credentials":
        result = send_request(config.socket_path, cmd)
        _emit(args, result, format_credentials(result))
        return 0

    if cmd == "init":
        try:
            creds = create_credentials(config.credentials_file, config.ssid_prefix)
            print(f"Credentials created. SSID: {creds.ssid}")
        except CredentialsError:
            creds = load_credentials(config.credentials_file)
            print(f"Credentials already exist. SSID: {creds.ssid}")
        return 0

    if cmd == "doctor":
        checks = run_checks(config, NmcliBackend())
        for check in checks:
            print(f"[{check.level.upper():4}] {check.name}: {check.detail}")
        return 1 if any(c.level == FAIL for c in checks) else 0

    if cmd == "cleanup":
        NmcliBackend().stop_hotspot()
        print("Hotspot profile removed.")
        return 0

    raise HotspotError(f"unknown command {cmd}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="klipper-hotspot")
    parser.add_argument("--config", default=None, help="path to hotspot.conf")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("command", choices=COMMANDS)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        return _run(args, config)
    except HotspotError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
