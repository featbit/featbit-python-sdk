import json
import threading
from distutils.util import strtobool
from typing import Any, Mapping, Optional, Tuple

from fbclient.category import FEATURE_FLAGS, SEGMENTS
from fbclient.common_types import AllFlagStates, FBUser, FlagState, _EvalResult
from fbclient.config import Config
from fbclient.data_storage import NullDataStorage
from fbclient.evaluator import (REASON_CLIENT_NOT_READY, REASON_ERROR,
                                REASON_FLAG_NOT_FOUND,
                                REASON_USER_NOT_SPECIFIED, Evaluator)
from fbclient.event_processor import DefaultEventProcessor, NullEventProcessor
from fbclient.event_types import FlagEvent, Metric, MetricEvent, UserEvent
from fbclient.interfaces import DataUpdateStatusProvider
from fbclient.status import DataUpdateStatusProviderImpl
from fbclient.status_types import State
from fbclient.streaming import Streaming, _data_to_dict
from fbclient.update_processor import NullUpdateProcessor
from fbclient.utils import (cast_variation_by_flag_type, check_uwsgi, log,
                            simple_type_inference, valide_all_data)
from fbclient.utils.http_client import DefaultSender


class FBClient:
    """The FeatBit Python SDK client object.

    Applications SHOULD instantiate a single instance for the lifetime of the application.
    In the case where an application needs to evaluate feature flags from different environments,
    you may create multiple clients, but they should still be retained for the lifetime of the application
    rather than created per request or per thread.

    Client instances are thread-safe.
    """

    def __init__(self, config: Config, start_wait: float = 15.):
        """
        Creates a new client to connect to feature flag center with a specified configuration.

        Unless client is configured in offline mode, this client try to connect to feature flag center as soon as the constructor is called.

        The constructor will return when it successfully connects, or when the timeout (default: 15 seconds) expires, whichever comes first.
        ```
        client = FBClient(Config(env_secret, event_url, streaming_url), start_wait=15)

        if client.initialize:
            # your code
        ```

        If it has not succeeded in connecting when the timeout elapses, you will receive the client in an uninitialized state where feature flags will return default values;
        it will still continue trying to connect in the background unless there has been an unrecoverable error or you close the client by :func:`stop`.
        You can detect whether initialization has succeeded by :func:`initialize`.

        If you prefer to have the constructor return immediately, and then wait for initialization to finish at some other point,
        you can use :func:`update_status_provider` as follows:
        ```
        client = FBClient(Config(env_secret, event_url, streaming_url), start_wait=0)
        if client._update_status_provider.wait_for_OKState():
            # your code
        ```
        :param config: the client configuration
        :param start_wait: the max time to wait for initialization
        """
        check_uwsgi()

        if not isinstance(config, Config):
            raise ValueError("Config is not valid")

        self._config = config
        self._config.validate()

        # init components
        # event processor
        self._event_processor = self._build_event_processor(config)
        self._event_handler = lambda event: self._event_processor.send_event(event)
        # data storage
        self._data_storage = config.data_storage
        # evaluator
        self._evaluator = Evaluator(lambda key: self._data_storage.get(FEATURE_FLAGS, key),
                                    lambda key: self._data_storage.get(SEGMENTS, key))
        # data updator and status provider
        self._update_status_provider = DataUpdateStatusProviderImpl(config.data_storage)
        # update processor
        update_processor_ready = threading.Event()
        self._update_processor = self._build_update_processor(config, self._update_status_provider,
                                                              update_processor_ready)
        self._update_processor.start()

        if start_wait > 0:
            if not isinstance(self._update_processor, NullUpdateProcessor):
                log.info("FB Python SDK: Waiting for Client initialization in %s seconds" % str(start_wait))

            if isinstance(self._data_storage, NullDataStorage):
                log.info("FB Python SDK: SDK just returns default variation")

            update_processor_ready.wait(start_wait)
            if self._config.is_offline:
                log.info("FB Python SDK: SDK is in offline mode")
            elif self._update_processor.initialized:
                log.info("FB Python SDK: SDK initialization is completed")
            else:
                log.warning("FB Python SDK: SDK was not successfully initialized")
        else:
            log.info("FB Python SDK: SDK starts in asynchronous mode")

    def _build_event_processor(self, config: Config):
        if config.event_processor_imp:
            log.debug("Using user-specified event processor: %s" % str(config.event_processor_imp))
            return config.event_processor_imp(config, DefaultSender('insight', config, max_size=10))

        if config.is_offline:
            log.debug("Offline mode, SDK disable event processing")
            return NullEventProcessor(config, DefaultSender('insight', config, max_size=10))

        return DefaultEventProcessor(config, DefaultSender('insight', config, max_size=10))

    def _build_update_processor(self, config: Config, update_status_provider, update_processor_event):
        if config.update_processor_imp:
            log.debug("Using user-specified update processor: %s" % str(config.update_processor_imp))
            return config.update_processor_imp(config, update_status_provider, update_processor_event)

        if config.is_offline:
            log.debug("Offline mode, SDK disable streaming data updating")
            return NullUpdateProcessor(config, update_status_provider, update_processor_event)

        return Streaming(config, update_status_provider, update_processor_event)

    @property
    def initialize(self) -> bool:
        """Returns true if the client has successfully connected to feature flag center.

        If this returns false, it means that the client has not yet successfully connected to  feature flag center.
        It might still be in the process of starting up, or it might be attempting to reconnect after an
        unsuccessful attempt, or it might have received an unrecoverable error and given up.
        """
        return self._update_processor.initialized

    @property
    def update_status_provider(self) -> DataUpdateStatusProvider:
        return self._update_status_provider

    def stop(self):
        """Releases all threads and network connections used by SDK.

        Do not attempt to use the client after calling this method.
        """
        log.info("FB Python SDK: Python SDK client is closing...")
        self._data_storage.stop()
        self._update_processor.stop()
        self._event_processor.stop()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.stop()

    def is_offline(self) -> bool:
        """Returns true if the client is in offline mode.
        """
        return self._config.is_offline

    def _get_flag_internal(self, key: str) -> Optional[dict]:
        return self._data_storage.get(FEATURE_FLAGS, key)

    def __handle_default_value(self, key: str, default: Any) -> Tuple[Optional[str], Optional[str]]:
        default_value = self._config.get_default_value(key, default)
        default_value_type = simple_type_inference(default_value)
        if default_value is None:
            return None, None
        elif default_value_type == 'boolean':
            return default_value_type, str(default).lower()
        elif default_value_type == 'json':
            return default_value_type, json.dumps(default_value)
        else:
            return default_value_type, str(default_value)

    def _evaluate_internal(self, key: str, user: dict, default: Any = None) -> _EvalResult:
        default_value_type, default_value = self.__handle_default_value(key, default)
        try:
            if not self.initialize:
                log.warning('FB Python SDK: Evaluation called before Java SDK client initialized for feature flag, well using the default value')
                return _EvalResult.error(default_value, REASON_CLIENT_NOT_READY, key, default_value_type)

            if not key:
                log.warning('FB Python SDK: null feature flag key; returning default value')
                return _EvalResult.error(default_value, REASON_FLAG_NOT_FOUND, key, default_value_type)

            flag = self._get_flag_internal(key)
            if not flag:
                log.warning('FB Python SDK: Unknown feature flag %s; returning default value' % key)
                return _EvalResult.error(default_value, REASON_FLAG_NOT_FOUND, key, default_value_type)

            try:
                fb_user = FBUser.from_dict(user)
            except ValueError as ve:
                log.warning('FB Python SDK: %s' % str(ve))
                return _EvalResult.error(default_value, REASON_USER_NOT_SPECIFIED, key, default_value_type)

            fb_event = FlagEvent(fb_user)
            er = self._evaluator.evaluate(flag, fb_user, fb_event)
            self._event_handler(fb_event)
            return er

        except Exception as e:
            log.exception('FB Python SDK: unexpected error in evaluation: %s' % str(e))
            return _EvalResult.error(default_value, REASON_ERROR, key, default_value_type)

    def variation(self, key: str, user: dict, default: Any = None) -> Any:
        """Return the variation of a feature flag for a given user.

        This method will send an event back to feature flag center immediately if no error occurs.

        The result of the flag evaluation will be converted to:
        1: string if the feature flag is a string type
        2: bool if the feature flag is a boolean type
        3: Python object if the feature flag is a json type
        4: float/int if the feature flag is a numeric type

        :param key: the unique key for the feature flag
        :param user:  the attributes of the user
        :param default: the default value of the flag, to be used if the return value is not available
        :return: one of the flag's values in any type in any type of string, bool, json(Python object), and float
        or the default value if flag evaluation fails
        """
        er = self._evaluate_internal(key, user, default)
        return cast_variation_by_flag_type(er.flag_type, er.value)

    def variation_detail(self, key: str, user: dict, default: Any = None) -> FlagState:
        """"Return the variation of a feature flag for a given user, but also provides additional information
         about how this value was calculated, in the property `data` of the :class:`fbclient.common_types.FlagState`.

        This method will send an event back to feature flag center immediately if no error occurs.

        :param key: the unique key for the feature flag
        :param user: the attributes of the user
        :param default: the default value of the flag, to be used if the return value is not available
        :return: an :class:`fbclient.common_types.FlagState` object
        """
        return self._evaluate_internal(key, user, default).to_flag_state

    def is_enabled(self, key: str, user: dict) -> bool:
        """
        Return the bool value for a feature flag for a given user. it's strongly recommended to call this method
        only in a bool feature flag, otherwise the results may not be what you expect

        This method will send an event back to feature flag center immediately if no error occurs.

        :param key: the unique key for the feature flag
        :param user: the attributes of the user
        :return: True or False

        """
        try:
            value = self.variation(key, user, False)
            return bool(strtobool(str(value)))
        except ValueError:
            return False

    def get_all_latest_flag_variations(self, user: dict) -> AllFlagStates:
        """
        Returns an object that encapsulates the state of all feature flags for a given user

        This method does not send events back to feature flag center immediately util calling :func:`fbcclient.common_types.AllFlagStates.get()`

        :param user: the attributes of the user
        :return: an :class:`fbcclient.common_types.AllFlagStates` object (will never be None; its `success` property will be False
        if SDK has not been initialized or the user invalid)
        """
        all_flag_details = {}
        message = ""
        success = True
        try:
            if not self.initialize:
                log.warning('FB Python SDK: Evaluation called before Java SDK client initialized for feature flag')
                message = REASON_CLIENT_NOT_READY
                success = False
            else:
                try:
                    fb_user = FBUser.from_dict(user)
                    all_flags = self._data_storage.get_all(FEATURE_FLAGS)
                    for flag in all_flags.values():
                        fb_event = FlagEvent(fb_user)
                        er = self._evaluator.evaluate(flag, fb_user, fb_event)
                        all_flag_details[er.to_evail_detail] = fb_event
                except ValueError as ve:
                    log.warning('FB Python SDK: %s' % str(ve))
                    message = REASON_USER_NOT_SPECIFIED
                    success = False
                except:
                    raise
        except Exception as e:
            log.exception('FB Python SDK: unexpected error in evaluation: %s' % str(e))
            message = REASON_ERROR
            success = False
        return AllFlagStates(success, message, all_flag_details, self._event_handler)

    def is_flag_known(self, key: str) -> bool:
        """
        Checks if the given flag exists in the your environment

        :param key: The key name of the flag to check
        :return: True if the flag exists
        """
        try:
            if not self.initialize:
                log.warning('FB Python SDK: isFlagKnown called before Java SDK client initialized for feature flag')
                return False
            return self._get_flag_internal(key) is not None
        except Exception as e:
            log.exception('FB Python SDK: unexpected error in is_flag_known: %s' % str(e))
        return False

    def flush(self):
        """Flushes all pending events.

        Normally, batches of events are delivered in the background at intervals determined by the
        `events_flush_interval` property of :class:`fbclient.config.Config`. Calling `flush()`
        schedules the next event delivery to be as soon as possible; however, the delivery still
        happens asynchronously on a thread, so this method will return immediately.
        """
        self._event_processor.flush()

    def identify(self, user: dict):
        """register an end user in the feature flag center

        :param user: the attributes of the user
        """
        try:
            fb_user = FBUser.from_dict(user)
        except ValueError:
            log.warning('FB Python SDK: user invalid')
            return

        self._event_handler(UserEvent(fb_user))

    def track_metric(self, user: dict, event_name: str, metric_value: float = 1.0):
        """Tracks that a user performed a metric event.

        Our feature flag center supports to track pageviews and clicks that are specified in the dashboard UI.
        This can be used to track custom metric.

        :param user: the attributes of the user
        :param event_name: the name of the event, which may correspond to a goal in A/B tests
        :param metric_value: a numeric value used by the experiment, default value is 1.0
        """
        if not event_name or metric_value <= 0:
            log.warning('FB Python SDK: event/metric invalid')
            return
        try:
            fb_user = FBUser.from_dict(user)
        except ValueError:
            log.warning('FB Python SDK: user invalid')
            return

        fb_user = FBUser.from_dict(user)
        metric_event = MetricEvent(fb_user).add(Metric(event_name, metric_value))
        self._event_handler(metric_event)

    def track_metrics(self, user: dict, metrics: Mapping[str, float]):
        """Tracks that a user performed a map of metric events.

        if any event_name or metric_value is invalid, that metric will be ignored

        :param user: the attributes of the user
        :param metrics: the pairs of event_name and metric_value
        """
        if not isinstance(metrics, dict):
            log.warning('FB Python SDK: metrics invalid')
            return
        try:
            fb_user = FBUser.from_dict(user)
        except ValueError:
            log.warning('FB Python SDK: user invalid')
            return

        metric_event = MetricEvent(fb_user)
        for event_name, metric_value in metrics.items():
            if event_name and metric_value > 0:
                metric_event.add(Metric(event_name, metric_value))
        self._event_handler(metric_event)

    def initialize_from_external_json(self, json_str: str) -> bool:
        """SDK initialization in the offline mode, this method is mainly used for tests

        :param json_str: feature flags, segments...etc in the json format
        :return: True if the initialization is well done
        """
        if self._config.is_offline and json_str:
            all_data = json.loads(json_str)
            if valide_all_data(all_data):
                version, data = _data_to_dict(all_data['data'])
                res = self._update_status_provider.init(data, version)
                if res:
                    self._update_status_provider.update_state(State.ok_state())
                return res

        return False
