import base64
import threading
from time import sleep
import pytest
from fbclient.common_types import FBUser

from fbclient.config import Config
from fbclient.event_processor import DefaultEventProcessor
from fbclient.event_types import UserEvent
from fbclient.utils.http_client import MockSender

FAKE_URL = "http://fake"
FAKE_ENV_SECRET = base64.b64encode(b"fake_env_secret").decode()
USER_1 = {"key": "test-user-1", "name": "test-user-1"}
USER_2 = {"key": "test-user-2", "name": "test-user-2"}
USER_3 = {"key": "test-user-3", "name": "test-user-3"}


@pytest.fixture
def ready_event():
    return threading.Event()


@pytest.fixture
def mock_sender(ready_event):
    return MockSender(ready_event)


@pytest.fixture
def event_processor(mock_sender):
    config = Config(FAKE_ENV_SECRET,
                    event_url=FAKE_URL,
                    streaming_url=FAKE_URL,
                    events_flush_interval=0.1,
                    events_max_in_queue=100)
    return DefaultEventProcessor(config, mock_sender)


def test_event_processor_start_and_stop(event_processor, mock_sender):
    with event_processor:
        assert mock_sender.get_sending_json_info(timeout=0.2) is None
    assert mock_sender.closed


def test_event_processor_can_gracefully_close_if_sender_error_on_close(event_processor, mock_sender):
    with event_processor:
        mock_sender.fake_error_on_close = RuntimeError("test exception")
        assert mock_sender.get_sending_json_info(timeout=0.2) is None
    assert mock_sender.closed


def test_event_processor_send_auto_flush(event_processor, mock_sender):
    with event_processor as ep:
        ep.send_event(UserEvent(FBUser.from_dict(USER_1)))
        ep.send_event(UserEvent(FBUser.from_dict(USER_2)))
        info = mock_sender.get_sending_json_info(timeout=0.2)
        if info.size == 1:
            assert info.is_contain_user("test-user-1")
        else:
            assert info.is_contain_user("test-user-1")
            assert info.is_contain_user("test-user-2")
    assert mock_sender.closed


def test_event_processor_send_manuel_flush(event_processor, mock_sender):
    with event_processor as ep:
        ep.send_event(UserEvent(FBUser.from_dict(USER_1)))
        ep.flush()
        info = mock_sender.get_sending_json_info(timeout=0.2)
        assert info.size == 1
        assert info.is_contain_user("test-user-1")
        ep.send_event(UserEvent(FBUser.from_dict(USER_2)))
        ep.flush()
        info = mock_sender.get_sending_json_info(timeout=0.2)
        assert info.size == 1
        assert info.is_contain_user("test-user-2")
    assert mock_sender.closed


def test_event_processor_can_work_if_sender_error(event_processor, mock_sender):
    with event_processor as ep:
        mock_sender.fake_error = RuntimeError("test exception")
        ep.send_event(UserEvent(FBUser.from_dict(USER_1)))
        ep.flush()
        mock_sender.get_sending_json_info(timeout=0.2)

        mock_sender.fake_error = None
        ep.send_event(UserEvent(FBUser.from_dict(USER_2)))
        ep.flush()
        info = mock_sender.get_sending_json_info(timeout=0.2)
        assert info.size == 1
        assert info.is_contain_user("test-user-2")
    assert mock_sender.closed


def test_event_processor_cannot_send_anything_after_close(event_processor, mock_sender):
    assert mock_sender.get_sending_json_info(timeout=0.2) is None
    event_processor.stop()
    assert mock_sender.closed
    event_processor.send_event(UserEvent(FBUser.from_dict(USER_1)))
    event_processor.flush()
    assert mock_sender.get_sending_json_info(timeout=0.2) is None


def test_event_processor_events_keep_in_buffer_if_all_flush_payload_runner_are_busy(event_processor, mock_sender, ready_event):
    with event_processor as ep:
        mock_sender.thread_num = 5
        for _ in range(5):
            ep.send_event(UserEvent(FBUser.from_dict(USER_1)))
            ep.flush()
            mock_sender.get_sending_json_info(timeout=0.2)
        ready_event.wait()
        mock_sender.thread_num = 0
        ep.send_event(UserEvent(FBUser.from_dict(USER_2)))
        ep.flush()
        ep.send_event(UserEvent(FBUser.from_dict(USER_3)))
        ep.flush()
        sleep(0.1)
        mock_sender.notify_locked_thread()
        info = mock_sender.get_sending_json_info(timeout=0.2)
        assert info.size == 2
        assert info.is_contain_user("test-user-2")
        assert info.is_contain_user("test-user-3")
    assert mock_sender.closed
