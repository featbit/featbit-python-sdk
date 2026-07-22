from typing import Any

from fbclient.common_types import EvalDetail
from fbclient.evaluator import (
    REASON_CLIENT_NOT_READY,
    REASON_ERROR,
    REASON_FLAG_NOT_FOUND,
    REASON_FLAG_OFF,
    REASON_RULE_MATCH,
    REASON_TARGET_MATCH,
    REASON_USER_NOT_SPECIFIED,
    REASON_WRONG_TYPE,
)
from openfeature.exception import ErrorCode
from openfeature.flag_evaluation import FlagResolutionDetails, Reason


_STANDARD_REASONS = {
    REASON_FLAG_OFF: Reason.DISABLED,
    REASON_TARGET_MATCH: Reason.TARGETING_MATCH,
    REASON_RULE_MATCH: Reason.TARGETING_MATCH,
}

_ERROR_CODES = {
    REASON_CLIENT_NOT_READY: ErrorCode.PROVIDER_NOT_READY,
    REASON_FLAG_NOT_FOUND: ErrorCode.FLAG_NOT_FOUND,
    REASON_USER_NOT_SPECIFIED: ErrorCode.TARGETING_KEY_MISSING,
    REASON_WRONG_TYPE: ErrorCode.TYPE_MISMATCH,
    REASON_ERROR: ErrorCode.GENERAL,
}


class ResolutionDetailsConverter:
    """Convert FeatBit details to OpenFeature resolution details."""

    def to_resolution_details(
        self, result: EvalDetail, resolved_value: Any
    ) -> FlagResolutionDetails:
        raw_reason = result.reason or ""
        error_code = _ERROR_CODES.get(raw_reason)

        if error_code is not None:
            reason = Reason.ERROR
            error_message = raw_reason
            variant = None
        else:
            reason = _STANDARD_REASONS.get(raw_reason, raw_reason or Reason.UNKNOWN)
            error_message = None
            variant = result.variation_id

        return FlagResolutionDetails(
            value=resolved_value,
            error_code=error_code,
            error_message=error_message,
            reason=reason,
            variant=variant,
        )
