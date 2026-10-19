"""Persisted state: survives daemon restarts and reboots. Tolerant of corruption."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

STORE_VERSION = 1


@dataclass
class StoredState:
    desired: str = "off"  # "on" | "off"
    since: Optional[float] = None


class StateStore:
    def __init__(self, path: str) -> None:
        self._path = Path(path)

    def load(self) -> StoredState:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            desired = raw.get("desired", "off")
            since = raw.get("since")
            if desired not in ("on", "off"):
                raise ValueError("bad desired")
            if since is not None:
                since = float(since)
            return StoredState(desired=desired, since=since)
        except FileNotFoundError:
            return StoredState()
        except (ValueError, TypeError, AttributeError, OSError) as exc:
            log.warning("ignoring unreadable state file %s: %s", self._path, exc)
            return StoredState()

    def save(self, state: StoredState) -> None:
        payload = {"version": STORE_VERSION, "desired": state.desired, "since": state.since}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_name(self._path.name + ".tmp")
            with open(str(tmp), "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(str(tmp), str(self._path))
        except OSError as exc:
            # State is a convenience, never a reason to fail a switch.
            log.warning("cannot persist state to %s: %s", self._path, exc)
