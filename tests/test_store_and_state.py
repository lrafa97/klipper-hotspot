import itertools
import json

from klipper_hotspot.state import TRANSITIONS, Event, State, transition
from klipper_hotspot.store import StateStore, StoredState


def test_every_state_event_pair_is_defined():
    for state, event in itertools.product(State, Event):
        assert (state, event) in TRANSITIONS, f"missing transition for {state}, {event}"


def test_transitions():
    assert transition(State.OFF, Event.START_OK) is State.ON
    assert transition(State.ON, Event.STOP_OK) is State.OFF
    assert transition(State.ON, Event.OBSERVED_INACTIVE) is State.OFF  # someone brought it down
    assert transition(State.OFF, Event.OBSERVED_ACTIVE) is State.ON  # someone brought it up
    assert transition(State.ON, Event.START_OK) is State.ON  # idempotent


def test_store_roundtrip(tmp_path):
    store = StateStore(str(tmp_path / "sub" / "state.json"))
    store.save(StoredState(desired="on", since=1234.5))
    loaded = store.load()
    assert loaded.desired == "on" and loaded.since == 1234.5
    assert not list((tmp_path / "sub").glob("*.tmp"))


def test_store_missing_file_gives_default(tmp_path):
    loaded = StateStore(str(tmp_path / "none.json")).load()
    assert loaded == StoredState(desired="off", since=None)


def test_store_corrupt_file_gives_default(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")
    assert StateStore(str(path)).load() == StoredState()


def test_store_rejects_invalid_desired(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"desired": "banana"}))
    assert StateStore(str(path)).load() == StoredState()


def test_store_write_failure_does_not_raise(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory")
    StateStore(str(blocker / "state.json")).save(StoredState(desired="on"))  # must not raise
