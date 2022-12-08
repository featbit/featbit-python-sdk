"""
Internal helper class to implement exponential backoff algorithm for better network reconnection
Base in https://docs.aws.amazon.com/general/latest/gr/api-retries.html
"""

import random
from time import time
from fbclient.utils import log


class BackoffAndJitterStrategy:

    def __init__(self,
                 first_delay_in_seconds: float = 1.0,
                 max_delay_in_seconds: float = 60.0,
                 reset_interval_in_seconds: float = 60,
                 jitter_ratio: float = 0.5):
        self.__retry_times = 0
        self.__first_delay = first_delay_in_seconds
        self.__reset_interval = reset_interval_in_seconds
        self.__jitter_ratio = jitter_ratio
        self.__latest_good_run = 0
        self.__max_delay = max_delay_in_seconds

    def set_good_run(self, current_time_in_seconds: float = 0):
        if current_time_in_seconds <= 0:
            self.__latest_good_run = time()
        else:
            self.__latest_good_run = current_time_in_seconds

    def __count_jitter_time(self, delay: float) -> float:
        return delay * self.__jitter_ratio * random.random()

    def __count_backoff_time(self) -> float:
        delay = self.__first_delay * (2**self.__retry_times)
        return delay if delay <= self.__max_delay else self.__max_delay

    def next_delay(self, force_to_restart_in_max_delay=False):
        current_time = time()
        if self.__latest_good_run > 0 and self.__reset_interval > 0 and current_time - self.__latest_good_run > self.__reset_interval:
            self.__retry_times = 0
        if force_to_restart_in_max_delay:
            self.__retry_times = 0
            delay = self.__max_delay
        else:
            backoff = self.__count_backoff_time()
            delay = self.__count_jitter_time(backoff) + backoff / 2
        self.__retry_times += 1
        self.__latest_good_run = 0
        log.debug('next delay is %s' % str(delay))
        return delay
