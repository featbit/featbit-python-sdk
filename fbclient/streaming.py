import json
from threading import Event, Thread
from time import sleep
from typing import Optional, Tuple

import websocket
from websocket._exceptions import WebSocketException

from fbclient.category import FEATURE_FLAGS, SEGMENTS
from fbclient.config import Config
from fbclient.interfaces import DataUpdateStatusProvider, UpdateProcessor
from fbclient.status_types import (DATA_INVALID_ERROR, NETWORK_ERROR,
                                   REQUEST_INVALID_ERROR, RUNTIME_ERROR,
                                   SYSTEM_QUIT, UNKNOWN_CLOSE_CODE,
                                   UNKNOWN_ERROR, WEBSOCKET_ERROR, State)
from fbclient.utils import (build_headers, build_token,
                            from_str_datetime_to_millis, log, valide_all_data)
from fbclient.utils.exponential_backoff_jitter_strategy import \
    BackoffAndJitterStrategy
from fbclient.utils.repeatable_task import RepeatableTask

WS_NORMAL_CLOSE = 1000

WS_GOING_AWAY_CLOSE = 1001

WS_INVALID_REQUEST_CLOSE = 4003


class _SelfClosed:
    def __init__(self,
                 is_self_close: bool = False,
                 is_reconn: bool = False,
                 state: Optional[State] = None):
        self.is_self_close = is_self_close
        self.is_reconn = is_reconn
        self.state = state

    def __call__(self):
        return self.is_self_close


def _data_to_dict(data: dict) -> tuple[int, dict]:
    version = 0
    all_data = {}
    flags = {}
    segments = {}
    all_data[FEATURE_FLAGS] = flags
    all_data[SEGMENTS] = segments
    for flag in data['featureFlags']:
        flag['timestamp'] = from_str_datetime_to_millis(flag['updatedAt'])
        flag['variationMap'] = dict((var['id'], var['value']) for var in flag['variations'])
        flag['_id'] = flag['id']
        flag['id'] = flag['key']
        flags[flag['id']] = {'id': flag['id'], 'timestamp': flag['timestamp'], 'isArchived': True} if flag['isArchived'] else flag
        version = max(version, flag['timestamp'])
    for segment in data['segments']:
        segment['timestamp'] = from_str_datetime_to_millis(segment['updatedAt'])
        segments[segment['id']] = {'id': segment['id'], 'timestamp': segment['timestamp'], 'isArchived': True} if segment['isArchived'] else segment
        version = max(version, segment['timestamp'])
    return version, all_data


def _handle_ws_error(error: BaseException) -> Tuple[bool, bool, State]:
    if isinstance(error, WebSocketException):
        return True, False, State.interrupted_state(WEBSOCKET_ERROR, str(error))
    if isinstance(error, ConnectionError):
        return True, False, State.interrupted_state(NETWORK_ERROR, str(error))
    # internal use for test
    if isinstance(error, (KeyboardInterrupt, SystemExit)):
        return False, False, State.error_off_state(SYSTEM_QUIT, str(error))
    # an unexpected error occurs when the custom action is called, close ws connection to jump ws client forever loop
    return True, True, State.interrupted_state(RUNTIME_ERROR, str(error))


class Streaming(Thread, UpdateProcessor):
    __ping_interval = 10.0

    def __init__(self, config: Config, dataUpdateStatusProvider: DataUpdateStatusProvider, ready: Event):
        super().__init__(daemon=True)
        self.__config = config
        self.__storage = dataUpdateStatusProvider
        self.__ready = ready
        self.__running = True
        self.__strategy = BackoffAndJitterStrategy(config.streaming_first_retry_delay)
        self.__wsapp = None
        self.__self_closed = _SelfClosed()
        self.__closed_by_error = False
        self.__force_close = False
        self.__has_network = not config.is_offline
        if self.__has_network:
            self.__ping_task = RepeatableTask('streaming ping', self.__ping_interval, self._on_ping)
            self.__ping_task.start()

    def _init_wsapp(self):

        # authenfication and headers
        token = build_token(self.__config.env_secret)
        params = '?token=%s&type=server' % token
        url = self.__config.streaming_uri + params
        headers = build_headers(self.__config.env_secret)

        # a timeout is triggered if no connection response is received
        websocket.setdefaulttimeout(self.__config.websocket.timeout)
        # init web socket app
        self.__wsapp = websocket.WebSocketApp(url,
                                              header=headers,
                                              on_open=self._on_open,
                                              on_message=self._on_message,
                                              on_close=self._on_close,
                                              on_error=self._on_error)
        # set the conn time
        self.__strategy.set_good_run()
        log.debug('Streaming WebSocket is connecting...')

    def run(self):
        while (not self.__force_close and self.__running and self.__has_network):
            try:
                self._init_wsapp()
                self.__wsapp.run_forever(sslopt=self.__config.websocket.sslopt,  # type: ignore
                                         http_proxy_host=self.__config.websocket.proxy_host,
                                         http_proxy_port=self.__config.websocket.proxy_port,
                                         http_proxy_auth=self.__config.websocket.proxy_auth,
                                         proxy_type=self.__config.websocket.proxy_type,
                                         skip_utf8_validation=self.__config.websocket.skip_utf8_validation)
                if self.__running:
                    # calculate the delay for reconn
                    delay = self.__strategy.next_delay()
                    sleep(delay)
            except Exception as e:
                log.exception('FB Python SDK: Streaming unexpected error: %s', str(e))
                self.__storage.update_state(State.error_off_state(UNKNOWN_ERROR, str(e)))
            finally:
                # clear the last connection state
                self.__wsapp = None
                self.__self_closed = _SelfClosed()
                self.__closed_by_error = False
        log.debug('Streaming WebSocket process is over')
        if not self.__ready.is_set():
            # if an error like data format invalid occurs in the first attempt, set ready to make client not to wait
            self.__ready.set()

    # handle websocket auto close issue
    def _on_ping(self):
        if self.__wsapp and self.__wsapp.sock and self.__wsapp.sock.connected:
            log.trace('ping')  # type: ignore
            self.__wsapp.send(json.dumps({'messageType': 'ping', 'data': None}))

    def _on_close(self, wsapp, close_code, close_msg):
        if self.__self_closed():
            # close by client
            self.__running = self.__self_closed.is_reconn
            state = self.__self_closed.state
            log.debug('Streaming WebSocket close reason: self close')
        elif self.__closed_by_error:
            return
        elif close_code == WS_INVALID_REQUEST_CLOSE:
            # close by server with code 4003
            self.__running = False
            state = State.error_off_state(REQUEST_INVALID_ERROR, REQUEST_INVALID_ERROR)
            log.debug('Streaming WebSocket close reason: %s' % REQUEST_INVALID_ERROR)
        else:
            # close by server with an unknown close code, restart immediately
            self.__running = True
            msg = close_msg if close_msg else UNKNOWN_CLOSE_CODE
            state = State.interrupted_state(UNKNOWN_CLOSE_CODE, msg)
            log.debug('Streaming WebSocket close reason: %s' % close_code)

        if state:
            self.__storage.update_state(state)

    def _on_error(self, wsapp: websocket.WebSocketApp, error):
        is_reconn, is_close_ws, state = _handle_ws_error(error)
        log.warning('FB Python SDK: Streaming WebSocket Failure: %s' % str(error))
        if is_close_ws:
            self.__self_closed = _SelfClosed(is_self_close=True, is_reconn=is_reconn, state=state)
            wsapp.close(status=WS_GOING_AWAY_CLOSE)
        else:
            self.__running = is_reconn
            self.__closed_by_error = True
            self.__storage.update_state(state)

    def _on_open(self, wsapp: websocket.WebSocketApp):
        log.debug('Asking Data updating on WebSocket')
        version = self.__storage.latest_version if self.__storage.latest_version > 0 else 0
        data_sync_msg = {'messageType': 'data-sync', 'data': {'timestamp': version}}
        json_str = json.dumps(data_sync_msg)
        wsapp.send(json_str)

    def _on_process_data(self, data):

        log.debug('Streaming WebSocket is processing data')
        version, all_data = _data_to_dict(data)
        op_ok = False
        if 'patch' == data['eventType']:
            op_ok = all(self.__storage.upsert(cat, item['id'], item, item['timestamp'])
                        for cat, items in all_data.items() for item in sorted(items.values(), key=lambda x: x['timestamp']))
        else:
            op_ok = self.__storage.init(all_data, version)
        if op_ok:
            if not self.__ready.is_set():
                # set ready when the initialization is complete.
                self.__ready.set()
            self.__storage.update_state(State.ok_state())
            log.debug("processing data is well done")
        return op_ok

    def _on_message(self, wsapp: websocket.WebSocketApp, msg):
        log.trace('Streaming WebSocket data: %s' % msg)  # type: ignore
        try:
            all_data = json.loads(msg)
            if valide_all_data(all_data) and not self._on_process_data(all_data['data']) and self.__wsapp:
                # state already updated in init or upsert, just reconn
                self.__self_closed = _SelfClosed(is_self_close=True, is_reconn=True, state=None)
                wsapp.close(status=WS_GOING_AWAY_CLOSE)
        except Exception as e:
            if isinstance(e, json.JSONDecodeError):
                self.__self_closed = _SelfClosed(is_self_close=True, is_reconn=False, state=State.error_off_state(DATA_INVALID_ERROR, str(e)))
                wsapp.close(status=WS_GOING_AWAY_CLOSE)

    def stop(self):
        log.info('FB Python SDK: Streaming is stopping...')
        self.__force_close = True
        if self.__running and self.__wsapp:
            self.__self_closed = _SelfClosed(is_self_close=True, is_reconn=False, state=State.normal_off_state())
            self.__wsapp.close(status=WS_NORMAL_CLOSE)
        if self.__has_network:
            self.__ping_task.stop()

    @property
    def initialized(self) -> bool:
        return self.__ready.is_set() and self.__storage.initialized
