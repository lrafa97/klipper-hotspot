"""Per-machine hotspot credentials: generated once at install time, stored 0600, never logged."""
from __future__ import annotations

import configparser
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .errors import CredentialsError

# No look-alike characters (0/o, 1/l/i) so the password can be read off a label or a screen.
PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
SSID_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
PASSWORD_LENGTH = 12
SSID_SUFFIX_LENGTH = 4


@dataclass(frozen=True, repr=False)
class Credentials:
    ssid: str
    password: str

    def __repr__(self) -> str:  # keeps the password out of logs and tracebacks
        return f"Credentials(ssid={self.ssid!r}, password=***)"


def generate_credentials(prefix: str, choice: Callable[[str], str] = secrets.choice) -> Credentials:
    suffix = "".join(choice(SSID_ALPHABET) for _ in range(SSID_SUFFIX_LENGTH))
    password = "".join(choice(PASSWORD_ALPHABET) for _ in range(PASSWORD_LENGTH))
    return Credentials(ssid=f"{prefix}-{suffix}", password=password)


def create_credentials(
    path: str, prefix: str, choice: Callable[[str], str] = secrets.choice
) -> Credentials:
    """Create the credentials file. Refuses to overwrite: rotating is a deliberate, separate act."""
    target = Path(path)
    if target.exists():
        raise CredentialsError(f"credentials already exist at {path}")
    creds = generate_credentials(prefix, choice)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(str(tmp), flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("[hotspot]\n")
            handle.write(f"ssid = {creds.ssid}\n")
            handle.write(f"password = {creds.password}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(str(tmp), 0o600)
        os.replace(str(tmp), str(target))
    except BaseException:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
        raise
    return creds


def load_credentials(path: str) -> Credentials:
    target = Path(path)
    try:
        mode = target.stat().st_mode
    except FileNotFoundError:
        raise CredentialsError(
            f"credentials file {path} not found; run: sudo klipper-hotspot init"
        )
    except OSError as exc:
        raise CredentialsError(f"cannot read credentials {path}: {exc.strerror or exc}")
    if mode & 0o077:
        raise CredentialsError(
            f"credentials file {path} must not be accessible by group or others (chmod 600)"
        )
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(target.read_text(encoding="utf-8"))
        ssid = parser.get("hotspot", "ssid").strip()
        password = parser.get("hotspot", "password").strip()
    except (configparser.Error, OSError):
        raise CredentialsError(f"credentials file {path} is malformed")
    if not 1 <= len(ssid.encode("utf-8")) <= 32:
        raise CredentialsError("SSID must be 1-32 bytes")
    if not 8 <= len(password) <= 63:
        raise CredentialsError("WPA2 password must be 8-63 characters")
    return Credentials(ssid=ssid, password=password)
