from enum import Enum
from threading import Event
from time import time
from typing import Optional

from fbclient.common_types import _EvalResult, FBEvent, FBUser


class MessageType(Enum):
    FLAGS = 0
    FLUSH = 1
    SHUTDOWN = 2
    METRICS = 3
    USER = 4
    STATISTICS = 5


class EventMessage:
    def __init__(self, type: MessageType, event: Optional[FBEvent], await_termination: bool):
        self.__type = type
        self.__event = event
        self.__wait_lock = Event() if await_termination else None

    def completed(self):
        if self.__wait_lock:
            self.__wait_lock.set()

    def waitForComplete(self):
        if self.__wait_lock:
            self.__wait_lock.wait()

    @property
    def type(self) -> MessageType:
        return self.__type

    @property
    def event(self) -> Optional[FBEvent]:
        return self.__event


class FlagEventVariation:
    def __init__(self, variation: _EvalResult):
        self.__variation = variation
        self.__timestamp = int(round(time() * 1000))

    @property
    def variation(self) -> _EvalResult:
        return self.__variation

    @property
    def timestamp(self) -> int:
        return self.__timestamp


class Metric:
    def __init__(self, event_name: str, value: float):
        self.__event_name = event_name
        self.__value = value
        self.__route = 'index/metric'
        self.__type = 'CustomEvent'
        self.__app_type = 'pythonserverside'
        self.__timestamp = int(round(time() * 1000))

    @property
    def value(self) -> float:
        return self.__value

    @property
    def event_name(self) -> str:
        return self.__event_name

    @property
    def route(self) -> str:
        return self.__route

    @property
    def type(self) -> str:
        return self.__type

    @property
    def app_type(self) -> str:
        return self.__app_type

    @property
    def timestamp(self) -> int:
        return self.__timestamp


class UserEvent(FBEvent):
    def __init__(self, user: FBUser):
        super().__init__(user)

    def add(self, *elements) -> FBEvent:
        return self

    @property
    def is_send_event(self) -> bool:
        return self._user is not None

    def to_json_dict(self) -> dict:
        return {'user': self._user.to_json_dict()}


class FlagEvent(FBEvent):
    def __init__(self, user: FBUser):
        super().__init__(user)
        self.__variations = []

    def add(self, *elements) -> FBEvent:
        for element in elements:
            if isinstance(element, FlagEventVariation) and element.variation.is_success:
                self.__variations.append(element)
        return self

    @property
    def is_send_event(self) -> bool:
        return self._user and len(self.__variations) > 0

    def to_json_dict(self) -> dict:
        json_dict = {'user': self._user.to_json_dict()}
        arr = []
        for variation in self.__variations:
            flag_json_dict = {'featureFlagKey': variation.variation.key_name,
                              'sendToExperiment': variation.variation.is_send_to_expt,
                              'timestamp': variation.timestamp,
                              'variation': {
                                  'id': variation.variation.id,
                                  'value': variation.variation.value,
                                  'reason': variation.variation.reason
                              }}
            arr.append(flag_json_dict)
        json_dict['variations'] = arr  # type: ignore
        return json_dict


class MetricEvent(FBEvent):
    def __init__(self, user: FBUser):
        super().__init__(user)
        self.__metrics = []

    def add(self, *elements) -> FBEvent:
        for element in elements:
            if isinstance(element, Metric):
                self.__metrics.append(element)
        return self

    @property
    def is_send_event(self) -> bool:
        return self._user and len(self.__metrics) > 0

    def to_json_dict(self) -> dict:
        json_dict = {'user': self._user.to_json_dict()}
        arr = []
        for metric in self.__metrics:
            metric_json_dict = {'eventName': metric.event_name,
                                'numericValue': metric.value,
                                'route': metric.route,
                                'type': metric.type,
                                'appType': metric.app_type,
                                'timestamp': metric.timestamp}
            arr.append(metric_json_dict)
        json_dict['metrics'] = arr  # type: ignore
        return json_dict
