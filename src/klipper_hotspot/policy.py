"""Policies decide WHEN the hotspot should be on. The manager only knows HOW to switch it."""
from __future__ import annotations

import abc


class Policy(abc.ABC):
    @abc.abstractmethod
    def should_start_on_boot(self) -> bool:
        """Whether the hotspot must be brought up when the daemon starts and it is not already up."""


class ManualPolicy(Policy):
    """V1: the hotspot is a mode the user switches on. Optionally it also starts at boot."""

    def __init__(self, autostart: bool) -> None:
        self._autostart = autostart

    def should_start_on_boot(self) -> bool:
        return self._autostart
