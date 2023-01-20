import threading
from time import time
from typing import Mapping

from fbclient.category import Category
from fbclient.interfaces import DataStorage, DataUpdateStatusProvider
from fbclient.status_types import (DATA_STORAGE_INIT_ERROR,
                                   DATA_STORAGE_UPDATE_ERROR, State, StateType)
from fbclient.utils import log


class DataUpdateStatusProviderImpl(DataUpdateStatusProvider):

    def __init__(self, storage: DataStorage):
        self.__storage = storage
        self.__current_state = State.intializing_state()
        self.__lock = threading.Condition(threading.Lock())

    def init(self, all_data: Mapping[Category, Mapping[str, dict]], version: int = 0) -> bool:
        try:
            self.__storage.init(all_data, version)
        except Exception as e:
            self.__handle_exception(e, DATA_STORAGE_INIT_ERROR, str(e))
            return False
        return True

    def upsert(self, kind: Category, key: str, item: dict, version: int = 0) -> bool:
        try:
            self.__storage.upsert(kind, key, item, version)
        except Exception as e:
            self.__handle_exception(e, DATA_STORAGE_UPDATE_ERROR, str(e))
            return False
        return True

    def __handle_exception(self, error: Exception, error_type: str, message: str):
        log.exception('FB Python SDK: Data Storage error: %s, UpdateProcessor will attempt to receive the data' % str(error))
        self.update_state(State.interrupted_state(error_type, message))

    @property
    def initialized(self) -> bool:
        return self.__storage.initialized

    @property
    def latest_version(self) -> int:
        return self.__storage.latest_version

    @property
    def current_state(self) -> State:
        with self.__lock:
            return self.__current_state

    def update_state(self, new_state: State):
        if not new_state:
            return
        with self.__lock:
            old_state_type = self.__current_state.state_type
            new_state_type = new_state.state_type
            error = new_state.error_track
            # special case: if ``new_state`` is INTERRUPTED, but the previous state was INITIALIZING, the state will remain at INITIALIZING
            # INTERRUPTED is only meaningful after a successful startup
            if new_state_type == StateType.INTERRUPTED and old_state_type == StateType.INITIALIZING:
                new_state_type = StateType.INITIALIZING

            # normal case
            if new_state_type != old_state_type or error is not None:
                state_since = time() if new_state_type != old_state_type else self.__current_state.state_since
                self.__current_state = State(new_state_type, state_since, error)
                # wakes up all threads waiting for the ok state to check the new state
                self.__lock.notify_all()

    def wait_for_OKState(self, timeout: float = 0) -> bool:
        _timeout = 0 if timeout is None or timeout <= 0 else timeout
        deadline = time() + _timeout
        with self.__lock:
            while True:
                if StateType.OK == self.__current_state.state_type:
                    return True
                elif StateType.OFF == self.__current_state.state_type:
                    return False
                else:
                    if (_timeout == 0):
                        self.__lock.wait()
                    else:
                        now = time()
                        if now >= deadline:
                            return False
                        else:
                            delay = deadline - now
                            self.__lock.wait(delay + 0.001)
