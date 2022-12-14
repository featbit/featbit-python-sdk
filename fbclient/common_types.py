import json
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Iterable, Mapping, Optional

from fbclient.utils import cast_variation_by_flag_type, is_numeric

__BUILTINS_MAPING__ = {'key': 'keyid',
                       'name': 'name',
                       'keyid': 'keyid'}

__NO_VARIATION__ = 'NE'

__FLAG_KEY_UNKNOWN__ = 'flag key unknown'

__FLAG_NAME_UNKNOWN__ = 'flag name unknown'

__FLAG_VALUE_UNKNOWN__ = 'flag value unknown'


class Jsonfy(ABC):

    @abstractmethod
    def to_json_dict(self) -> dict:
        pass

    def to_json_str(self) -> str:
        return json.dumps(self.to_json_dict())


class FBUser(Jsonfy):

    def __init__(self, key: Optional[str], name: Optional[str], **kwargs):
        self._check_argument(key, 'key is not valid')
        self._check_argument(name, 'name is not valid')
        self._commons = {}
        self._commons['keyid'] = key
        self._commons['name'] = name
        self._customs = {}
        if len(kwargs) > 0:
            self._customs \
                .update(dict((k, str(v)) for k, v in kwargs.items() if isinstance(k, str) and k.lower() not in __BUILTINS_MAPING__.keys()
                             and (isinstance(v, str) or is_numeric(v) or isinstance(v, bool))))

    @staticmethod
    def from_dict(user: Dict[str, Any]) -> "FBUser":
        user_copy = {}
        if not isinstance(user, dict):
            raise ValueError('user is not valid')
        user_copy.update(user)
        key = user_copy.pop('key', None) or user_copy.pop('keyid', None)
        name = user_copy.pop('name', None)
        return FBUser(key, name, **user_copy)

    def _check_argument(self, value, msg) -> bool:
        if isinstance(value, str) and value.strip():
            return True
        raise ValueError(msg)

    def get(self, prop: str, default=None) -> Optional[str]:
        if not isinstance(prop, str):
            return default

        if prop in self._commons:
            return self._commons[prop]

        if prop.lower() in __BUILTINS_MAPING__:
            return self._commons.get(__BUILTINS_MAPING__[prop.lower()], default)

        return self._customs.get(prop, default)

    def to_json_dict(self) -> dict:
        json_dict = {}
        json_dict['keyId'] = self._commons['keyid']
        json_dict['name'] = self._commons['name']
        json_dict['customizedProperties'] = [{'name': k, 'value': v} for k, v in self._customs.items()]
        return json_dict


class EvalDetail(Jsonfy):
    """
    The object combining the result of a flag evaluation with information about how it was calculated.
    The result of the flag evaluation should be converted to:
        1: string if the feature flag is a string type
        2: bool if the feature flag is a boolean type
        3: Python object if the feature flag is a json type
        4: float if the feature flag is a numeric type
    """

    def __init__(self,
                 reason: str,
                 variation: Any,
                 key_name: Optional[str] = None,
                 name: Optional[str] = None):
        """Constructs an instance.

        :param id: variation id
        :param reason: main factor that influenced the flag evaluation value
        :param variation: result of the flag evaluation in any type of string, bool, float/int, json(Python object) or default value if flag evaluation fails
        :param key_name: key name of the flag
        :param name: name of the flag
        """
        self._reason = reason
        self._variation = variation
        self._key_name = key_name
        self._name = name

    @property
    def reason(self) -> str:
        """A string describing the main factor that influenced the flag evaluation value.
        """
        return self._reason

    @property
    def variation(self) -> Any:
        """The result of the flag evaluation in any type of string, bool, float/int, json(Python object)
        or default value if flag evaluation fails
        """
        return self._variation

    @property
    def key_name(self) -> Optional[str]:
        """The flag key name
        """
        return self._key_name

    @property
    def name(self) -> Optional[str]:
        """The flag name
        """
        return self._name

    def to_json_dict(self) -> dict:
        json_dict = {}
        json_dict['reason'] = self.reason
        json_dict['variation'] = self.variation
        json_dict['keyName'] = self.key_name
        json_dict['name'] = self.name
        return json_dict


class BasicFlagState:
    """Abstract class representing flag state after feature flag evaluaion
    """

    def __init__(self, success: bool, message: str):
        """Constructs an instance.

        :param success: True if successful
        :param message: the state of last evaluation; the value is OK if successful
        """
        self._success = success
        self._message = 'OK' if success else message

    @property
    def success(self) -> bool:
        """Returns true if last evaluation was successful
        """
        return self._success

    @property
    def message(self) -> str:
        """Message representing the state of last evaluation; the value is OK if successful
        """
        return self._message


class FlagState(BasicFlagState, Jsonfy):
    """The object representing representing flag state of a given feature flag after feature flag evaluaion
    This object contains the information about how this flag vable was calculated in the property `data`

    The result of the flag evaluation should be converted to:
        1: string if the feature flag is a string type
        2: bool if the feature flag is a boolean type
        3: Python object if the feature flag is a json type
        4: float/int if the feature flag is a numeric type
    """

    def __init__(self, success: bool, message: str, data: EvalDetail):
        """Constructs an instance.

        :param success: True if successful
        :param message: the state of last evaluation; the value is OK if successful
        :param data: the result of a flag evaluation with information about how it was calculated
        """
        super().__init__(success, message)
        self._data = data

    @property
    def data(self) -> EvalDetail:
        """return the result of a flag evaluation with information about how it was calculated"""
        return self._data

    def to_json_dict(self) -> dict:
        return {'success': self.success,
                'message': self.message,
                'data': self._data.to_json_dict() if self._data else None}


class AllFlagStates(BasicFlagState, Jsonfy):
    """The object that encapsulates the state of all feature flags for a given user after feature flag evaluaion
    :func:`get(key_name)` to get the state for a given feature flag key
    """

    def __init__(self, success: bool, message: str,
                 data: Mapping[EvalDetail, "FBEvent"],
                 event_handler: Callable[["FBEvent"], None]):
        """Constructs an instance.

        :param success: True if successful
        :param message: the state of last evaluation; the value is OK if successful
        :param data: a dictionary containing state of all feature flags and their events
        :event_handler: callback function used to send events to feature flag center
        """
        super().__init__(success, message)
        self._data = dict((ed.key_name, (ed, fb_event)) for ed, fb_event in data.items()) if data else {}
        self._event_handler = event_handler

    @property
    def key_names(self) -> Iterable[Optional[str]]:
        """Return key names of all feature flag
        """
        return self._data.keys()

    def get(self, key_name: str) -> Optional[EvalDetail]:
        """Return the flag evaluation details of a given feature flag key

        This method will send event to back to feature flag center immediately

        :param key_name: key name of the flag
        :return: an :class:`fbclient.common_types.EvalDetail` object
        """
        ed, fb_event = self._data.get(key_name, (None, False))
        if self._event_handler and fb_event:
            self._event_handler(fb_event)
        return ed

    def to_json_dict(self) -> dict:
        return {'success': self.success,
                'message': self.message,
                'data': [ed.to_json_dict() for ed, _ in self._data.values()] if self._data else []}


class FBEvent(Jsonfy, ABC):
    def __init__(self, user: "FBUser"):
        self._user = user

    @abstractmethod
    def add(self, *elements) -> 'FBEvent':
        pass

    @property
    @abstractmethod
    def is_send_event(self) -> bool:
        pass


class _EvalResult:

    def __init__(self,
                 id: str,
                 value: Optional[str],
                 reason: str,
                 is_send_to_expt: bool = False,
                 key_name: Optional[str] = None,
                 name: Optional[str] = None,
                 flag_type: Optional[str] = 'string'):

        self.__id = id
        self.__value = value
        self.__reason = reason
        self.__is_send_to_expt = is_send_to_expt
        self.__key_name = key_name
        self.__name = name
        self.__flag_type = flag_type

    @staticmethod
    def error(default_value: Optional[str], reason: str, key_name: Optional[str] = None, flag_type: Optional[str] = 'string'):
        return _EvalResult(__NO_VARIATION__, default_value, reason, False, key_name if key_name else __FLAG_KEY_UNKNOWN__, __FLAG_NAME_UNKNOWN__, flag_type)

    @property
    def id(self) -> str:
        return self.__id

    @property
    def value(self) -> Optional[str]:
        return self.__value

    @property
    def reason(self) -> str:
        return self.__reason

    @property
    def is_send_to_expt(self) -> bool:
        return self.__is_send_to_expt

    @property
    def key_name(self) -> Optional[str]:
        return self.__key_name

    @property
    def name(self) -> Optional[str]:
        return self.__name

    @property
    def flag_type(self) -> Optional[str]:
        return self.__flag_type

    @property
    def is_success(self) -> bool:
        return self.__id != __NO_VARIATION__

    @property
    def to_evail_detail(self) -> "EvalDetail":
        _value = cast_variation_by_flag_type(self.__flag_type, self.__value)
        return EvalDetail(self.__reason, _value, self.__key_name, self.__name)

    @property
    def to_flag_state(self) -> "FlagState":
        return FlagState(self.is_success, self.__reason, self.to_evail_detail)
