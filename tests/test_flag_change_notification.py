

from queue import Empty, Queue

import pytest

from fbclient.flag_change_notification import (FlagChangedListener,
                                               FlagChangedNotice, FlagTracker)
from fbclient.interfaces import Notice
from fbclient.notice_broadcaster import NoticeBroadcater

TEST_NOTICE_TYPE = 'test_notice_type'


class TestNotice(Notice):
    # https://stackoverflow.com/questions/62460557/cannot-collect-test-class-testmain-because-it-has-a-init-constructor-from
    __test__ = False

    def __init__(self, notice_type: str, content: str):
        self.__notice_type = notice_type
        self.__content = content

    @property
    def notice_type(self) -> str:
        return self.__notice_type

    @property
    def content(self) -> str:
        return self.__content


class FakeFlagChangedListener(FlagChangedListener):
    __test__ = False

    def __init__(self, queue: Queue):
        self.__queue = queue

    def on_flag_change(self, notice: FlagChangedNotice):
        self.__queue.put(notice)


@pytest.fixture
def queue():
    return Queue()


def test_register_a_listener(queue):
    notice_broadcaster = NoticeBroadcater()
    notice_broadcaster.add_listener(TEST_NOTICE_TYPE, queue.put)
    notice_broadcaster.add_listener(TEST_NOTICE_TYPE, queue.put)
    notice_broadcaster.add_listener(TEST_NOTICE_TYPE, queue.put)

    notice = TestNotice(TEST_NOTICE_TYPE, 'test content')
    notice_broadcaster.broadcast(notice)

    assert queue.get() == notice
    assert queue.get() == notice
    assert queue.get() == notice

    notice_broadcaster.stop()


def test_unregister_a_listener(queue):
    notice_broadcaster = NoticeBroadcater()
    notice_broadcaster.add_listener(TEST_NOTICE_TYPE, queue.put)
    notice_broadcaster.add_listener(TEST_NOTICE_TYPE, queue.put)
    notice_broadcaster.add_listener(TEST_NOTICE_TYPE, queue.put)
    notice_broadcaster.remove_listener(TEST_NOTICE_TYPE, queue.put)

    notice = TestNotice(TEST_NOTICE_TYPE, 'test content')
    notice_broadcaster.broadcast(notice)

    assert queue.get() == notice
    assert queue.get() == notice

    with pytest.raises(Empty):
        queue.get(timeout=0.01)

    notice_broadcaster.stop()


def test_register_a_flag_changed_listener(queue):
    notice_broadcaster = NoticeBroadcater()
    flag_changed_listener = FakeFlagChangedListener(queue)
    flag_tracker = FlagTracker(notice_broadcaster, None)  # type: ignore
    flag_tracker.add_flag_changed_listener(flag_changed_listener)
    flag_tracker.add_flag_changed_listener(flag_changed_listener)
    flag_tracker.add_flag_changed_listener(flag_changed_listener)

    notice = FlagChangedNotice('test_flag_key')
    notice_broadcaster.broadcast(notice)

    assert queue.get() == notice
    assert queue.get() == notice
    assert queue.get() == notice

    notice_broadcaster.stop()


def test_unregister_a_flag_changed_listener(queue):
    notice_broadcaster = NoticeBroadcater()
    flag_changed_listener = FakeFlagChangedListener(queue)
    flag_tracker = FlagTracker(notice_broadcaster, None)  # type: ignore
    flag_tracker.add_flag_changed_listener(flag_changed_listener)
    flag_tracker.add_flag_changed_listener(flag_changed_listener)
    flag_tracker.add_flag_changed_listener(flag_changed_listener)
    flag_tracker.remove_flag_change_notifier(flag_changed_listener)

    notice = FlagChangedNotice('test_flag_key')
    notice_broadcaster.broadcast(notice)

    assert queue.get() == notice
    assert queue.get() == notice

    with pytest.raises(Empty):
        queue.get(timeout=0.01)

    notice_broadcaster.stop()
