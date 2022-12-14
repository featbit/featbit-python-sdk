import json
import logging
import sys
from math import floor
from random import random
from time import time
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import urlparse

from dateutil.parser import isoparse

TRACE_LEVEL = logging.DEBUG - 5

logging.addLevelName(TRACE_LEVEL, 'TRACE')


class _MyLogger(logging.getLoggerClass()):
    def trace(self, msg, *args, **kwargs):
        if self.isEnabledFor(TRACE_LEVEL):
            self._log(TRACE_LEVEL, msg, args, **kwargs)


logging.setLoggerClass(_MyLogger)

logging.getLogger("schedule").setLevel(logging.ERROR)

log = logging.getLogger(sys.modules[__name__].__name__)

ALPHABETS = {"0": "Q", "1": "B", "2": "W", "3": "S", "4": "P", "5": "H", "6": "D", "7": "X", "8": "Z", "9": "U"}


def build_headers(env_secret: str, extra_headers={}):

    def build_default_headers():
        return {
            'Authorization': env_secret,
            'User-Agent': 'fb-python-server-sdk',
            'Content-Type': 'application/json'
        }

    headers = build_default_headers()
    headers.update(extra_headers)
    return headers


def build_token(env_secret: str) -> str:

    def encodeNumber(num, length):
        s = "000000000000" + str(num)
        return ''.join(list(map(lambda ch: ALPHABETS[ch], s[len(s) - length:])))

    text = env_secret.rstrip("=")
    now = unix_timestamp_in_milliseconds()
    timestampCode = encodeNumber(now, len(str(now)))
    start = max(floor(random() * len(text)), 2)
    part1 = encodeNumber(start, 3)
    part2 = encodeNumber(len(timestampCode), 2)
    part3 = text[0:start]
    part4 = timestampCode
    part5 = text[start:]
    return '%s%s%s%s%s' % (part1, part2, part3, part4, part5)


def unix_timestamp_in_milliseconds():
    return int(round(time() * 1000))


def valide_all_data(all_data={}) -> bool:
    return isinstance(all_data, dict) \
        and all_data.get('messageType', 'pong') == 'data-sync' \
        and 'data' in all_data and isinstance(all_data['data'], dict) \
        and all(k in all_data['data'] for k in ('eventType', 'featureFlags', 'segments')) \
        and any(k == all_data['data']['eventType'] for k in ('full', 'patch')) \
        and isinstance(all_data['data']['featureFlags'], Iterable) \
        and isinstance(all_data['data']['segments'], Iterable)


def is_ascii(value: str) -> bool:
    if value and isinstance(value, str):
        return len(value) == len(value.encode())
    return False


def is_url(value: str) -> bool:
    try:
        result = urlparse(value)
        return all([result.scheme, result.netloc])
    except:
        return False


def check_uwsgi():
    if 'uwsgi' in sys.modules:
        # noinspection PyPackageRequirements,PyUnresolvedReferences
        import uwsgi
        if not hasattr(uwsgi, 'opt'):
            # means that we are not running under uwsgi
            return

        if uwsgi.opt.get('enable-threads'):
            return
        if uwsgi.opt.get('threads') is not None and int(uwsgi.opt.get('threads')) > 1:
            return
        raise ValueError("The Python Server SDK requires the 'enable-threads' or 'threads' option be passed to uWSGI.")


def is_numeric(value) -> bool:
    try:
        float(str(value))
        return True
    except ValueError:
        return False


def from_str_datetime_to_millis(value: str) -> int:
    try:
        return int(round(isoparse(value).timestamp() * 1000))
    except:
        return 0


def cast_variation_by_flag_type(flag_type: Optional[str], variation: Optional[str]) -> Any:
    try:
        if 'boolean' == flag_type or 'json' == flag_type:
            return json.loads(variation)  # type: ignore
        elif 'number' == flag_type:
            float_value = float(variation)  # type: ignore
            return int(float_value) if float_value.is_integer() else float_value
        else:
            return variation
    except:
        return variation


def simple_type_inference(value: Any) -> Optional[str]:
    if isinstance(value, bool):
        return 'boolean'
    elif isinstance(value, str):
        return 'string'
    elif isinstance(value, Iterable) or isinstance(value, Mapping):
        return 'json'
    elif is_numeric(value):
        return 'number'
    elif value is None:
        return None
    else:
        raise ValueError("value type is not supported")
