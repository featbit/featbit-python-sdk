import json
from pathlib import Path

import pytest

from fbclient.category import FEATURE_FLAGS, SEGMENTS
from fbclient.common_types import FBUser
from fbclient.data_storage import InMemoryDataStorage
from fbclient.evaluator import (REASON_FALLTHROUGH, REASON_FLAG_OFF,
                                REASON_RULE_MATCH, REASON_TARGET_MATCH,
                                Evaluator)
from fbclient.event_types import FlagEvent
from fbclient.streaming import _data_to_dict
from fbclient.utils import valide_all_data

USER_1 = {"key": "test-user-1", "name": "test-user-1", "country": "us"}
USER_2 = {"key": "test-target-user", "name": "test-target-user"}
USER_3 = {"key": "test-true-user", "name": "test-true-user", "graduated": "true"}
USER_4 = {"key": "test-equal-user", "name": "test-equal-user", "country": "CHN"}
USER_5 = {"key": "test-than-user", "name": "test-than-user", "salary": "2500"}
USER_6 = {"key": "test-contain-user", "name": "test-contain-user", "email": "test-contain-user@gmail.com"}
USER_7 = {"key": "test-isoneof-user", "name": "test-isoneof-user", "major": "CS"}
USER_8 = {"key": "group-admin-user", "name": "group-admin-user"}
USER_9 = {"key": "test-regex-user", "name": "test-regex-user", "phone": "18555358000"}
USER_10 = {"key": "test-fallthrough-user", "name": "test-fallthrough-user"}


@pytest.fixture
def data_storage():
    json_str = Path('tests/fbclient_test_data.json').read_text()
    data_storage = InMemoryDataStorage()
    if json_str:
        all_data = json.loads(json_str)
        if valide_all_data(all_data):
            version, data = _data_to_dict(all_data['data'])
            data_storage.init(data, version)
    return data_storage


@pytest.fixture
def evaluator(data_storage):
    def flag_getter(key):
        return data_storage.get(FEATURE_FLAGS, key)

    def segment_getter(key):
        return data_storage.get(SEGMENTS, key)

    return Evaluator(flag_getter, segment_getter)


@pytest.fixture
def disable_flag(data_storage):
    return data_storage.get(FEATURE_FLAGS, "ff-test-off")


@pytest.fixture
def flag(data_storage):
    return data_storage.get(FEATURE_FLAGS, "ff-evaluation-test")


def test_evaluation_when_disable_flag(evaluator, disable_flag):
    user = FBUser.from_dict(USER_1)
    event = FlagEvent(user)
    er = evaluator.evaluate(disable_flag, user, event)
    assert er.value == "false"
    assert er.reason == REASON_FLAG_OFF


def test_evaluation_when_match_target_user(evaluator, flag):
    user = FBUser.from_dict(USER_2)
    event = FlagEvent(user)
    er = evaluator.evaluate(flag, user, event)
    assert er.value == "teamB"
    assert er.reason == REASON_TARGET_MATCH


def test_evaluation_when_match_true_condition(evaluator, flag):
    user = FBUser.from_dict(USER_3)
    event = FlagEvent(user)
    er = evaluator.evaluate(flag, user, event)
    assert er.value == "teamC"
    assert er.reason == REASON_RULE_MATCH


def test_evaluation_when_match_equal_condition(evaluator, flag):
    user = FBUser.from_dict(USER_4)
    event = FlagEvent(user)
    er = evaluator.evaluate(flag, user, event)
    assert er.value == "teamD"
    assert er.reason == REASON_RULE_MATCH


def test_evaluation_when_match_than_condition(evaluator, flag):
    user = FBUser.from_dict(USER_5)
    event = FlagEvent(user)
    er = evaluator.evaluate(flag, user, event)
    assert er.value == "teamE"
    assert er.reason == REASON_RULE_MATCH


def test_evaluation_when_match_contain_condition(evaluator, flag):
    user = FBUser.from_dict(USER_6)
    event = FlagEvent(user)
    er = evaluator.evaluate(flag, user, event)
    assert er.value == "teamF"
    assert er.reason == REASON_RULE_MATCH


def test_evaluation_when_match_isoneof_condition(evaluator, flag):
    user = FBUser.from_dict(USER_7)
    event = FlagEvent(user)
    er = evaluator.evaluate(flag, user, event)
    assert er.value == "teamG"
    assert er.reason == REASON_RULE_MATCH


def test_evaluation_when_match_startend_condition(evaluator, flag):
    user = FBUser.from_dict(USER_8)
    event = FlagEvent(user)
    er = evaluator.evaluate(flag, user, event)
    assert er.value == "teamH"
    assert er.reason == REASON_RULE_MATCH


def test_evaluation_when_match_regex_condition(evaluator, flag):
    user = FBUser.from_dict(USER_9)
    event = FlagEvent(user)
    er = evaluator.evaluate(flag, user, event)
    assert er.value == "teamI"
    assert er.reason == REASON_RULE_MATCH


def test_evaluation_when_match_fallthroug_condition(evaluator, flag):
    user = FBUser.from_dict(USER_10)
    event = FlagEvent(user)
    er = evaluator.evaluate(flag, user, event)
    assert er.value == "teamA"
    assert er.reason == REASON_FALLTHROUGH
