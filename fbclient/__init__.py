from fbclient.client import FBClient
from fbclient.config import Config
from fbclient.utils.rwlock import ReadWriteLock
from fbclient.utils import log

"""Settings."""
start_wait = 15

__client = None
__config = None
__lock = ReadWriteLock()


def get() -> FBClient:
    """Returns the singleton Python SDK client instance, using the current configuration.

    To use the SDK as a singleton, first make sure you have called :func:`fbclient.set_config()`
    at startup time. Then :func:`fbclient.get()` will return the same shared :class:`fbclient.client.FBClient`
    instance each time. The client will be initialized if it runs first time.
    ```
    set_config(Config(env_secret, event_url, streaming_url))
    client = get()
    ```
    If you need to create multiple client instances with different environments, instead of this
    singleton approach you can call directly the :class:`fbclient.client.FBClient` constructor.
    """
    global __config
    global __client
    global __lock

    try:
        __lock.read_lock()
        if __client:
            return __client
        if not __config:
            raise Exception("config is not initialized")
    finally:
        __lock.release_read_lock()

    try:
        __lock.write_lock()
        if not __client:
            log.info("FB Python SDK: FB Python Client is initializing...")
            __client = FBClient(__config, start_wait)
        return __client
    finally:
        __lock.release_write_lock()


def set_config(config: Config):
    """Sets the configuration for the shared SDK client instance.

    If this is called prior to :func:`fbclient.get()`, it stores the configuration that will be used when the
    client is initialized. If it is called after the client has already been initialized, the client will be
    re-initialized with the new configuration.

    :param config: the client configuration
    """
    global __config
    global __client
    global __lock

    try:
        __lock.write_lock()
        if __client:
            __client.stop()
            log.info('FB Python SDK: FB Python Client is reinitializing...')
            __client = FBClient(config, start_wait)
    finally:
        __config = config
        __lock.release_write_lock()
