
from queue import Empty, Queue
from threading import Thread
from typing import Callable
from fbclient.interfaces import Notice

from fbclient.utils import log


class NoticeBroadcater:
    def __init__(self):
        self.__notice_queue = Queue()
        self.__closed = False
        self.__listeners = {}
        self.__thread = Thread(daemon=True, target=self.__run)
        log.debug('notice broadcaster starting...')
        self.__thread.start()

    def add_listener(self, notice_type: str, listener: Callable[[Notice], None]):
        if isinstance(notice_type, str) and notice_type.strip() and listener is not None:
            log.debug('add a listener for notice type %s' % notice_type)
            if notice_type not in self.__listeners:
                self.__listeners[notice_type] = []
            self.__listeners[notice_type].append(listener)

    def remove_listener(self, notice_type: str, listener: Callable[[Notice], None]):
        if notice_type in self.__listeners and listener is not None:
            log.debug('remove a listener for notice type %s' % notice_type)
            notifiers = self.__listeners[notice_type]
            if not notifiers:
                del self.__listeners[notice_type]
            else:
                notifiers.remove(listener)

    def broadcast(self, notice: Notice):
        self.__notice_queue.put(notice)

    def stop(self):
        log.debug('notice broadcaster stopping...')
        self.__closed = True
        self.__thread.join()

    def __run(self):
        while not self.__closed:
            try:
                notice = self.__notice_queue.get(block=True, timeout=1)
                self.__notice_process(notice)
            except Empty:
                pass

    def __notice_process(self, notice: Notice):
        if notice.notice_type in self.__listeners:
            for listerner in self.__listeners[notice.notice_type]:
                try:
                    listerner(notice)
                except Exception as e:
                    log.exception('FB Python SDK: unexpected error in handle notice %s: %s' % (notice.notice_type, str(e)))
