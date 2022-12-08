import json
from queue import Queue
from threading import Condition, Event, Lock
from time import sleep
from typing import List, Mapping, Optional, Union

import certifi
import urllib3
from fbclient.config import Config, HTTPConfig
from fbclient.interfaces import Sender
from fbclient.utils import build_headers, log


def build_http_factory(config: Config, headers={}):
    return HTTPFactory(build_headers(config.env_secret, headers), config.http)


class HTTPFactory:

    def __init__(self, headers, http_config: HTTPConfig):
        """
        :param override_read_timeout override default read timeout at streaming update
        """
        self.__headers = headers
        self.__http_config = http_config
        self.__timeout = urllib3.Timeout(connect=http_config.connect_timeout, read=http_config.read_timeout)

    @property
    def headers(self) -> Mapping[str, str]:
        return self.__headers

    @property
    def http_config(self) -> HTTPConfig:
        return self.__http_config

    @property
    def timeout(self) -> urllib3.Timeout:
        return self.__timeout

    def create_http_client(self, num_pools=1, max_size=10) -> Union[urllib3.PoolManager, urllib3.ProxyManager]:
        proxy_url = self.__http_config.http_proxy

        if self.__http_config.disable_ssl_verification:
            cert_reqs = 'CERT_NONE'
            ca_certs = None
        else:
            cert_reqs = 'CERT_REQUIRED'
            ca_certs = self.__http_config.ca_certs or certifi.where()

        if not proxy_url:
            return urllib3.PoolManager(num_pools=num_pools,
                                       maxsize=max_size,
                                       headers=self.__headers,
                                       timeout=self.__timeout,
                                       cert_reqs=cert_reqs,
                                       ca_certs=ca_certs)
        else:
            url = urllib3.util.parse_url(proxy_url)
            if url.auth:
                proxy_headers = urllib3.util.make_headers(proxy_basic_auth=url.auth)
            elif self.__http_config.http_proxy_auth:
                auth = self.__http_config.http_proxy_auth
                proxy_headers = urllib3.util.make_headers(proxy_basic_auth=f"{auth[0]}:{auth[1]}")
            else:
                proxy_headers = None

            return urllib3.ProxyManager(proxy_url,
                                        num_pools=num_pools,
                                        maxsize=max_size,
                                        headers=self.__headers,
                                        proxy_headers=proxy_headers,
                                        timeout=self.__timeout,
                                        cert_reqs=cert_reqs,
                                        ca_certs=ca_certs)


class DefaultSender(Sender):

    def __init__(self, name: str, config: Config, num_pools=1, max_size=10):
        self.__http = build_http_factory(config).create_http_client(num_pools, max_size)
        self.__retry_interval = config.events_retry_interval
        self.__max_retries = config.events_max_retries
        self.__name = name

    def postJson(self, url: str, json_str: str, fetch_response: bool = True) -> Optional[str]:
        for i in range(self.__max_retries + 1):
            try:
                if i > 0:
                    sleep(self.__retry_interval)
                response = self.__http.request('POST', url, body=json_str)
                if response.status == 200:
                    log.debug('sending ok')
                    resp = response.data.decode('utf-8')
                    return resp if fetch_response else None
            except Exception as e:
                log.exception('FB Python SDK: sending error: %s' % str(e))
        return None

    def stop(self):
        log.debug('%s sender is stopping...' % self.__name)
        self.__http.clear()


class SendingJsonInfo:
    def __init__(self, payloads: List[dict]) -> None:
        self.__payloads = payloads
        self.size = len(payloads)

    def is_contain_user(self, key: str) -> bool:
        return any(payload['user']['keyId'] == key for payload in self.__payloads)


class MockSender(Sender):
    def __init__(self, ready: Event):
        self.__ready = ready
        self.__lock = Condition(Lock())
        self.__buffer = Queue(maxsize=100)
        self.thread_num = 0
        self.fake_error = None
        self.fake_error_on_close = None
        self.closed = False

    def postJson(self, url: str, json_str: str, fetch_response: bool = True) -> Optional[str]:
        payloads = json.loads(json_str)
        self.__buffer.put(SendingJsonInfo(payloads))
        if self.thread_num > 0 and not self.__ready.is_set():
            with self.__lock:
                self.thread_num = self.thread_num - 1
                if self.thread_num <= 0:
                    self.__ready.set()
                self.__lock.wait()
        if self.fake_error is not None:
            raise self.fake_error  # type: ignore
        return None

    def notify_locked_thread(self):
        with self.__lock:
            self.__lock.notify_all()

    def get_sending_json_info(self, timeout: float) -> Optional[SendingJsonInfo]:
        try:
            return self.__buffer.get(timeout=timeout)
        except:
            return None

    def stop(self):
        self.closed = True
        if self.fake_error_on_close is not None:
            raise self.fake_error_on_close  # type: ignore
