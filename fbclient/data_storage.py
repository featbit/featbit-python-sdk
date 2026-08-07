from collections import defaultdict
from typing import Mapping, Optional

from fbclient.category import Category
from fbclient.interfaces import DataStorage
from fbclient.utils.rwlock import ReadWriteLock


class InMemoryDataStorage(DataStorage):

    def __init__(self):
        self.__rw_lock = ReadWriteLock()
        self.__initialized = False
        self.__version = 0
        # initialized with a function (“default factory”) that provides the default value for a nonexistent key.
        self.__storage = defaultdict(dict)

    def get(self, kind: Category, key: str) -> Optional[dict]:
        try:
            self.__rw_lock.read_lock()
            keyItems = self.__storage.get(kind, {})
            item = keyItems.get(key, None)
            if (item is None) or item['isArchived']:
                return None
            return item
        finally:
            self.__rw_lock.release_read_lock()

    def get_all(self, kind: Category) -> Mapping[str, dict]:
        try:
            self.__rw_lock.read_lock()
            keyItems = self.__storage.get(kind, {})
            return dict((k, v) for k, v in keyItems.items() if not v['isArchived'])
        finally:
            self.__rw_lock.release_read_lock()

    def init(self, all_data: Mapping[Category, Mapping[str, dict]], version: int = 0) -> bool:
        if (not all_data) or not isinstance(version, int) or version < 0:
            return False
        snapshot_is_empty = not any(bool(items) for items in all_data.values())
        # A version-zero snapshot is valid only when the environment is empty.
        # This is how the service represents a successful full sync containing
        # no flags or segments.
        if version == 0 and not snapshot_is_empty:
            return False
        try:
            self.__rw_lock.write_lock()
            if self.__initialized:
                if (version == self.__version == 0
                        and snapshot_is_empty
                        and not any(bool(items)
                                    for items in self.__storage.values())):
                    # Empty environments repeatedly send the same version-zero
                    # full snapshot after reconnecting. Treat it as an accepted
                    # no-op instead of forcing another reconnect.
                    return True
                if version <= self.__version:
                    return False
            self.__storage.clear()
            self.__storage.update(all_data)  # type: ignore
            self.__initialized = True
            self.__version = version
            return True
        finally:
            self.__rw_lock.release_write_lock()

    def upsert(self, kind: Category, key: str, item: dict, version: int = 0) -> bool:
        if (not kind) or (not item) or (not key) or not isinstance(version, int) or version <= 0:
            return False
        try:
            self.__rw_lock.write_lock()
            keyItems = self.__storage[kind]
            v = keyItems.get(key, None)
            # Patches are versioned per entity. Comparing with the global
            # latest version would incorrectly discard a different flag or
            # segment that happens to have the same timestamp.
            if v is not None and v.get('timestamp', 0) >= version:
                return False
            keyItems[key] = item
            self.__version = max(self.__version, version)
            if not self.__initialized:
                self.__initialized = True
            return True
        finally:
            self.__rw_lock.release_write_lock()

    @property
    def initialized(self) -> bool:
        try:
            self.__rw_lock.read_lock()
            return self.__initialized
        finally:
            self.__rw_lock.release_read_lock()

    @property
    def latest_version(self) -> int:
        try:
            self.__rw_lock.read_lock()
            return self.__version
        finally:
            self.__rw_lock.release_read_lock()

    def stop(self):
        pass


class NullDataStorage(DataStorage):

    def get(self, kind: Category, key: str) -> Optional[dict]:
        return None

    def get_all(self, kind: Category) -> Mapping[str, dict]:
        return dict()

    def init(self, all_data: Mapping[Category, Mapping[str, dict]], version: int = 0) -> bool:
        return True

    def upsert(self, kind: Category, key: str, item: dict, version: int = 0) -> bool:
        return True

    @property
    def initialized(self) -> bool:
        return True

    @property
    def latest_version(self) -> int:
        return 0

    def stop(self):
        pass
