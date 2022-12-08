from enum import Enum
from time import time
from typing import Optional

DATA_STORAGE_INIT_ERROR = 'Data Storage init error'

DATA_STORAGE_UPDATE_ERROR = 'Data Storage update error'

REQUEST_INVALID_ERROR = 'Request invalid'

DATA_INVALID_ERROR = 'Received Data invalid'

NETWORK_ERROR = 'Network error'

RUNTIME_ERROR = 'Runtime error'

WEBSOCKET_ERROR = 'WebSocket error'

UNKNOWN_ERROR = 'Unknown error'

UNKNOWN_CLOSE_CODE = 'Unknown close code'

SYSTEM_ERROR = 'System error'

SYSTEM_QUIT = 'System quit'


class StateType(Enum):
    """
    The initial state of the update processing when the SDK is being initialized.
    If it encounters an error that requires it to retry initialization, the state will remain at
    INITIALIZING until it either succeeds and becomes OK, or permanently fails and becomes OFF.
    """
    INITIALIZING = 1
    """
    Indicates that the update processing is currently operational and has not had any problems since the
    last time it received data.
    In streaming mode, this means that there is currently an open stream connection and that at least
    one initial message has been received on the stream.
    """
    OK = 2
    """
    Indicates that the update processing encountered an error that it will attempt to recover from.
    In streaming mode, this means that the stream connection failed, or had to be dropped due to some
    other error, and will be retried after a backoff delay.
    """
    INTERRUPTED = 3
    """
    Indicates that the update processing has been permanently shut down.
    This could be because it encountered an unrecoverable error or because the SDK client was
    explicitly shut down.
    """
    OFF = 4


class ErrorTrack:
    def __init__(self, error_type: str, message: str):
        self.__error_type = error_type
        self.__message = message

    @property
    def error_type(self) -> str:
        return self.__error_type

    @property
    def message(self) -> str:
        return self.__message


class State:
    def __init__(self, state_type: "StateType", state_since: float, error_track: Optional["ErrorTrack"] = None):
        self.__state_type = state_type
        self.__state_since = state_since
        self.__error_track = error_track

    @property
    def state_type(self) -> "StateType":
        return self.__state_type

    @property
    def state_since(self) -> float:
        return self.__state_since

    @property
    def error_track(self) -> Optional["ErrorTrack"]:
        return self.__error_track

    @staticmethod
    def intializing_state() -> "State":
        return State(StateType.INITIALIZING, time())

    @staticmethod
    def ok_state() -> "State":
        return State(StateType.OK, time())

    @staticmethod
    def interrupted_state(error_type: str, message: str) -> "State":
        return State(StateType.INTERRUPTED, time(), ErrorTrack(error_type, message))

    @staticmethod
    def normal_off_state() -> "State":
        return State(StateType.OFF, time())

    @staticmethod
    def error_off_state(error_type: str, message: str) -> "State":
        return State(StateType.OFF, time(), ErrorTrack(error_type, message))
