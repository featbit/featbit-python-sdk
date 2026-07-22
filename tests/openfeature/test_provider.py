# flake8: noqa: E402

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

pytest.importorskip("openfeature")

from fbclient.common_types import EvalDetail
from fbclient.evaluator import REASON_CLIENT_NOT_READY, REASON_TARGET_MATCH
from fbclient.flag_change_notification import FlagChangedNotice
from fbclient.status_types import State
from openfeature.evaluation_context import EvaluationContext
from openfeature.event import ProviderEvent
from openfeature.exception import (
    ErrorCode,
    ProviderFatalError,
    ProviderNotReadyError,
)
from openfeature.flag_evaluation import Reason
from openfeature.track import TrackingEventDetails

from featbit_openfeature import FeatBitProvider


def make_client(initialized=True):
    client = Mock()
    client.initialize = initialized
    client.flag_tracker = Mock()
    client.update_status_provider = Mock()
    return client


def make_context():
    return EvaluationContext("user-123", {"name": "Alice", "plan": "beta"})


def test_metadata_and_client_access():
    client = make_client()
    provider = FeatBitProvider(client)

    assert provider.get_metadata().name == "featbit-openfeature-server"
    assert provider.client is client


def test_constructor_validation():
    with pytest.raises(ValueError):
        FeatBitProvider(None)
    with pytest.raises(ValueError):
        FeatBitProvider(make_client(), initialization_timeout=0)


@pytest.mark.parametrize(
    "method_name,default_value,return_value,expected_value",
    [
        ("resolve_boolean_details", False, True, True),
        ("resolve_string_details", "default", "enabled", "enabled"),
        ("resolve_integer_details", 1, 2.9, 2),
        ("resolve_float_details", 1.0, 2, 2.0),
        (
            "resolve_object_details",
            {"default": True},
            {"enabled": True},
            {"enabled": True},
        ),
        ("resolve_object_details", ["default"], ["enabled"], ["enabled"]),
    ],
)
def test_typed_resolution_methods(
    method_name, default_value, return_value, expected_value
):
    client = make_client()
    client.variation_detail.return_value = EvalDetail(
        REASON_TARGET_MATCH, return_value, "flag-key", "Flag", "variation-id"
    )
    provider = FeatBitProvider(client)

    result = getattr(provider, method_name)(
        "flag-key", default_value, make_context()
    )

    assert result.value == expected_value
    assert result.reason == Reason.TARGETING_MATCH
    assert result.variant == "variation-id"
    client.variation_detail.assert_called_once_with(
        "flag-key",
        {"key": "user-123", "name": "Alice", "plan": "beta"},
        default_value,
    )


@pytest.mark.parametrize(
    "method_name,default_value,return_value",
    [
        ("resolve_boolean_details", False, 1),
        ("resolve_boolean_details", False, "true"),
        ("resolve_string_details", "default", True),
        ("resolve_integer_details", 1, True),
        ("resolve_float_details", 1.0, True),
        ("resolve_object_details", {}, "json"),
    ],
)
def test_type_mismatch_returns_default(method_name, default_value, return_value):
    client = make_client()
    client.variation_detail.return_value = EvalDetail(
        REASON_TARGET_MATCH, return_value, "flag-key", "Flag", "variation-id"
    )
    provider = FeatBitProvider(client)

    result = getattr(provider, method_name)(
        "flag-key", default_value, make_context()
    )

    assert result.value == default_value
    assert result.reason == Reason.ERROR
    assert result.error_code == ErrorCode.TYPE_MISMATCH
    assert result.variant is None


def test_missing_context_returns_default_without_calling_featbit():
    client = make_client()
    provider = FeatBitProvider(client)

    result = provider.resolve_boolean_details("flag-key", False, None)

    assert result.value is False
    assert result.reason == Reason.ERROR
    assert result.error_code == ErrorCode.TARGETING_KEY_MISSING
    client.variation_detail.assert_not_called()


def test_featbit_error_details_are_preserved():
    client = make_client()
    client.variation_detail.return_value = EvalDetail(
        REASON_CLIENT_NOT_READY, False, "flag-key", "Flag"
    )
    provider = FeatBitProvider(client)

    result = provider.resolve_boolean_details("flag-key", False, make_context())

    assert result.value is False
    assert result.reason == Reason.ERROR
    assert result.error_code == ErrorCode.PROVIDER_NOT_READY
    assert result.error_message == REASON_CLIENT_NOT_READY


def test_unexpected_evaluation_exception_never_escapes():
    client = make_client()
    client.variation_detail.side_effect = RuntimeError("boom")
    provider = FeatBitProvider(client)

    result = provider.resolve_string_details("flag-key", "safe", make_context())

    assert result.value == "safe"
    assert result.error_code == ErrorCode.GENERAL
    assert result.reason == Reason.ERROR


def test_initialize_returns_immediately_when_client_is_ready():
    client = make_client(initialized=True)
    provider = FeatBitProvider(client)

    provider.initialize(EvaluationContext())

    client.update_status_provider.wait_for_OKState.assert_not_called()
    client.flag_tracker.add_flag_changed_listener.assert_called_once()


def test_initialize_waits_for_ready_client():
    client = make_client(initialized=False)
    client.update_status_provider.wait_for_OKState.return_value = True
    provider = FeatBitProvider(client, initialization_timeout=3)

    provider.initialize(EvaluationContext())

    client.update_status_provider.wait_for_OKState.assert_called_once_with(3)


def test_initialize_timeout_raises_provider_not_ready():
    client = make_client(initialized=False)
    client.update_status_provider.wait_for_OKState.return_value = False
    client.update_status_provider.current_state = State.intializing_state()
    provider = FeatBitProvider(client, initialization_timeout=3)

    with pytest.raises(ProviderNotReadyError):
        provider.initialize(EvaluationContext())


def test_initialize_off_state_raises_provider_fatal():
    client = make_client(initialized=False)
    client.update_status_provider.wait_for_OKState.return_value = False
    client.update_status_provider.current_state = State.error_off_state(
        "credential", "invalid environment secret"
    )
    provider = FeatBitProvider(client, initialization_timeout=3)

    with pytest.raises(ProviderFatalError) as error:
        provider.initialize(EvaluationContext())

    assert error.value.error_message == "invalid environment secret"


def test_flag_change_is_emitted_and_shutdown_removes_listener():
    client = make_client()
    provider = FeatBitProvider(client)
    emitter = Mock()
    provider.attach(emitter)
    provider.initialize(EvaluationContext())
    listener = client.flag_tracker.add_flag_changed_listener.call_args.args[0]

    listener.on_flag_change(FlagChangedNotice("checkout"))
    provider.shutdown()
    provider.shutdown()

    emitted_provider, event, details = emitter.call_args.args
    assert emitted_provider is provider
    assert event == ProviderEvent.PROVIDER_CONFIGURATION_CHANGED
    assert details.flags_changed == ["checkout"]
    client.flag_tracker.remove_flag_change_notifier.assert_called_once_with(listener)
    client.stop.assert_not_called()


def test_flag_change_callback_exception_never_escapes():
    client = make_client()
    provider = FeatBitProvider(client)
    emitter = Mock(side_effect=RuntimeError("boom"))
    provider.attach(emitter)
    provider.initialize(EvaluationContext())
    listener = client.flag_tracker.add_flag_changed_listener.call_args.args[0]

    listener.on_flag_change(FlagChangedNotice("checkout"))

    emitter.assert_called_once()


def test_shutdown_retries_listener_removal_after_failure():
    client = make_client()
    provider = FeatBitProvider(client)
    provider.initialize(EvaluationContext())
    listener = client.flag_tracker.add_flag_changed_listener.call_args.args[0]
    client.flag_tracker.remove_flag_change_notifier.side_effect = [
        RuntimeError("boom"),
        None,
    ]

    provider.shutdown()
    provider.initialize(EvaluationContext())
    provider.shutdown()

    client.flag_tracker.add_flag_changed_listener.assert_called_once_with(listener)
    assert client.flag_tracker.remove_flag_change_notifier.call_count == 2


def test_track_maps_numeric_value_and_context():
    client = make_client()
    provider = FeatBitProvider(client)

    provider.track(
        "checkout",
        make_context(),
        TrackingEventDetails(value=2.5, attributes={"currency": "CNY"}),
    )

    client.track_metric.assert_called_once_with(
        {"key": "user-123", "name": "Alice", "plan": "beta"},
        "checkout",
        2.5,
    )


def test_track_without_context_or_on_error_never_raises():
    client = make_client()
    provider = FeatBitProvider(client)

    provider.track("missing-context")
    client.track_metric.side_effect = RuntimeError("boom")
    provider.track("failure", make_context())

    assert client.track_metric.call_count == 1


def test_concurrent_resolutions_do_not_share_request_state():
    client = make_client()

    def evaluate(_flag_key, user, _default):
        return EvalDetail(
            REASON_TARGET_MATCH,
            user["request"],
            "flag-key",
            "Flag",
            "variation-id",
        )

    client.variation_detail.side_effect = evaluate
    provider = FeatBitProvider(client)

    def resolve(index):
        context = EvaluationContext(
            "user-{}".format(index),
            {"name": "User {}".format(index), "request": str(index)},
        )
        return provider.resolve_string_details(
            "flag-key", "fallback", context
        ).value

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(resolve, range(1000)))

    assert results == [str(index) for index in range(1000)]
