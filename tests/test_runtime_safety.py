import base64
import queue
import threading
from time import sleep
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fbclient.client import FBClient
from fbclient.config import Config, HTTPConfig
from fbclient.data_storage import InMemoryDataStorage
from fbclient.event_processor import NullEventProcessor
from fbclient.notice_broadcaster import NoticeBroadcater
from fbclient.status import DataUpdateStatusProviderImpl
from fbclient.status_types import State, StateType
from fbclient.streaming import Streaming
import fbclient.streaming as streaming_module
from fbclient.update_processor import NullUpdateProcessor
from fbclient.utils.http_client import build_http_factory
from fbclient.utils.repeatable_task import RepeatableTask


FAKE_ENV_SECRET = base64.b64encode(b"runtime-safety").decode()
FAKE_URL = "http://fake"
USER = {"key": "runtime-user", "name": "Runtime User"}


def make_offline_client():
    client = FBClient(Config(FAKE_ENV_SECRET,
                             event_url=FAKE_URL,
                             streaming_url=FAKE_URL,
                             offline=True))
    bootstrap = Path("tests/fbclient_test_data.json").read_text()
    assert client.initialize_from_external_json(bootstrap)
    return client


def featbit_thread_ids():
    return {
        thread.ident for thread in threading.enumerate()
        if thread.name.startswith("featbit-")
    }


def test_concurrent_evaluation_is_thread_safe():
    client = make_offline_client()

    def evaluate(worker):
        for index in range(1000):
            user = {
                "key": "worker-%s-%s" % (worker, index),
                "name": "Worker %s" % worker,
            }
            assert isinstance(client.variation("ff-test-bool", user, False), bool)
        return 1000

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            assert sum(executor.map(evaluate, range(8))) == 8000
    finally:
        client.stop()


def test_repeated_clients_release_all_sdk_threads():
    baseline = featbit_thread_ids()
    for _ in range(10):
        client = make_offline_client()
        client.stop()
        client.stop()
    assert featbit_thread_ids() == baseline


def test_repeatable_task_can_be_joined_cleanly():
    task = RepeatableTask("featbit-test-repeatable", 0.01, lambda: None)
    task.start()
    task.stop()
    assert not task.is_alive()


def test_notice_broadcaster_is_safe_during_listener_churn():
    broadcaster = NoticeBroadcater()
    callback_count = [0]
    callback_lock = threading.Lock()

    class Notice:
        notice_type = "test"

    def listener(_notice):
        with callback_lock:
            callback_count[0] += 1

    def churn(_worker):
        for _ in range(200):
            broadcaster.add_listener("test", listener)
            broadcaster.broadcast(Notice())
            broadcaster.remove_listener("test", listener)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(churn, range(8)))
    broadcaster.stop()
    broadcaster.stop()
    assert callback_count[0] >= 0


def test_notice_broadcast_cannot_be_overtaken_by_shutdown(monkeypatch):
    class PausingQueue:
        def __init__(self):
            self.inner = queue.Queue()
            self.target = None
            self.target_started = threading.Event()
            self.release_target = threading.Event()

        def put(self, item, *args, **kwargs):
            if item is self.target:
                self.target_started.set()
                self.release_target.wait(1.0)
            self.inner.put(item, *args, **kwargs)

        def get(self, *args, **kwargs):
            return self.inner.get(*args, **kwargs)

    controlled_queue = PausingQueue()
    monkeypatch.setattr("fbclient.notice_broadcaster.Queue",
                        lambda: controlled_queue)
    broadcaster = NoticeBroadcater()
    received = threading.Event()

    class Notice:
        notice_type = "test"

    notice = Notice()
    controlled_queue.target = notice
    broadcaster.add_listener("test", lambda _notice: received.set())

    broadcaster_thread = threading.Thread(
        target=lambda: broadcaster.broadcast(notice)
    )
    broadcaster_thread.start()
    assert controlled_queue.target_started.wait(1.0)

    stopped = threading.Event()

    def stop_broadcaster():
        broadcaster.stop()
        stopped.set()

    stopper = threading.Thread(target=stop_broadcaster)
    stopper.start()
    assert not stopped.wait(0.05)
    controlled_queue.release_target.set()
    broadcaster_thread.join(1.0)
    stopper.join(1.0)
    assert stopped.is_set()
    assert received.wait(1.0)


def test_client_public_event_and_shutdown_calls_do_not_raise():
    class FailingEventProcessor:
        def send_event(self, _event):
            raise RuntimeError("send failed")

        def flush(self):
            raise RuntimeError("flush failed")

        def stop(self):
            raise RuntimeError("stop failed")

    def build_event_processor(_config, _sender):
        return FailingEventProcessor()

    config = Config(FAKE_ENV_SECRET,
                    event_url=FAKE_URL,
                    streaming_url=FAKE_URL,
                    update_processor_imp=NullUpdateProcessor,
                    event_processor_imp=build_event_processor)
    client = FBClient(config)
    client.identify(USER)
    client.track_metric(USER, "metric")
    client.track_metrics(USER, {"metric": 1.0})
    client.flush()
    client.stop()
    client.stop()


def test_status_listener_can_reenter_client_stop_without_deadlock():
    stopped_components = []

    class NotifyingUpdateProcessor:
        def __init__(self, _config, status_provider, ready):
            self.status_provider = status_provider
            self.ready = ready

        def start(self):
            self.ready.set()
            self.status_provider.update_state(State.ok_state())

        def stop(self):
            stopped_components.append("update")
            self.status_provider.update_state(State.normal_off_state())

        @property
        def initialized(self):
            return True

    config = Config(FAKE_ENV_SECRET,
                    event_url=FAKE_URL,
                    streaming_url=FAKE_URL,
                    update_processor_imp=NotifyingUpdateProcessor,
                    event_processor_imp=lambda config, sender: NullEventProcessor(config, sender))
    client = FBClient(config)
    listener_states = []

    def on_status_change(state):
        listener_states.append(state.state_type)
        if state.state_type == StateType.OFF:
            client.stop()

    client.update_status_provider.add_listener(on_status_change)
    completed = threading.Event()

    def stop_client():
        client.stop()
        completed.set()

    thread = threading.Thread(target=stop_client, daemon=True)
    thread.start()
    assert completed.wait(1.0)
    thread.join(1.0)
    assert not thread.is_alive()
    assert listener_states == [StateType.OFF]
    assert stopped_components == ["update"]


def test_concurrent_client_stop_waits_for_cleanup():
    stop_entered = threading.Event()
    release_stop = threading.Event()

    class BlockingUpdateProcessor:
        def __init__(self, _config, status_provider, ready):
            self.status_provider = status_provider
            self.ready = ready

        def start(self):
            self.ready.set()
            self.status_provider.update_state(State.ok_state())

        def stop(self):
            stop_entered.set()
            release_stop.wait(1.0)

        @property
        def initialized(self):
            return True

    config = Config(
        FAKE_ENV_SECRET,
        event_url=FAKE_URL,
        streaming_url=FAKE_URL,
        update_processor_imp=BlockingUpdateProcessor,
        event_processor_imp=lambda config, sender: NullEventProcessor(
            config, sender
        ),
    )
    client = FBClient(config)
    first_done = threading.Event()
    second_done = threading.Event()
    first = threading.Thread(
        target=lambda: (client.stop(), first_done.set())
    )
    second = threading.Thread(
        target=lambda: (client.stop(), second_done.set())
    )
    first.start()
    assert stop_entered.wait(1.0)
    second.start()
    assert not second_done.wait(0.05)
    release_stop.set()
    first.join(1.0)
    second.join(1.0)
    assert first_done.is_set()
    assert second_done.is_set()


def test_streaming_stop_interrupts_network_wait(monkeypatch):
    connected = threading.Event()

    class FakeWebSocketApp:
        def __init__(self, _url, **_kwargs):
            self.closed = threading.Event()
            self.sock = None

        def run_forever(self, **_kwargs):
            connected.set()
            self.closed.wait(10.0)

        def close(self, status=None):
            self.closed.set()

    monkeypatch.setattr("fbclient.streaming.websocket.WebSocketApp",
                        FakeWebSocketApp)
    config = Config(FAKE_ENV_SECRET,
                    event_url=FAKE_URL,
                    streaming_url=FAKE_URL)
    broadcaster = NoticeBroadcater()
    status = DataUpdateStatusProviderImpl(InMemoryDataStorage())
    streaming = Streaming(config, broadcaster, status, threading.Event())
    streaming.start()
    assert connected.wait(1.0)
    streaming.stop()
    broadcaster.stop()
    assert not streaming.is_alive()


def test_default_config_objects_are_not_shared():
    left = Config(FAKE_ENV_SECRET, FAKE_URL, FAKE_URL)
    right = Config(FAKE_ENV_SECRET, FAKE_URL, FAKE_URL)
    assert left.http is not right.http
    assert left.websocket is not right.websocket


def test_config_copy_uses_independent_storage_and_exact_queue_capacity():
    original = Config(FAKE_ENV_SECRET, FAKE_URL, FAKE_URL,
                      events_max_in_queue=1,
                      defaults={"flag": {"nested": True}})
    copied = original.copy_config_in_a_new_env(
        base64.b64encode(b"other-environment").decode()
    )
    assert original.events_max_in_queue == 1
    assert copied.events_max_in_queue == 1
    assert copied.data_storage is not original.data_storage
    assert copied.http is not original.http
    assert copied.websocket is not original.websocket


def test_http_client_uses_configured_client_certificate():
    config = Config(FAKE_ENV_SECRET, FAKE_URL, FAKE_URL,
                    http=HTTPConfig(cert_file="client.pem"))
    manager = build_http_factory(config).create_http_client()
    try:
        assert manager.connection_pool_kw["cert_file"] == "client.pem"
    finally:
        manager.clear()


def test_terminal_streaming_error_does_not_report_initialized(monkeypatch):
    ready = threading.Event()

    class InvalidRequestWebSocketApp:
        def __init__(self, _url, **callbacks):
            self.on_close = callbacks["on_close"]
            self.sock = None

        def run_forever(self, **_kwargs):
            self.on_close(self, 4003, "invalid request")

        def close(self, status=None):
            pass

    monkeypatch.setattr("fbclient.streaming.websocket.WebSocketApp",
                        InvalidRequestWebSocketApp)
    status = DataUpdateStatusProviderImpl(InMemoryDataStorage())
    broadcaster = NoticeBroadcater()
    streaming = Streaming(Config(FAKE_ENV_SECRET, FAKE_URL, FAKE_URL),
                          broadcaster, status, ready)
    streaming.start()
    streaming.join(1.0)
    try:
        assert ready.is_set()
        assert not streaming.initialized
        assert not streaming.is_alive()
    finally:
        streaming.stop()
        broadcaster.stop()


def test_streaming_constructor_failures_use_backoff(monkeypatch):
    attempts = [0]

    def fail_constructor(*_args, **_kwargs):
        attempts[0] += 1
        raise RuntimeError("constructor failed")

    monkeypatch.setattr("fbclient.streaming.websocket.WebSocketApp",
                        fail_constructor)
    config = Config(FAKE_ENV_SECRET, FAKE_URL, FAKE_URL,
                    streaming_first_retry_delay=0.05)
    broadcaster = NoticeBroadcater()
    streaming = Streaming(config, broadcaster,
                          DataUpdateStatusProviderImpl(InMemoryDataStorage()),
                          threading.Event())
    streaming.start()
    sleep(0.12)
    streaming.stop()
    broadcaster.stop()
    assert 1 <= attempts[0] <= 4


def test_streaming_restores_websocket_global_timeout_after_open(monkeypatch):
    import websocket

    opened = threading.Event()
    original_timeout = websocket.getdefaulttimeout()

    class OpenWebSocketApp:
        def __init__(self, _url, **callbacks):
            self.on_open = callbacks["on_open"]
            self.closed = threading.Event()
            self.sock = None

        def run_forever(self, **_kwargs):
            self.on_open(self)
            opened.set()
            self.closed.wait(1.0)

        def send(self, _message):
            pass

        def close(self, status=None):
            self.closed.set()

    monkeypatch.setattr("fbclient.streaming.websocket.WebSocketApp",
                        OpenWebSocketApp)
    broadcaster = NoticeBroadcater()
    streaming = Streaming(Config(FAKE_ENV_SECRET, FAKE_URL, FAKE_URL),
                          broadcaster,
                          DataUpdateStatusProviderImpl(InMemoryDataStorage()),
                          threading.Event())
    streaming.start()
    assert opened.wait(1.0)
    try:
        assert websocket.getdefaulttimeout() == original_timeout
    finally:
        streaming.stop()
        broadcaster.stop()


def test_streaming_does_not_block_on_another_clients_timeout_lock(monkeypatch):
    connected = threading.Event()

    class OpenWebSocketApp:
        def __init__(self, _url, **callbacks):
            self.on_open = callbacks["on_open"]
            self.closed = threading.Event()
            self.sock = None

        def run_forever(self, **_kwargs):
            self.on_open(self)
            connected.set()
            self.closed.wait(1.0)

        def send(self, _message):
            pass

        def close(self, status=None):
            self.closed.set()

    monkeypatch.setattr("fbclient.streaming.websocket.WebSocketApp",
                        OpenWebSocketApp)
    assert streaming_module._WEBSOCKET_TIMEOUT_LOCK.acquire(timeout=1.0)
    broadcaster = NoticeBroadcater()
    streaming = Streaming(
        Config(FAKE_ENV_SECRET, FAKE_URL, FAKE_URL),
        broadcaster,
        DataUpdateStatusProviderImpl(InMemoryDataStorage()),
        threading.Event(),
    )
    try:
        streaming.start()
        assert connected.wait(1.0)
    finally:
        streaming.stop()
        broadcaster.stop()
        streaming_module._WEBSOCKET_TIMEOUT_LOCK.release()
