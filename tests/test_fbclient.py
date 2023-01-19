import base64
from pathlib import Path
from unittest.mock import patch

import pytest

from fbclient.client import FBClient
from fbclient.config import Config
from fbclient.data_storage import InMemoryDataStorage
from fbclient.evaluator import (REASON_CLIENT_NOT_READY, REASON_ERROR,
                                REASON_FALLTHROUGH, REASON_FLAG_NOT_FOUND,
                                REASON_RULE_MATCH, REASON_TARGET_MATCH,
                                REASON_USER_NOT_SPECIFIED)
from fbclient.event_processor import NullEventProcessor
from fbclient.update_processor import NullUpdateProcessor

FAKE_ENV_SECRET = base64.b64encode(b"fake_env_secret").decode()

FAKE_URL = "http://fake"

USER_1 = {"key": "test-user-1", "name": "test-user-1", "country": "us"}
USER_2 = {"key": "test-user-2", "name": "test-user-2", "country": "fr"}
USER_3 = {"key": "test-user-3", "name": "test-user-3", "country": "cn", "major": "cs"}
USER_4 = {"key": "test-user-4", "name": "test-user-4", "country": "uk", "major": "physics"}
USER_CN_PHONE_NUM = {"key": "18555358000", "name": "test-user-5"}
USER_FR_PHONE_NUM = {"key": "0603111111", "name": "test-user-6"}
USER_EMAIL = {"key": "test-user-7@featbit.com", "name": "test-user-7"}


def make_fb_client(update_processor_imp, event_processor_imp, start_wait=15.):
    config = Config(FAKE_ENV_SECRET,
                    event_url=FAKE_URL,
                    streaming_url=FAKE_URL,
                    update_processor_imp=update_processor_imp,
                    event_processor_imp=event_processor_imp)
    return FBClient(config, start_wait=start_wait)


def make_fb_client_offline(start_wait=15.):
    json = Path('tests/fbclient_test_data.json').read_text()
    config = Config(FAKE_ENV_SECRET,
                    event_url=FAKE_URL,
                    streaming_url=FAKE_URL,
                    offline=True)
    client = FBClient(config, start_wait=start_wait)
    client.initialize_from_external_json(json)
    return client


def test_construct_null_config():
    with pytest.raises(ValueError) as exc_info:
        FBClient(None)  # type: ignore
        assert exc_info.value.args[0] == "Config is not valid"


def test_construct_empty_envsecret():
    with pytest.raises(ValueError) as exc_info:
        FBClient(Config("", event_url=FAKE_URL, streaming_url=FAKE_URL))
        assert exc_info.value.args[0] == "env secret is invalid"


def test_construct_illegal_envsecret():
    with pytest.raises(ValueError) as exc_info:
        FBClient(Config(FAKE_ENV_SECRET + "©öäü£", event_url=FAKE_URL, streaming_url=FAKE_URL))
        assert exc_info.value.args[0] == "env secret is invalid"


def test_construct_empty_url():
    with pytest.raises(ValueError) as exc_info:
        FBClient(Config(FAKE_ENV_SECRET, event_url="", streaming_url=""))
        assert exc_info.value.args[0] == "streaming or event url is invalid"


def test_construct_invalid_url():
    with pytest.raises(ValueError) as exc_info:
        FBClient(Config(FAKE_ENV_SECRET, event_url="mailto:John.Doe@example.com", streaming_url="urn:isbn:0-294-56559-3"))
        assert exc_info.value.args[0] == "streaming or event url is invalid"


def test_start_and_wait():
    with make_fb_client(NullUpdateProcessor, NullEventProcessor, start_wait=0.1) as client:
        assert client.initialize


@patch.object(NullUpdateProcessor, "start")
def test_start_and_timeout(mock_start_method):
    def start():
        pass
    mock_start_method.side_effect = start
    with make_fb_client(NullUpdateProcessor, NullEventProcessor, start_wait=0.1) as client:
        assert not client.initialize


@patch.object(NullUpdateProcessor, "start")
def test_start_and_nowait(mock_start_method):
    def start():
        pass
    mock_start_method.side_effect = start
    with make_fb_client(NullUpdateProcessor, NullEventProcessor, start_wait=0) as client:
        assert not client.update_status_provider.wait_for_OKState(timeout=0.1)


@patch.object(NullUpdateProcessor, "start")
def test_variation_when_client_not_initialized(mock_start_method):
    def start():
        pass
    mock_start_method.side_effect = start
    with make_fb_client(NullUpdateProcessor, NullEventProcessor, start_wait=0.1) as client:
        assert not client.initialize
        flag_state = client.variation_detail("ff-test-bool", USER_1, False)
        assert not flag_state.success
        assert not flag_state.data.variation
        assert flag_state.data.reason == REASON_CLIENT_NOT_READY
        all_states = client.get_all_latest_flag_variations(USER_1)  # type: ignore
        assert not all_states.success
        assert all_states.message == REASON_CLIENT_NOT_READY


def test_bool_variation():
    with make_fb_client_offline() as client:
        assert client.initialize
        assert client.is_enabled("ff-test-bool", USER_1)
        assert client.variation("ff-test-bool", USER_1, False)
        flag_state = client.variation_detail("ff-test-bool", USER_2, False)
        assert flag_state.success
        assert flag_state.data.variation
        assert flag_state.data.reason == REASON_TARGET_MATCH
        assert not client.is_enabled("ff-test-bool", USER_3)
        flag_state = client.variation_detail("ff-test-bool", USER_4, False)
        assert flag_state.success
        assert flag_state.data.variation
        assert flag_state.data.reason == REASON_FALLTHROUGH


def test_numeric_variation():
    with make_fb_client_offline() as client:
        assert client.initialize
        assert client.variation("ff-test-number", USER_1, -1) == 1
        flag_state = client.variation_detail("ff-test-number", USER_2, -1)
        assert flag_state.success
        assert flag_state.data.variation == 33
        assert flag_state.data.reason == REASON_RULE_MATCH
        assert client.variation("ff-test-number", USER_3, -1) == 86
        flag_state = client.variation_detail("ff-test-number", USER_4, -1)
        assert flag_state.success
        assert flag_state.data.variation == 9999
        assert flag_state.data.reason == REASON_FALLTHROUGH


def test_string_variation():
    with make_fb_client_offline() as client:
        assert client.initialize
        assert client.variation("ff-test-string", USER_CN_PHONE_NUM, 'error') == 'phone number'
        flag_state = client.variation_detail("ff-test-string", USER_FR_PHONE_NUM, 'error')
        assert flag_state.success
        assert flag_state.data.variation == 'phone number'
        assert flag_state.data.reason == REASON_RULE_MATCH
        assert client.variation("ff-test-string", USER_EMAIL, 'error') == 'email'
        flag_state = client.variation_detail("ff-test-string", USER_1, 'error')
        assert flag_state.success
        assert flag_state.data.variation == 'others'
        assert flag_state.data.reason == REASON_FALLTHROUGH


def test_segment():
    with make_fb_client_offline() as client:
        assert client.initialize
        assert client.variation("ff-test-seg", USER_1, 'error') == 'teamA'
        assert client.variation("ff-test-seg", USER_2, 'error') == 'teamB'
        flag_state = client.variation_detail("ff-test-seg", USER_3, 'error')
        assert flag_state.success
        assert flag_state.data.variation == 'teamA'
        assert flag_state.data.reason == REASON_RULE_MATCH
        flag_state = client.variation_detail("ff-test-seg", USER_4, 'error')
        assert flag_state.success
        assert flag_state.data.variation == 'teamB'
        assert flag_state.data.reason == REASON_FALLTHROUGH


def test_json_variation():
    with make_fb_client_offline() as client:
        assert client.initialize
        json_object = client.variation("ff-test-json", USER_1, {})
        assert json_object["code"] == 200
        assert json_object["reason"] == "you win 100 euros"
        flag_state = client.variation_detail("ff-test-json", USER_2, {})
        assert flag_state.success
        assert flag_state.data.variation["code"] == 404
        assert flag_state.data.variation["reason"] == "fail to win the lottery"
        assert flag_state.data.reason == REASON_FALLTHROUGH


def test_flag_known():
    with make_fb_client_offline() as client:
        assert client.initialize
        assert client.is_flag_known("ff-test-bool")
        assert client.is_flag_known("ff-test-number")
        assert client.is_flag_known("ff-test-string")
        assert client.is_flag_known("ff-test-seg")
        assert client.is_flag_known("ff-test-json")
        assert not client.is_flag_known("ff-not-existed")


def test_get_all_latest_flag_variations():
    with make_fb_client_offline() as client:
        assert client.initialize
        all_states = client.get_all_latest_flag_variations(USER_1)
        ed = all_states.get("ff-test-bool")
        assert ed is not None and ed.variation
        ed = all_states.get("ff-test-number")
        assert ed is not None and ed.variation == 1
        ed = all_states.get("ff-test-string")
        assert ed is not None and ed.variation == "others"
        ed = all_states.get("ff-test-seg")
        assert ed is not None and ed.variation == "teamA"
        ed = all_states.get("ff-test-json")
        assert ed is not None and ed.variation["code"] == 200


def test_variation_argument_error():
    with make_fb_client_offline() as client:
        assert client.initialize
        flag_state = client.variation_detail("ff-not-existed", USER_1, False)
        assert not flag_state.success
        assert not flag_state.data.variation
        assert flag_state.data.reason == REASON_FLAG_NOT_FOUND
        flag_state = client.variation_detail("ff-test-bool", None, False)  # type: ignore
        assert not flag_state.success
        assert not flag_state.data.variation
        assert flag_state.data.reason == REASON_USER_NOT_SPECIFIED
        all_states = client.get_all_latest_flag_variations(None)  # type: ignore
        assert not all_states.success
        assert all_states.message == REASON_USER_NOT_SPECIFIED


@patch.object(InMemoryDataStorage, "get_all")
@patch.object(InMemoryDataStorage, "get")
def test_variation_unexpected_error(mock_get_method, mock_get_all_method):
    mock_get_method.side_effect = RuntimeError('test exception')
    mock_get_all_method.side_effect = RuntimeError('test exception')
    with make_fb_client_offline() as client:
        assert client.initialize
        flag_state = client.variation_detail("ff-test-bool", USER_1, False)
        assert not flag_state.success
        assert not flag_state.data.variation
        assert flag_state.data.reason == REASON_ERROR
        all_states = client.get_all_latest_flag_variations(USER_1)
        assert not all_states.success
        assert all_states.message == REASON_ERROR
