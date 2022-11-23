from threading import Event
from typing import Any, Callable, Dict, Optional, Tuple

from fbclient.data_storage import InMemoryDataStorage
from fbclient.interfaces import (DataStorage, DataUpdateStatusProvider,
                                 EventProcessor, Sender, UpdateProcessor)
from fbclient.utils import is_ascii, is_url

__all__ = ['Config', 'HTTPConfig', 'WebSocketConfig']

try:
    # https://websocket-client.readthedocs.io/en/latest/faq.html#why-is-this-library-slow
    import wsaccel  # noqa: F401

    def _skip_utf8_validation():  # type: ignore
        return False
except ImportError:
    def _skip_utf8_validation():
        return True


class WebSocketConfig:
    """
    FBClient websocket supports proxied connections, please read the details in https://websocket-client.readthedocs.io/en/latest/examples.html#connecting-through-a-proxy
    FBClient websocket supports ssl connection, please read the details in https://websocket-client.readthedocs.io/en/latest/faq.html#what-else-can-i-do-with-sslopts
    """

    def __init__(self,
                 timeout: float = 5.0,
                 sslopt: Optional[Dict[str, Any]] = None,
                 proxy_type: Optional[str] = None,
                 proxy_host: Optional[str] = None,
                 proxy_port: Optional[str] = None,
                 proxy_auth: Optional[Tuple[str, str]] = None):
        # a timeout is triggered if no connection response is received from the server after the timeout interval
        self.__timeout = 5.0 if timeout is None or timeout <= 0 else min(timeout, 10.0)
        self.__sslopt = sslopt
        self.__proxy_type = proxy_type
        self.__proxy_host = proxy_host
        self.__proxy_port = proxy_port
        self.__proxy_auth = proxy_auth

    @property
    def skip_utf8_validation(self) -> bool:
        return _skip_utf8_validation()

    @property
    def timeout(self) -> float:
        return self.__timeout

    @property
    def sslopt(self) -> Optional[Dict[str, Any]]:
        return self.__sslopt

    @property
    def proxy_type(self) -> Optional[str]:
        return self.__proxy_type

    @property
    def proxy_host(self) -> Optional[str]:
        return self.__proxy_host

    @property
    def proxy_port(self) -> Optional[str]:
        return self.__proxy_port

    @property
    def proxy_auth(self) -> Optional[Tuple[str, str]]:
        return self.__proxy_auth


class HTTPConfig:

    def __init__(self,
                 connect_timeout: float = 5.0,
                 read_timeout: float = 10.0,
                 http_proxy: Optional[str] = None,
                 http_proxy_auth: Optional[Tuple[str, str]] = None,
                 ca_certs: Optional[str] = None,
                 cert_file: Optional[str] = None,
                 disable_ssl_verification: bool = False):

        self.__connect_timeout = 5.0 if connect_timeout is None or connect_timeout <= 0 else connect_timeout
        self.__read_timeout = 10.0 if read_timeout is None or read_timeout <= 0 else read_timeout
        self.__http_proxy = http_proxy
        self.__http_proxy_auth = http_proxy_auth
        self.__ca_certs = ca_certs
        self.__cert_file = cert_file
        self.__disable_ssl_verification = disable_ssl_verification

    @property
    def connect_timeout(self) -> float:
        return self.__connect_timeout

    @property
    def read_timeout(self) -> float:
        return self.__read_timeout

    @property
    def http_proxy(self) -> Optional[str]:
        return self.__http_proxy

    @property
    def http_proxy_auth(self) -> Optional[Tuple[str, str]]:
        return self.__http_proxy_auth

    @property
    def ca_certs(self) -> Optional[str]:
        return self.__ca_certs

    @property
    def cert_file(self) -> Optional[str]:
        return self.__cert_file

    @property
    def disable_ssl_verification(self) -> bool:
        return self.__disable_ssl_verification


class Config:

    __STREAMING_PATH = '/streaming'
    __EVENTS_PATH = '/api/public/insight/track'

    def __init__(self,
                 env_secret: str,
                 event_url: str,
                 streaming_url: str,
                 streaming_first_retry_delay: float = 1.0,
                 events_max_in_queue: int = 10000,
                 events_flush_interval: float = 1.0,
                 events_retry_interval: float = 0.1,
                 events_max_retries: int = 1,
                 offline: bool = False,
                 data_storage: Optional[DataStorage] = None,
                 update_processor_imp: Optional[Callable[['Config', DataUpdateStatusProvider, Event], UpdateProcessor]] = None,
                 event_processor_imp: Optional[Callable[['Config', Sender], EventProcessor]] = None,
                 http: HTTPConfig = HTTPConfig(),
                 websocket: WebSocketConfig = WebSocketConfig(),
                 defaults: Optional[dict] = None):

        self.__env_secret = env_secret
        self.__event_url = event_url.rstrip('/')
        self.__streaming_url = streaming_url.rstrip('/')
        self.__streaming_first_retry_delay = 1.0 if streaming_first_retry_delay is None or streaming_first_retry_delay <= 0 else min(
            streaming_first_retry_delay, 60.0)
        self.__offline = offline
        self.__data_storage = data_storage if data_storage else InMemoryDataStorage()
        self.__event_processor_imp = event_processor_imp
        self.__update_processor_imp = update_processor_imp
        self.__events_max_in_queue = 10000 if events_max_in_queue is None else max(events_max_in_queue, 10000)
        self.__events_flush_interval = 1.0 if events_flush_interval is None or events_flush_interval <= 0 else min(
            events_flush_interval, 3.0)
        self.__events_retry_interval = 0.1 if events_retry_interval is None or events_retry_interval <= 0 else min(
            events_retry_interval, 1)
        self.__events_max_retries = 1 if events_max_retries is None or events_max_retries <= 0 else min(
            events_max_retries, 3)
        self.__http = http
        self.__websocket = websocket
        self.__defaults = defaults if defaults is not None else {}

    def copy_config_in_a_new_env(self, env_secret: str, defaults=None) -> 'Config':
        return Config(env_secret,
                      event_url=self.__event_url,
                      streaming_url=self.__streaming_url,
                      streaming_first_retry_delay=self.__streaming_first_retry_delay,
                      events_max_in_queue=self.__events_max_in_queue,
                      events_flush_interval=self.__events_flush_interval,
                      events_retry_interval=self.__events_retry_interval,
                      events_max_retries=self.__events_max_retries,
                      offline=self.__offline,
                      data_storage=self.__data_storage,
                      update_processor_imp=self.__update_processor_imp,
                      event_processor_imp=self.__event_processor_imp,
                      http=self.__http,
                      websocket=self.__websocket,
                      defaults=defaults if defaults is not None else self.__defaults)

    def get_default_value(self, key, default=None) -> Dict[str, Any]:
        return self.__defaults.get(key, default)

    @property
    def env_secret(self) -> str:
        return self.__env_secret

    @property
    def events_max_in_queue(self) -> int:
        return self.__events_max_in_queue

    @property
    def events_flush_interval(self) -> float:
        return self.__events_flush_interval

    @property
    def events_retry_interval(self) -> float:
        return self.__events_retry_interval

    @property
    def events_max_retries(self) -> int:
        return self.__events_max_retries

    @property
    def events_uri(self) -> str:
        return self.__event_url + self.__EVENTS_PATH

    @property
    def streaming_uri(self) -> str:
        return self.__streaming_url + self.__STREAMING_PATH

    @property
    def streaming_first_retry_delay(self) -> float:
        return self.__streaming_first_retry_delay

    @property
    def is_offline(self) -> bool:
        return self.__offline

    @property
    def data_storage(self) -> DataStorage:
        return self.__data_storage

    @property
    def update_processor_imp(self):
        return self.__update_processor_imp

    @property
    def event_processor_imp(self):
        return self.__event_processor_imp

    @property
    def http(self) -> HTTPConfig:
        return self.__http

    @property
    def websocket(self) -> WebSocketConfig:
        return self.__websocket

    def validate(self):
        if not is_ascii(self.__env_secret):
            raise ValueError('env secret is invalid')
        elif not is_url(self.__streaming_url) or not is_url(self.__event_url):
            raise ValueError('streaming or event url is invalid')
