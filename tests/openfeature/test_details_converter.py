# flake8: noqa: E402

import pytest

pytest.importorskip("openfeature")

from fbclient.common_types import EvalDetail
from fbclient.evaluator import (
    REASON_CLIENT_NOT_READY,
    REASON_ERROR,
    REASON_FALLTHROUGH,
    REASON_FLAG_NOT_FOUND,
    REASON_FLAG_OFF,
    REASON_PREREQUISITE_FAILED,
    REASON_RULE_MATCH,
    REASON_TARGET_MATCH,
    REASON_USER_NOT_SPECIFIED,
    REASON_WRONG_TYPE,
)
from openfeature.exception import ErrorCode
from openfeature.flag_evaluation import Reason

from featbit_openfeature.impl.details_converter import ResolutionDetailsConverter


@pytest.fixture
def converter():
    return ResolutionDetailsConverter()


@pytest.mark.parametrize(
    "featbit_reason,openfeature_reason",
    [
        (REASON_FLAG_OFF, Reason.DISABLED),
        (REASON_TARGET_MATCH, Reason.TARGETING_MATCH),
        (REASON_RULE_MATCH, Reason.TARGETING_MATCH),
        (REASON_FALLTHROUGH, REASON_FALLTHROUGH),
        (REASON_PREREQUISITE_FAILED, REASON_PREREQUISITE_FAILED),
        ("vendor-specific-reason", "vendor-specific-reason"),
        ("", Reason.UNKNOWN),
    ],
)
def test_success_reason_mapping(converter, featbit_reason, openfeature_reason):
    detail = EvalDetail(featbit_reason, True, "flag", "Flag", "variation-id")

    result = converter.to_resolution_details(detail, True)

    assert result.value is True
    assert result.reason == openfeature_reason
    assert result.error_code is None
    assert result.error_message is None
    assert result.variant == "variation-id"


@pytest.mark.parametrize(
    "featbit_reason,error_code",
    [
        (REASON_CLIENT_NOT_READY, ErrorCode.PROVIDER_NOT_READY),
        (REASON_FLAG_NOT_FOUND, ErrorCode.FLAG_NOT_FOUND),
        (REASON_USER_NOT_SPECIFIED, ErrorCode.TARGETING_KEY_MISSING),
        (REASON_WRONG_TYPE, ErrorCode.TYPE_MISMATCH),
        (REASON_ERROR, ErrorCode.GENERAL),
    ],
)
def test_error_mapping_does_not_return_variant(
    converter, featbit_reason, error_code
):
    detail = EvalDetail(featbit_reason, False, "flag", "Flag", "must-not-leak")

    result = converter.to_resolution_details(detail, False)

    assert result.reason == Reason.ERROR
    assert result.error_code == error_code
    assert result.error_message == featbit_reason
    assert result.variant is None
