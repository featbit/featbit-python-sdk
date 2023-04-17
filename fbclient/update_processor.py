from threading import Event
from fbclient.config import Config
from fbclient.interfaces import DataUpdateStatusProvider, UpdateProcessor
from fbclient.status_types import State


class NullUpdateProcessor(UpdateProcessor):

    def __init__(self, config: Config, dataUpdateStatusProvider: DataUpdateStatusProvider, ready: Event):
        self.__ready = ready
        self.__store = dataUpdateStatusProvider

    def start(self):
        self.__ready.set()
        self.__store.update_state(State.ok_state())

    def stop(self):
        pass

    @property
    def initialized(self) -> bool:
        return self.__ready.is_set()
