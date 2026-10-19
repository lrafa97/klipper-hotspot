"""Manager: applies requests through the backend, owns the state, persists it."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

from .backend import HotspotInfo, HotspotSettings, NetworkBackend
from .config import Config
from .credentials import Credentials
from .errors import BackendError, HotspotError
from .policy import Policy
from .state import Event, State, transition
from .store import StateStore, StoredState

log = logging.getLogger(__name__)


class Manager:
    def __init__(
        self,
        *,
        config: Config,
        credentials: Credentials,
        backend: NetworkBackend,
        store: StateStore,
        policy: Policy,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._config = config
        self._credentials = credentials
        self._backend = backend
        self._store = store
        self._policy = policy
        self._clock = clock
        self._lock = threading.RLock()
        self._state = State.OFF
        self._since: Optional[float] = None
        self._last_error: Optional[str] = None

    # -- internals -------------------------------------------------------------------------

    def _settings(self) -> HotspotSettings:
        return HotspotSettings(
            interface=self._config.interface,
            ssid=self._credentials.ssid,
            password=self._credentials.password,
            band=self._config.band,
            channel=self._config.channel,
            address=self._config.address,
        )

    def _persist(self) -> None:
        desired = "on" if self._state is State.ON else "off"
        self._store.save(StoredState(desired=desired, since=self._since))

    def _apply(self, event: Event, since: Optional[float] = None) -> None:
        new = transition(self._state, event)
        if new is self._state:
            return
        self._since = (since if since is not None else self._clock()) if new is State.ON else None
        self._state = new
        self._persist()

    def _observe(self, since: Optional[float] = None) -> HotspotInfo:
        try:
            info = self._backend.info(self._config.interface)
        except BackendError as exc:
            self._last_error = str(exc)
            raise
        self._apply(Event.OBSERVED_ACTIVE if info.active else Event.OBSERVED_INACTIVE, since)
        return info

    def _status_dict(self, info: HotspotInfo) -> Dict[str, Any]:
        # Never includes the password: status is polled and may end up in logs or UIs.
        return {
            "state": self._state.value,
            "interface": self._config.interface,
            "ssid": self._credentials.ssid,
            "ip": info.ip,
            "clients": info.clients,
            "since": int(self._since) if self._since is not None else None,
            "last_error": self._last_error,
        }

    # -- lifecycle -------------------------------------------------------------------------

    def reconcile(self) -> None:
        """Called once at daemon start. Adopts what is already up, otherwise asks the policy."""
        with self._lock:
            stored = self._store.load()
            try:
                info = self._backend.info(self._config.interface)
            except HotspotError as exc:
                self._last_error = str(exc)
                log.error("cannot read network state at startup: %s", exc)
                return
            if info.active:
                since = stored.since if stored.desired == "on" else None
                self._apply(Event.OBSERVED_ACTIVE, since)
                log.info("hotspot already active, adopting it")
                return
            self._apply(Event.OBSERVED_INACTIVE)
            if self._policy.should_start_on_boot():
                log.info("autostart enabled, starting hotspot")
                try:
                    self.on()
                except HotspotError as exc:
                    log.error("autostart failed: %s", exc)
            else:
                self._persist()

    # -- verbs -----------------------------------------------------------------------------

    def on(self) -> Dict[str, Any]:
        with self._lock:
            info = self._observe()
            if self._state is State.ON:
                # Idempotent: do not recreate the access point and drop connected clients.
                return self._status_dict(info)
            try:
                self._backend.start_hotspot(self._settings())
            except BackendError as exc:
                self._last_error = str(exc)
                log.error("failed to start hotspot: %s", exc)
                raise
            self._last_error = None
            self._apply(Event.START_OK)
            return self._status_dict(self._backend.info(self._config.interface))

    def off(self) -> Dict[str, Any]:
        with self._lock:
            try:
                self._backend.stop_hotspot()
            except BackendError as exc:
                self._last_error = str(exc)
                log.error("failed to stop hotspot: %s", exc)
                raise
            self._last_error = None
            self._apply(Event.STOP_OK)
            return self._status_dict(HotspotInfo(active=False))

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return self._status_dict(self._observe())

    def credentials(self) -> Dict[str, str]:
        with self._lock:
            return {"ssid": self._credentials.ssid, "password": self._credentials.password}
