
from abc import ABC, abstractmethod
from typing import Any, Callable
from fbclient.common_types import FBUser
from fbclient.interfaces import Notice
from fbclient.notice_broadcaster import NoticeBroadcater

FLAG_CHANGE_NOTICE_TYPE = 'flag_change_notice'


class FlagChangedNotice(Notice):
    def __init__(self, flag_key: str):
        self.__flag_key = flag_key

    @property
    def notice_type(self) -> str:
        return FLAG_CHANGE_NOTICE_TYPE

    @property
    def flag_key(self) -> str:
        return self.__flag_key


class FlagChangedListener(ABC):
    """
    A notice listener that is notified when a feature flag's configuration has changed.

    This is an abstract class. You need to implement your own listener by overriding the :func:`on_flag_change` method.

    """
    @abstractmethod
    def on_flag_change(self, notice: FlagChangedNotice):
        pass


class FlagValueChangedListener(FlagChangedListener):
    def __init__(self,
                 flag_key: str,
                 user: dict,
                 evaluate_fn: Callable[[str, dict, Any], Any],
                 flag_value_changed_fn: Callable[[str, Any, Any], None]):
        self.__flag_key = flag_key
        self.__user = user
        self.__evaluate_fn = evaluate_fn
        self.__fn = flag_value_changed_fn
        # record the flag value when the listener is created
        self.__prvious_flag_value = self.__evaluate_fn(self.__flag_key, self.__user, None)

    def on_flag_change(self, notice: FlagChangedNotice):
        if notice.flag_key == self.__flag_key:
            prev_flag_value = self.__prvious_flag_value
            curr_flag_value = self.__evaluate_fn(self.__flag_key, self.__user, None)
            if prev_flag_value != curr_flag_value:
                self.__fn(self.__flag_key, prev_flag_value, curr_flag_value)
                self.__prvious_flag_value = curr_flag_value


class FlagValueMaybeChangedListener(FlagChangedListener):
    def __init__(self,
                 flag_key: str,
                 user: dict,
                 evaluate_fn: Callable[[str, dict, Any], Any],
                 flag_value_maybe_changed_fn: Callable[[str, Any], None]):
        self.__flag_key = flag_key
        self.__user = user
        self.__evaluate_fn = evaluate_fn
        self.__fn = flag_value_maybe_changed_fn

    def on_flag_change(self, notice: FlagChangedNotice):
        if notice.flag_key == self.__flag_key:
            curr_flag_value = self.__evaluate_fn(self.__flag_key, self.__user, None)
            self.__fn(self.__flag_key, curr_flag_value)


class FlagTracker:
    """
    A registry to register the flag change listeners in order to track changes in feature flag configurations.

    The registered listerners only work if the SDK is actually connecting to FeatBit feature flag center.
    If the SDK is only in offline mode then it cannot know when there is a change, because flags are read on an as-needed basis.

    Application code never needs to initialize or extend this class directly.
    """

    def __init__(self,
                 flag_change_broadcaster: NoticeBroadcater,
                 evaluate_fn: Callable[[str, dict, Any], Any]):
        """
        :param flag_change_broadcaster: The broadcaster that broadcasts the flag change notices
        :param evaluate_fn: The function to evaluate the flag value
        """
        self.__broadcater = flag_change_broadcaster
        self.__evaluate_fn = evaluate_fn

    def add_flag_value_changed_listener(self,
                                        flag_key: str,
                                        user: dict,
                                        flag_value_changed_fn: Callable[[str, Any, Any], None]) -> FlagValueChangedListener:
        """
        Registers a listener to be notified of a change in a specific feature flag's value for a specific FeatBit user.

        The listener will be notified whenever the SDK receives any change to any feature flag's configuration,
        or to a user segment that is referenced by a feature flag.

        When you call this method, it first immediately evaluates the feature flag. It then uses :class:`FlagChangeListener` to start listening for feature flag configuration
        changes, and whenever the specified feature flag changes, it re-evaluates the flag for the same user. It then calls :class:`FlagValueChangeListener`
        if and only if the resulting value has changed.

        :param flag_key: The key of the feature flag to track
        :param user: The user to evaluate the flag value
        :param flag_value_changed_fn: The function to be called only when this flag value changes
            * the first argument is the flag key
            * the second argument is the previous flag value
            * the third argument is the current flag value

        :return: A listener object that can be used to remove it later on.
        """

        # check flag key
        if not isinstance(flag_key, str) or not flag_key:
            raise ValueError('flag_key must be a non-empty string')
        # check user
        FBUser.from_dict(user)
        # check flag_value_changed_fn
        if not isinstance(flag_value_changed_fn, Callable) or not flag_value_changed_fn:
            raise ValueError('flag_value_changed_fn must be a callable function')

        listener = FlagValueChangedListener(flag_key, user, self.__evaluate_fn, flag_value_changed_fn)
        self.add_flag_changed_listener(listener)
        return listener

    def add_flag_value_maybe_changed_listener(self,
                                              flag_key: str,
                                              user: dict,
                                              flag_value_maybe_changed_fn: Callable[[str, Any], None]) -> FlagValueMaybeChangedListener:
        """
        Registers a listener to be notified of a change in a specific feature flag's value for a specific FeatBit user.

        The listener will be notified whenever the SDK receives any change to any feature flag's configuration,
        or to a user segment that is referenced by a feature flag.

        Note that this does not necessarily mean the flag's value has changed for any particular flag,
        only that some part of the flag configuration was changed so that it may return a different value than it previously returned for some user.

        If you want to track flag value changes,use :func:`add_flag_value_changed_listener instead.

        :param flag_key: The key of the feature flag to track
        :param user: The user to evaluate the flag value
        :param flag_value_maybe_changed_fn: The function to be called if any changes to a specific flag
            * the first argument is the flag key
            * the second argument is the latest flag value, this value may be same as the previous value

        :return: A listener object that can be used to remove it later on.

        """

        # check flag key
        if not isinstance(flag_key, str) or not flag_key:
            raise ValueError('flag_key must be a non-empty string')
        # check user
        FBUser.from_dict(user)
        # check flag_value_changed_fn
        if not isinstance(flag_value_maybe_changed_fn, Callable) or not flag_value_maybe_changed_fn:
            raise ValueError('flag_value_changed_fn must be a callable function')

        listener = FlagValueMaybeChangedListener(flag_key, user, self.__evaluate_fn, flag_value_maybe_changed_fn)
        self.add_flag_changed_listener(listener)
        return listener

    def add_flag_changed_listener(self, listener: FlagChangedListener):
        """
        Registers a listener to be notified of feature flag changes in general.

        The listener will be notified whenever the SDK receives any change to any feature flag's configuration,
        or to a user segment that is referenced by a feature flag.

        :param listener: The listener to be registered. The :class:`FlagChangedListner` is an abstract class. You need to implement your own listener.
        """
        self.__broadcater.add_listener(FLAG_CHANGE_NOTICE_TYPE, listener.on_flag_change)  # type: ignore

    def remove_flag_change_notifier(self, listener: FlagChangedListener):
        """
        Unregisters a listener so that it will no longer be notified of feature flag changes.

        :param listener: The listener to be unregistered. The listener must be the same object that was passed to :func:`add_flag_changed_listner` or :func:`add_flag_value_changed_listerner`
        """
        self.__broadcater.remove_listener(FLAG_CHANGE_NOTICE_TYPE, listener.on_flag_change)  # type: ignore
