import threading
from time import sleep, time
from unittest.mock import patch

import pytest

from fbclient.category import DATATEST
from fbclient.data_storage import InMemoryDataStorage
from fbclient.status import DataUpdateStatusProviderImpl
from fbclient.status_types import State, StateType


@pytest.fixture
def items():
    items = {}
    items["id_1"] = {"id": "id_1", "timestamp": 1, "isArchived": True, "name": "name_1"}
    items["id_2"] = {"id": "id_2", "timestamp": 2, "isArchived": False, "name": "name_2"}
    items["id_3"] = {"id": "id_3", "timestamp": 3, "isArchived": False, "name": "name_3"}
    return items


@pytest.fixture
def data_storage():
    return InMemoryDataStorage()


@pytest.fixture
def data_updator(data_storage):
    return DataUpdateStatusProviderImpl(data_storage)


def test_init_data_storage(data_updator, data_storage, items):
    all_data = {DATATEST: items}
    if data_updator.init(all_data, 3):
        data_updator.update_state(State.ok_state())
    assert data_updator.latest_version == 3
    assert data_updator.initialized
    assert data_updator.current_state.state_type == StateType.OK
    item = data_storage.get(DATATEST, "id_2")
    assert item["name"] == "name_2"


def test_upsert_data_storage(data_updator, data_storage, items):
    all_data = {DATATEST: items}
    if data_updator.init(all_data, 3):
        data_updator.update_state(State.ok_state())
    item_2 = {"id": "id_2", "timestamp": 4, "isArchived": False, "name": "name_2_2"}
    if data_updator.upsert(DATATEST, "id_2", item_2, 4):
        data_updator.update_state(State.ok_state())
    assert data_updator.latest_version == 4
    assert data_updator.initialized
    item = data_storage.get(DATATEST, "id_2")
    assert item["name"] == "name_2_2"
    assert data_updator.current_state.state_type == StateType.OK


@patch.object(InMemoryDataStorage, "init")
def test_init_data_storage_unexptected_error(mock_init_method, data_updator, data_storage, items):
    mock_init_method.side_effect = RuntimeError("test exception")
    all_data = {DATATEST: items}
    if data_updator.init(all_data, 3):
        data_updator.update_state(State.ok_state())
    assert data_updator.latest_version == 0
    assert not data_updator.initialized
    assert data_updator.current_state.state_type == StateType.INITIALIZING
    assert len(data_storage.get_all(DATATEST)) == 0


@patch.object(InMemoryDataStorage, "upsert")
def test_upsert_data_storage_unexpected_error(mock_upsert_method, data_updator, data_storage, items):
    mock_upsert_method.side_effect = RuntimeError("test exception")
    all_data = {DATATEST: items}
    if data_updator.init(all_data, 3):
        data_updator.update_state(State.ok_state())
    assert data_updator.latest_version == 3
    assert data_updator.initialized
    assert data_updator.current_state.state_type == StateType.OK
    item_2 = {"id": "id_2", "timestamp": 4, "isArchived": False, "name": "name_2_2"}
    if data_updator.upsert(DATATEST, "id_2", item_2, 4):
        data_updator.update_state(State.ok_state())
    assert data_updator.latest_version == 3
    assert data_updator.initialized
    assert data_updator.current_state.state_type == StateType.INTERRUPTED
    item_2 = data_storage.get(DATATEST, "id_2")
    assert item_2["name"] == "name_2"


def test_update_state(data_updator):
    data_updator.update_state(State.interrupted_state("some type", "some reason"))
    assert data_updator.current_state.state_type == StateType.INITIALIZING
    data_updator.update_state(State.ok_state())
    data_updator.update_state(State.interrupted_state("some type", "some reason"))
    assert data_updator.current_state.state_type == StateType.INTERRUPTED


def test_status_listener_receives_changes_and_can_be_removed(data_updator):
    received = []

    def listener(state):
        received.append(state.state_type)

    data_updator.add_listener(listener)
    data_updator.add_listener(listener)
    data_updator.add_listener(None)
    data_updator.remove_listener(lambda _state: None)
    data_updator.update_state(State.ok_state())
    data_updator.update_state(State.interrupted_state("network", "disconnected"))
    data_updator.remove_listener(listener)
    data_updator.update_state(State.ok_state())

    assert received == [StateType.OK, StateType.INTERRUPTED]


def test_status_listener_exception_does_not_escape_or_block_others(data_updator):
    received = []

    def failing_listener(_state):
        raise RuntimeError("listener failure")

    data_updator.add_listener(failing_listener)
    data_updator.add_listener(lambda state: received.append(state.state_type))

    data_updator.update_state(State.ok_state())

    assert received == [StateType.OK]
    assert data_updator.current_state.state_type == StateType.OK


def test_status_listener_preserves_concurrent_transition_order(data_updator):
    first_callback_started = threading.Event()
    release_first_callback = threading.Event()
    received = []

    def listener(state):
        if state.state_type == StateType.OK:
            first_callback_started.set()
            assert release_first_callback.wait(1)
        received.append(state.state_type)

    data_updator.add_listener(listener)
    first_update = threading.Thread(
        target=data_updator.update_state,
        args=(State.ok_state(),)
    )
    second_update = threading.Thread(
        target=data_updator.update_state,
        args=(State.interrupted_state("network", "disconnected"),)
    )

    first_update.start()
    assert first_callback_started.wait(1)
    second_update.start()
    second_update.join(1)
    release_first_callback.set()
    first_update.join(1)

    assert not first_update.is_alive()
    assert not second_update.is_alive()
    assert received == [StateType.OK, StateType.INTERRUPTED]


def test_wait_for_OKState(data_updator):
    assert not data_updator.wait_for_OKState(timeout=0.1)
    data_updator.update_state(State.ok_state())
    assert data_updator.wait_for_OKState(timeout=0.1)


def test_wait_for_OKState_in_thread(data_updator):
    def dummy():
        sleep(0.05)
        data_updator.update_state(State.ok_state())

    t = threading.Thread(target=dummy)
    t.start()
    time_1 = time()
    assert data_updator.wait_for_OKState(timeout=0.1)
    time_2 = time()
    assert time_2 - time_1 < 0.1
    assert time_2 - time_1 >= 0.05


def test_wait_for_timeout(data_updator):
    time_1 = time()
    assert not data_updator.wait_for_OKState(timeout=0.1)
    time_2 = time()
    assert time_2 - time_1 >= 0.1
