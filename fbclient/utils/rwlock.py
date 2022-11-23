"""
Internal helper class for Read-Write Lock.
Base in https://code.activestate.com/recipes/66426-readwritelock/
"""

import threading


class ReadWriteLock:
    """ A lock object that allows many simultaneous "read locks", but
    only one "write lock." """

    def __init__(self):
        self._read_ready = threading.Condition(threading.Lock())
        self._readers = 0

    def read_lock(self):
        """ Acquire a read lock. Blocks only if a thread has
        acquired the write lock. """
        with self._read_ready:
            self._readers += 1

    def release_read_lock(self):
        """ Release a read lock. """
        with self._read_ready:
            self._readers = self._readers - 1 if self._readers > 0 else 0
            if self._readers == 0:
                self._read_ready.notifyAll()

    def write_lock(self):
        """ Acquire a write lock. Blocks until there are no
        acquired read or write locks. """
        self._read_ready.acquire()
        while self._readers > 0:
            self._read_ready.wait()

    def release_write_lock(self):
        """ Release a write lock. """
        self._read_ready.release()
