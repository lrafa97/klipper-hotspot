"""The daemon: wires everything together and serves the control socket."""
from __future__ import annotations

import logging
import signal
import threading

from .api import ControlServer
from .backend import NmcliBackend
from .config import Config
from .credentials import load_credentials
from .manager import Manager
from .policy import ManualPolicy
from .store import StateStore

log = logging.getLogger(__name__)


def build_manager(config: Config) -> Manager:
    return Manager(
        config=config,
        credentials=load_credentials(config.credentials_file),
        backend=NmcliBackend(),
        store=StateStore(config.state_file),
        policy=ManualPolicy(config.autostart),
    )


def run_daemon(config: Config) -> int:
    for warning in config.warnings:
        log.warning("config: %s", warning)
    manager = build_manager(config)
    manager.reconcile()
    server = ControlServer(config.socket_path, manager, group=config.socket_group or None)

    def _stop(signum, frame):  # noqa: ANN001
        # shutdown() blocks until serve_forever returns, so it cannot run in the handler itself.
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("listening on %s", config.socket_path)
    try:
        server.serve_forever()
    finally:
        # Stopping the daemon deliberately leaves the hotspot as it is: restarting or
        # updating the service must not kick connected users off the machine.
        server.server_close()
    return 0
