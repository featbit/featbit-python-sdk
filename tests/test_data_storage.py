import pytest

from fbclient.category import DATATEST
from fbclient.data_storage import InMemoryDataStorage


@pytest.fixture
def data_storage():
    return InMemoryDataStorage()


@pytest.fixture
def items():
    items = {}
    items["id_1"] = {"id": "id_1", "timestamp": 1, "isArchived": True, "name": "name_1"}
    items["id_2"] = {"id": "id_2", "timestamp": 2, "isArchived": False, "name": "name_2"}
    items["id_3"] = {"id": "id_3", "timestamp": 3, "isArchived": False, "name": "name_3"}
    return items


def test_default_version(data_storage):
    assert data_storage.latest_version == 0
    assert not data_storage.initialized


def test_init(data_storage, items):
    all_data = {DATATEST: items}
    data_storage.init(all_data, 3)
    assert data_storage.latest_version == 3
    assert data_storage.initialized
    assert data_storage.get(DATATEST, "id_1") is None
    item = data_storage.get(DATATEST, "id_2")
    assert item is not None
    assert not item["isArchived"]
    assert item["name"] == "name_2"
    assert len(data_storage.get_all(DATATEST)) == 2


def test_invalid_init(data_storage, items):
    all_data = {DATATEST: items}
    data_storage.init(None, 3)
    assert data_storage.latest_version == 0
    assert not data_storage.initialized
    data_storage.init(DATATEST, None)
    assert data_storage.latest_version == 0
    assert not data_storage.initialized
    data_storage.init(all_data, 0)
    assert data_storage.latest_version == 0
    assert not data_storage.initialized
    data_storage.init(all_data, 3)
    data_storage.init(all_data, 2)
    assert data_storage.latest_version == 3
    assert data_storage.initialized


def test_upsert(data_storage):
    item_1 = {"id": "id_1", "timestamp": 1, "isArchived": True, "name": "name_1"}
    item_2 = {"id": "id_2", "timestamp": 2, "isArchived": False, "name": "name_2"}
    item_3 = {"id": "id_3", "timestamp": 3, "isArchived": False, "name": "name_3"}
    data_storage.upsert(DATATEST, "id_1", item_1, 1)
    data_storage.upsert(DATATEST, "id_2", item_2, 2)
    data_storage.upsert(DATATEST, "id_3", item_3, 3)
    assert data_storage.latest_version == 3
    assert data_storage.initialized
    assert data_storage.get(DATATEST, "id_1") is None
    item = data_storage.get(DATATEST, "id_2")
    assert item is not None
    assert not item["isArchived"]
    assert item["name"] == "name_2"
    assert len(data_storage.get_all(DATATEST)) == 2
    item_2 = {"id": "id_2", "timestamp": 4, "isArchived": False, "name": "name_2_2"}
    data_storage.upsert(DATATEST, "id_2", item_2, 4)
    item = data_storage.get(DATATEST, "id_2")
    assert item is not None
    assert not item["isArchived"]
    assert item["name"] == "name_2_2"


def test_invalid_upsert(data_storage):
    item_1 = {"id": "id_1", "timestamp": 1, "isArchived": False, "name": "name_1"}
    item_2 = {"id": "id_2", "timestamp": 2, "isArchived": False, "name": "name_2"}
    data_storage.upsert(None, "id_1", item_1, 1)
    assert data_storage.latest_version == 0
    assert not data_storage.initialized
    data_storage.upsert(DATATEST, None, item_1, 1)
    assert data_storage.latest_version == 0
    assert not data_storage.initialized
    data_storage.upsert(DATATEST, "id_1", None, 1)
    assert data_storage.latest_version == 0
    assert not data_storage.initialized
    data_storage.upsert(DATATEST, "id_1", item_1, None)
    assert data_storage.latest_version == 0
    assert not data_storage.initialized
    data_storage.upsert(DATATEST, "id_1", item_1, 0)
    assert data_storage.latest_version == 0
    assert not data_storage.initialized
    data_storage.upsert(DATATEST, "id_1", item_1, 1)
    data_storage.upsert(DATATEST, "id_2", item_2, 1)
    assert data_storage.latest_version == 1
    assert data_storage.initialized
