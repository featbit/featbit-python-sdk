from threading import Event
from fbclient.config import Config
from fbclient.interfaces import DataUpdateStatusProvider, UpdateProcessor
from fbclient.status_types import State


class NullUpdateProcessor(UpdateProcessor):

    def __init__(self, config: Config, dataUpdateStatusProvider: DataUpdateStatusProvider, ready: Event):
        self.__ready = ready
        self.__store = dataUpdateStatusProvider
        self.__offline = config.is_offline

    def start(self):
        self.__ready.set()
        # Offline mode is not initialized until bootstrap data is loaded.
        # Custom online null processors retain their historical ready behavior.
        if not self.__offline or self.__store.initialized:
            self.__store.update_state(State.ok_state())

    def stop(self):
        pass

    @property
    def initialized(self) -> bool:
        return self.__store.initialized if self.__offline else self.__ready.is_set()
