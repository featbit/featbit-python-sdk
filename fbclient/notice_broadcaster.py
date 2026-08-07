
from queue import Queue
from threading import Lock, Thread, current_thread
from typing import Callable
from fbclient.interfaces import Notice

from fbclient.utils import log


class NoticeBroadcater:
    def __init__(self):
        self.__notice_queue = Queue()
        self.__closed = False
        self.__listeners = {}
        self.__lock = Lock()
        self.__stop_notice = object()
        self.__thread = Thread(name='featbit-notice-broadcaster',
                               daemon=True,
                               target=self.__run)
        log.debug('notice broadcaster starting...')
        self.__thread.start()

    def add_listener(self, notice_type: str, listener: Callable[[Notice], None]):
        if isinstance(notice_type, str) and notice_type.strip() and listener is not None:
            log.debug('add a listener for notice type %s' % notice_type)
            with self.__lock:
                if self.__closed:
                    return
                if notice_type not in self.__listeners:
                    self.__listeners[notice_type] = []
                # Preserve the existing contract: registering the same
                # callable multiple times produces the same number of
                # notifications.
                self.__listeners[notice_type].append(listener)

    def remove_listener(self, notice_type: str, listener: Callable[[Notice], None]):
        if listener is None:
            return
        log.debug('remove a listener for notice type %s' % notice_type)
        with self.__lock:
            notifiers = self.__listeners.get(notice_type)
            if not notifiers:
                return
            try:
                notifiers.remove(listener)
            except ValueError:
                return
            if not notifiers:
                del self.__listeners[notice_type]

    def broadcast(self, notice: Notice):
        with self.__lock:
            if self.__closed:
                return
            # Keep acceptance and enqueue atomic with stop(). Otherwise the
            # shutdown sentinel can overtake the final accepted notice.
            self.__notice_queue.put(notice)

    def stop(self):
        log.debug('notice broadcaster stopping...')
        with self.__lock:
            if self.__closed:
                return
            self.__closed = True
        self.__notice_queue.put(self.__stop_notice)
        if current_thread() is not self.__thread:
            self.__thread.join(5.0)
            if self.__thread.is_alive():
                log.warning('FB Python SDK: notice broadcaster did not stop in time')

    def __run(self):
        while True:
            notice = self.__notice_queue.get(block=True, timeout=None)
            if notice is self.__stop_notice:
                return
            self.__notice_process(notice)

    def __notice_process(self, notice: Notice):
        with self.__lock:
            listeners = tuple(self.__listeners.get(notice.notice_type, ()))
        for listener in listeners:
            try:
                listener(notice)
            except Exception as e:
                log.exception('FB Python SDK: unexpected error in handle notice %s: %s' % (notice.notice_type, str(e)))
