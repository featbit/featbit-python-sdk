import base64
import json
import threading
from pathlib import Path
from queue import Queue

from fbclient.category import FEATURE_FLAGS, SEGMENTS
from fbclient.config import Config
from fbclient.data_storage import InMemoryDataStorage
from fbclient.flag_change_notification import FLAG_CHANGE_NOTICE_TYPE
from fbclient.notice_broadcaster import NoticeBroadcater
from fbclient.status import DataUpdateStatusProviderImpl
from fbclient.streaming import Streaming, _data_to_dict

FAKE_ENV_SECRET = base64.b64encode(b"archived-data-sync").decode()
FAKE_URL = "http://fake"


def load_data(archived_flag_keys=(), archived_segment_ids=()):
    payload = json.loads(Path("tests/fbclient_test_data.json").read_text())
    data = payload["data"]
    for flag in data["featureFlags"]:
        flag["isArchived"] = flag["key"] in archived_flag_keys
    for segment in data["segments"]:
        segment["isArchived"] = segment["id"] in archived_segment_ids
    return data


def test_archived_flag_keeps_its_category():
    data = load_data(archived_flag_keys={"ff-test-bool"})

    _, all_data = _data_to_dict(data)

    archived = all_data[FEATURE_FLAGS]["ff-test-bool"]
    assert archived["isArchived"] is True
    assert archived["cat"] == FEATURE_FLAGS


def test_archived_segment_keeps_its_category():
    segment_id = json.loads(Path("tests/fbclient_test_data.json").read_text())["data"][
        "segments"
    ][0]["id"]
    data = load_data(archived_segment_ids={segment_id})

    _, all_data = _data_to_dict(data)

    archived = all_data[SEGMENTS][segment_id]
    assert archived["isArchived"] is True
    assert archived["cat"] == SEGMENTS


def test_data_sync_with_an_archived_flag_still_broadcasts_changes():
    broadcaster = NoticeBroadcater()
    notices: Queue = Queue()
    broadcaster.add_listener(FLAG_CHANGE_NOTICE_TYPE, notices.put)
    streaming = Streaming(
        Config(
            FAKE_ENV_SECRET, event_url=FAKE_URL, streaming_url=FAKE_URL, offline=True
        ),
        broadcaster,
        DataUpdateStatusProviderImpl(InMemoryDataStorage()),
        threading.Event(),
    )

    try:
        assert streaming._on_process_data(
            load_data(archived_flag_keys={"ff-test-bool"})
        )
        changed_keys = set()
        while len(changed_keys) < 7:
            changed_keys.add(notices.get(timeout=1).flag_key)
        assert "ff-test-bool" in changed_keys
    finally:
        streaming.stop()
        broadcaster.stop()
