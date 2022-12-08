from threading import Event
from fbclient.config import Config
from fbclient.interfaces import DataUpdateStatusProvider, UpdateProcessor


class NullUpdateProcessor(UpdateProcessor):

    def __init__(self, config: Config, dataUpdateStatusProvider: DataUpdateStatusProvider, ready: Event):
        self.__ready = ready

    def start(self):
        self.__ready.set()

    def stop(self):
        pass

    @property
    def initialized(self) -> bool:
        return self.__ready.is_set()
