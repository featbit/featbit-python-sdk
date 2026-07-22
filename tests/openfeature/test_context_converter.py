# flake8: noqa: E402

import logging
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("openfeature")

from openfeature.evaluation_context import EvaluationContext
from openfeature.exception import TargetingKeyMissingError

from featbit_openfeature.impl.context_converter import EvaluationContextConverter


@pytest.fixture
def converter():
    return EvaluationContextConverter()


def test_targeting_key_and_name_are_converted(converter):
    context = EvaluationContext("user-123", {"name": "Alice", "plan": "beta"})

    assert converter.to_fb_user(context) == {
        "key": "user-123",
        "name": "Alice",
        "plan": "beta",
    }


def test_attribute_key_is_supported_as_compatibility_fallback(converter):
    context = EvaluationContext(None, {"key": "legacy-user"})

    assert converter.to_fb_user(context) == {
        "key": "legacy-user",
        "name": "legacy-user",
    }


def test_targeting_key_takes_precedence_over_attribute_key(converter):
    context = EvaluationContext("preferred", {"key": "legacy", "name": "Alice"})

    user = converter.to_fb_user(context)

    assert user["key"] == "preferred"
    assert "keyid" not in user
    assert "targetingKey" not in user


@pytest.mark.parametrize("context", [None, EvaluationContext(), EvaluationContext("  ")])
def test_missing_targeting_key_is_rejected(converter, context):
    with pytest.raises(TargetingKeyMissingError):
        converter.to_fb_user(context)


def test_invalid_name_falls_back_to_targeting_key(converter, caplog):
    context = EvaluationContext("user-123", {"name": 42})

    user = converter.to_fb_user(context)

    assert user["name"] == "user-123"
    assert "using targeting key" in caplog.records[0].message


def test_scalar_attributes_are_preserved(converter):
    context = EvaluationContext(
        "user-123",
        {"string": "value", "boolean": True, "integer": 3, "float": 1.5},
    )

    user = converter.to_fb_user(context)

    assert user["string"] == "value"
    assert user["boolean"] is True
    assert user["integer"] == 3
    assert user["float"] == 1.5


def test_datetime_attributes_are_iso_formatted(converter):
    naive = datetime(2026, 7, 22, 12, 30)
    aware = datetime(2026, 7, 22, 12, 30, tzinfo=timezone(timedelta(hours=8)))
    context = EvaluationContext("user-123", {"naive": naive, "aware": aware})

    user = converter.to_fb_user(context)

    assert user["naive"] == "2026-07-22T12:30:00+00:00"
    assert user["aware"] == "2026-07-22T12:30:00+08:00"


def test_structured_attributes_are_ignored_without_mutation(converter, caplog):
    caplog.set_level(logging.DEBUG, logger="featbit-openfeature-server")
    attributes = {"groups": ["beta"], "profile": {"region": "cn"}, "plan": "pro"}
    context = EvaluationContext("user-123", attributes)

    user = converter.to_fb_user(context)

    assert user["plan"] == "pro"
    assert "groups" not in user
    assert "profile" not in user
    assert context.attributes == attributes
    assert len(caplog.records) == 2
