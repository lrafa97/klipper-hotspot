"""Exception types. Every error that can reach a client carries a stable machine code."""
from __future__ import annotations

from typing import Optional


class HotspotError(Exception):
    code = "error"

    def __init__(self, message: str, code: Optional[str] = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class ConfigError(HotspotError):
    code = "config_error"


class CredentialsError(HotspotError):
    code = "credentials_error"


class BackendError(HotspotError):
    code = "backend_error"


class ProtocolError(HotspotError):
    code = "bad_request"
