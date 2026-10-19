"""Explicit state machine. V1 has two states; later modes are added as states and rows in the table."""
from __future__ import annotations

import enum


class State(str, enum.Enum):
    OFF = "off"
    ON = "on"


class Event(enum.Enum):
    START_OK = "start_ok"  # we started the hotspot and the backend confirmed it
    STOP_OK = "stop_ok"  # we stopped the hotspot and the backend confirmed it
    OBSERVED_ACTIVE = "observed_active"  # polling found the hotspot up
    OBSERVED_INACTIVE = "observed_inactive"  # polling found the hotspot down


# Every (state, event) pair must be defined. test_state.py enforces that, so adding a
# state without deciding what every event means there is a failing test, not a latent bug.
TRANSITIONS = {
    (State.OFF, Event.START_OK): State.ON,
    (State.OFF, Event.STOP_OK): State.OFF,
    (State.OFF, Event.OBSERVED_ACTIVE): State.ON,
    (State.OFF, Event.OBSERVED_INACTIVE): State.OFF,
    (State.ON, Event.START_OK): State.ON,
    (State.ON, Event.STOP_OK): State.OFF,
    (State.ON, Event.OBSERVED_ACTIVE): State.ON,
    (State.ON, Event.OBSERVED_INACTIVE): State.OFF,
}


def transition(state: State, event: Event) -> State:
    return TRANSITIONS[(state, event)]
