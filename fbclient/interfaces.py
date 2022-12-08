from abc import ABC, abstractmethod
from typing import Mapping, Optional

from fbclient.category import Category
from fbclient.common_types import FBEvent
from fbclient.status_types import State


class UpdateProcessor(ABC):
    '''
    Interface for the component that obtains feature flag data in some way and passes it to a
    :class:`DataStorage`. The built-in imp now of this is streaming, we will provide the polling update
    and file update soon
    '''

    @abstractmethod
    def start(self):
        '''
        Starts an operation in the background.
        '''
        pass

    @abstractmethod
    def stop(self):
        '''
        Stops an operation running in the background.
        '''
        pass

    @property
    @abstractmethod
    def initialized(self) -> bool:
        """
        Returns whether the update processor has received feature flags/values and has initialized its storage.
        """
        pass


class DataUpdateStatusProvider(ABC):
    '''
    Interface for manipulating the data updates in :class: `DataStorage` and maintain the status of :class: `UpdateProcessor`.
    The implementation should be called in :class: `UpdateProcessor`.
    '''

    @abstractmethod
    def init(self, all_data: Mapping[Category, Mapping[str, dict]], version: int = 0) -> bool:
        """
        Manipulate the init operation in data storage. If the underlying data storage throws an error during this operation, the SDK will catch it, log it,
        and set the state of update process to INTERRUPTED. It will not rethrow the error to other level, but will simply return falseto indicate that the operation failed.

        :param all_data: all data to be stored
        :param version: the version of this data set
        :return: True if the update succeeded
        """
        pass

    @abstractmethod
    def upsert(self, kind: Category, key: str, item: dict, version: int = 0) -> bool:
        """
        Manipuate the upsert operation in data storage. If the underlying data storage throws an error during this operation, the SDK will catch it, log it,
        and set the state of update process to INTERRUPTED. It will not rethrow the error to other level, but will simply return falseto indicate that the operation failed.

        :param kind: The kind of data to update
        :param key: The unique key of the data
        :param item: The data to update or insert
        :param version: the version of this data set
        :return: True if the update succeeded
        """
        pass

    @property
    @abstractmethod
    def initialized(self) -> bool:
        """
        Returns whether the storage has been initialized yet or not
        """
        pass

    @property
    @abstractmethod
    def latest_version(self) -> int:
        """
        return the latest version of the data storage
        """
        pass

    @property
    @abstractmethod
    def current_state(self) -> State:
        """
        Returns the current status of the update processing
        All of the :class:`UpdateProcessor` implementations should update this status,
        whenever they successfully initialize, encounter an error, or recover after an error.
        If not, the status will always be reported as INITIALIZING.

        :return: the current state
        """
        pass

    @abstractmethod
    def update_state(self, new_state: State):
        """
        Informs the SDK of a change of status in the update processing. Implementations should use this method,
        if they have any concept of being in a valid state, a temporarily disconnected state, or a permanently stopped state.
        If ``new_state`` is different from the previous state, and/or ``error`` is non-null, the SDK will start returning the new status
        (adding a timestamp for the change).
        A special case is that if ``new_state`` is INTERRUPTED, but the previous state was INITIALIZING, the state will remain at INITIALIZING
        because INTERRUPTED is only meaningful after a successful startup.

        :param new_state: the new state of update processing
        """
        pass

    @abstractmethod
    def wait_for_OKState(self, timeout: float) -> bool:
        """
        A method for waiting for a OK state arival
        If the current state is already OK when this method is called, it immediately returns.
        Otherwise, it blocks until 1. the state has become OK, 2. the state has become
        OFF, 3. the specified timeout elapses, 4. the current thread is interrupted by some reason

        :param timeout: the maximum amount of time to wait or to block indefinitely if the timeout is zero or negative.
        :return: True if the state is OK; False if the state is OFF or timeout elapses
        """
        pass


class DataStorage(ABC):
    """
    Interface for a versioned store for feature flags and related data received from feature flag center.
    Implementations should permit concurrent access and updates.
    This is an internal interface only implemented and used in SDK

    An "data", for ``DataStorage``, is simply a dict of data which must have at least
    three properties: ``id`` (its unique key), ``version`` or ``timestamp``(the version number provided by
    feature flag center), and ``isArchived`` (True if this is a placeholder for a deleted data).

    init and upsert requests are version-based: if the version number in the request is less than
    the currently stored version of the data, the call should be ignored.
    """

    @abstractmethod
    def get(self, kind: Category, key: str) -> Optional[dict]:
        """
        Retrieves the data to which the specified key is mapped, or None if the key is not found
        or the associated data has a ``isArchived`` property of True.

        :param kind: The kind of data to get
        :param key: The key whose associated data is to be returned
        :return: the data received from feature flag center
        """

    @abstractmethod
    def get_all(self, kind: Category) -> Mapping[str, dict]:
        """
        Retrieves a dictionary of all associated data of a given kind except the data with a ``isArchived`` property of True.

        :param kind: The kind of data to get
        :return: the data received from feature flag center
        """
        pass

    @abstractmethod
    def init(self, all_data: Mapping[Category, Mapping[str, dict]], version: int = 0):
        """
        Init (or re-init by data update process) the storage with the specified set of data.
        Any existing entries will be removed if the new data set's version is greater than the current version


        :param all_data: All data to be stored
        :param version: the version of this data set
        """
        pass

    @abstractmethod
    def upsert(self, kind: Category, key: str, item: dict, version: int = 0):
        """
        Updates or inserts the data associated with the specified key. If an item with the same key
        already exists, it should update it only if the new item's ``version`` property is greater than the current version

        :param kind: The kind of data to update
        :param key: The unique key of the data
        :param item: The data to update or insert
        :param version: the version of this data set
        """
        pass

    @property
    @abstractmethod
    def initialized(self) -> bool:
        """
        Returns whether the storage has been initialized yet or not
        """
        pass

    @property
    @abstractmethod
    def latest_version(self) -> int:
        """
        Returns the latest version of this date storage
        """
        pass

    @abstractmethod
    def stop(self):
        """
        Shuts down the date storage
        """
        pass


class EventProcessor(ABC):
    """
    Interface for a component to send analytics events.
    """

    @abstractmethod
    def send_event(self, event: FBEvent):
        """
        Processes an event to be sent at some point.

        :param event: The event to send
        """
        pass

    @abstractmethod
    def flush(self):
        """
        Specifies that any buffered events should be sent as soon as possible, rather than waiting
        for the next flush interval. This method is asynchronous, so events still may not be sent
        until a later time. However, calling ``stop()`` will synchronously deliver any events that were
        not yet delivered prior to shutting down.
        """
        pass

    @abstractmethod
    def stop(self):
        """
        Shuts down the event processor after first delivering all pending events.
        """
        pass


class Sender(ABC):
    """
    interface for a component to send request to feature flag center. It's mainly internal use, for example sending events, requesting
    the latest version of feature flags, etc.
    """

    @abstractmethod
    def postJson(self, url: str, json_str: str, fetch_response: bool = True) -> Optional[str]:
        """
        Sends a json object via HTTP POST to the given URL

        :param url: The URL to send the json
        :param json_str: The json to send data
        :param fetch_response: Whether to fetch the response or not
        :return: The response, normally it'a json string or None; if fetch_response is False, return None
        """
        pass

    @abstractmethod
    def stop(self):
        """
        Shuts down the connection to feature flag center
        """
        pass
