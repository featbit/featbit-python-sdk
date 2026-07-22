import logging
import threading
from typing import Any, Mapping, Optional, Sequence, Union

from fbclient.client import FBClient
from fbclient.flag_change_notification import FlagChangedListener, FlagChangedNotice
from fbclient.status_types import StateType
from openfeature.evaluation_context import EvaluationContext
from openfeature.event import ProviderEventDetails
from openfeature.exception import (
    ErrorCode,
    ProviderFatalError,
    ProviderNotReadyError,
    TargetingKeyMissingError,
)
from openfeature.flag_evaluation import (
    FlagResolutionDetails,
    FlagType,
    FlagValueType,
    Reason,
)
from openfeature.provider import AbstractProvider
from openfeature.provider.metadata import Metadata
from openfeature.track import TrackingEventDetails

from featbit_openfeature.impl.context_converter import EvaluationContextConverter
from featbit_openfeature.impl.details_converter import ResolutionDetailsConverter


logger = logging.getLogger("featbit-openfeature-server")

_TYPE_MISMATCH = object()


class _FlagChangeListener(FlagChangedListener):
    def __init__(self, callback: Any):
        self._callback = callback

    def on_flag_change(self, notice: FlagChangedNotice):
        self._callback(notice.flag_key)


class FeatBitProvider(AbstractProvider):
    """OpenFeature provider backed by an existing thread-safe ``FBClient``.

    The provider does not own the client. ``shutdown`` removes the listener installed
    by the provider, but the application remains responsible for calling
    ``FBClient.stop`` when it no longer needs the SDK.
    """

    def __init__(self, client: FBClient, initialization_timeout: float = 15.0):
        super().__init__()
        if client is None:
            raise ValueError("client is required")
        if initialization_timeout <= 0:
            raise ValueError("initialization_timeout must be greater than zero")

        self._client = client
        self._initialization_timeout = initialization_timeout
        self._context_converter = EvaluationContextConverter()
        self._details_converter = ResolutionDetailsConverter()
        self._lifecycle_lock = threading.Lock()
        self._flag_change_listener = None  # type: Optional[_FlagChangeListener]

    @property
    def client(self) -> FBClient:
        """Return the FeatBit client supplied to this provider."""
        return self._client

    def initialize(self, evaluation_context: EvaluationContext) -> None:
        if not self._client.initialize:
            ready = self._client.update_status_provider.wait_for_OKState(
                self._initialization_timeout
            )
            if not ready:
                state = self._client.update_status_provider.current_state
                message = self._state_message(state)
                if state.state_type == StateType.OFF:
                    raise ProviderFatalError(message)
                raise ProviderNotReadyError(message)

        self._register_flag_change_listener()

    def shutdown(self) -> None:
        with self._lifecycle_lock:
            listener = self._flag_change_listener

        if listener is None:
            return
        try:
            self._client.flag_tracker.remove_flag_change_notifier(listener)
        except Exception:
            logger.exception("Failed to remove FeatBit flag change listener")
            return

        with self._lifecycle_lock:
            if self._flag_change_listener is listener:
                self._flag_change_listener = None

    def get_metadata(self) -> Metadata:
        return Metadata("featbit-openfeature-server")

    def resolve_boolean_details(
        self,
        flag_key: str,
        default_value: bool,
        evaluation_context: Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails:
        return self._resolve_value(
            FlagType.BOOLEAN, flag_key, default_value, evaluation_context
        )

    def resolve_string_details(
        self,
        flag_key: str,
        default_value: str,
        evaluation_context: Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails:
        return self._resolve_value(
            FlagType.STRING, flag_key, default_value, evaluation_context
        )

    def resolve_integer_details(
        self,
        flag_key: str,
        default_value: int,
        evaluation_context: Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails:
        return self._resolve_value(
            FlagType.INTEGER, flag_key, default_value, evaluation_context
        )

    def resolve_float_details(
        self,
        flag_key: str,
        default_value: float,
        evaluation_context: Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails:
        return self._resolve_value(
            FlagType.FLOAT, flag_key, default_value, evaluation_context
        )

    def resolve_object_details(
        self,
        flag_key: str,
        default_value: Union[
            Sequence[FlagValueType], Mapping[str, FlagValueType]
        ],
        evaluation_context: Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails:
        return self._resolve_value(
            FlagType.OBJECT, flag_key, default_value, evaluation_context
        )

    def track(
        self,
        tracking_event_name: str,
        evaluation_context: Optional[EvaluationContext] = None,
        tracking_event_details: Optional[TrackingEventDetails] = None,
    ) -> None:
        try:
            user = self._context_converter.to_fb_user(evaluation_context)
            metric_value = 1.0
            if tracking_event_details is not None:
                if tracking_event_details.attributes:
                    logger.debug(
                        "FeatBit track_metric does not support tracking attributes; "
                        "ignoring them"
                    )
                if tracking_event_details.value is not None:
                    metric_value = float(tracking_event_details.value)
            self._client.track_metric(user, tracking_event_name, metric_value)
        except TargetingKeyMissingError:
            logger.warning("Ignoring FeatBit tracking call without a targeting key")
        except Exception:
            logger.exception("FeatBit tracking failed")

    def _resolve_value(
        self,
        flag_type: FlagType,
        flag_key: str,
        default_value: Any,
        evaluation_context: Optional[EvaluationContext],
    ) -> FlagResolutionDetails:
        try:
            user = self._context_converter.to_fb_user(evaluation_context)
            result = self._client.variation_detail(flag_key, user, default_value)
            resolved_value = self._validate_and_cast_value(
                flag_type, result.variation
            )
            if resolved_value is _TYPE_MISMATCH:
                return self._type_mismatch_details(default_value)
            return self._details_converter.to_resolution_details(
                result, resolved_value
            )
        except TargetingKeyMissingError as error:
            return FlagResolutionDetails(
                value=default_value,
                reason=Reason.ERROR,
                error_code=ErrorCode.TARGETING_KEY_MISSING,
                error_message=error.error_message,
            )
        except Exception:
            logger.exception("FeatBit flag evaluation failed")
            return FlagResolutionDetails(
                value=default_value,
                reason=Reason.ERROR,
                error_code=ErrorCode.GENERAL,
                error_message="FeatBit flag evaluation failed",
            )

    @staticmethod
    def _validate_and_cast_value(flag_type: FlagType, value: Any) -> Any:
        if flag_type == FlagType.BOOLEAN and isinstance(value, bool):
            return value
        if flag_type == FlagType.STRING and isinstance(value, str):
            return value
        if (
            flag_type == FlagType.INTEGER
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            return int(value)
        if (
            flag_type == FlagType.FLOAT
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            return float(value)
        if flag_type == FlagType.OBJECT and isinstance(value, (dict, list)):
            return value
        return _TYPE_MISMATCH

    @staticmethod
    def _type_mismatch_details(default_value: Any) -> FlagResolutionDetails:
        return FlagResolutionDetails(
            value=default_value,
            reason=Reason.ERROR,
            error_code=ErrorCode.TYPE_MISMATCH,
            error_message="FeatBit flag value does not match the requested type",
        )

    def _register_flag_change_listener(self) -> None:
        with self._lifecycle_lock:
            if self._flag_change_listener is not None:
                return
            listener = _FlagChangeListener(self._emit_configuration_changed)
            try:
                self._client.flag_tracker.add_flag_changed_listener(listener)
            except Exception:
                logger.exception("Failed to register FeatBit flag change listener")
                return
            self._flag_change_listener = listener

    def _emit_configuration_changed(self, flag_key: str) -> None:
        try:
            self.emit_provider_configuration_changed(
                ProviderEventDetails(flags_changed=[flag_key])
            )
        except Exception:
            logger.exception("Failed to emit OpenFeature configuration change event")

    @staticmethod
    def _state_message(state: Any) -> str:
        error = getattr(state, "error_track", None)
        message = getattr(error, "message", None)
        return message or "FeatBit client initialization did not complete"
