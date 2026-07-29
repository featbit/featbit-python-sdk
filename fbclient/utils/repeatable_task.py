"""
Internal helper class for a simple periodic task.
base in https://medium.com/greedygame-engineering/an-elegant-way-to-run-periodic-tasks-in-python-61b7c477b679
"""

from threading import Event, Thread, current_thread
from time import time
from typing import Callable

from fbclient.utils import log


class RepeatableTask(Thread):

    def __init__(self, name: str, interval: float, callable: Callable, args=(), kwargs=None):
        super().__init__(name=name, daemon=True)
        self._interval = interval
        self._callable = callable
        # ``Thread`` already has a private ``_stop()`` method which is used by
        # ``join()``.  Keeping an Event under that name makes joining the task
        # fail with ``TypeError: 'Event' object is not callable``.
        self._stop_event = Event()
        self._args = args
        self._kwargs = {} if kwargs is None else kwargs

    def stop(self, timeout: float = 5.0):
        log.info("FB Python SDK: %s repeatable task is stopping..." % self.name)
        self._stop_event.set()
        if current_thread() is not self and self.is_alive():
            self.join(timeout)
            if self.is_alive():
                log.warning("FB Python SDK: %s repeatable task did not stop in time" % self.name)

    def run(self):
        log.debug("%s repeatable task is starting..." % self.name)
        stopped = self._stop_event.is_set()
        while not stopped:
            next_time = time() + self._interval
            try:
                self._callable(*self._args, **self._kwargs)
            except Exception as e:
                log.exception("FB Python SDK: unexpected exception on %s repeatable task: %s" % (self.name, str(e)))
            delay = next_time - time()
            stopped = self._stop_event.wait(delay) if delay > 0 else self._stop_event.is_set()
