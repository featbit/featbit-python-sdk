import base64
import json
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest

from fbclient.client import FBClient
from fbclient.common_types import FBUser
from fbclient.config import Config
from fbclient.event_processor import DefaultEventProcessor, NullEventProcessor
from fbclient.event_types import FlagEvent, MetricEvent, UserEvent
from fbclient.streaming import Streaming
from fbclient.update_processor import NullUpdateProcessor


MISSING = object()
USER = {'key': 'test-user-1', 'name': 'Test User', 'country': 'us'}
FLAG_KEY = 'ff-test-bool'
SETTINGS = [MISSING, True, False, None, 0, 'false']


def payload(setting, event_type='full', revision=1):
    message = json.loads(Path('tests/fbclient_test_data.json').read_text())
    message['data']['eventType'] = event_type
    for flag in message['data']['featureFlags']:
        flag.pop('insightsEnabled', None)
        if setting is not MISSING:
            flag['insightsEnabled'] = setting
        flag['updatedAt'] = '2030-01-01T00:00:%02dZ' % revision
    return json.dumps(message)


@pytest.fixture
def client():
    processor = Mock()
    config = Config(base64.b64encode(b'insights-test').decode(),
                    event_url='http://fake', streaming_url='http://fake',
                    update_processor_imp=NullUpdateProcessor,
                    event_processor_imp=lambda *_: processor)
    with FBClient(config) as instance:
        yield instance


def sync(client, message):
    # Exercise the real WebSocket message parser and storage update without
    # starting a network connection or a ping thread.
    streaming = Streaming(Config('unused', 'http://fake', 'http://fake', offline=True), client._broadcaster,
                          client._update_status_provider, Event())
    streaming._on_message(None, message)


@pytest.mark.parametrize('setting', SETTINGS)
@pytest.mark.parametrize('entry', ['variation', 'variation_detail', 'get', 'get_variation'])
def test_synced_insights_setting_controls_all_evaluation_entries(client, setting, entry):
    sync(client, payload(setting))
    flag = client._get_flag_internal(FLAG_KEY)
    if setting is MISSING:
        assert 'insightsEnabled' not in flag
    else:
        assert flag['insightsEnabled'] == setting
        assert type(flag['insightsEnabled']) is type(setting)

    if entry in ('get', 'get_variation'):
        states = client.get_all_latest_flag_variations(USER)
        client._event_processor.send_event.assert_not_called()
        result = getattr(states, entry)(FLAG_KEY, False)
    else:
        result = getattr(client, entry)(FLAG_KEY, USER, False)
    assert (result.variation if entry in ('get', 'variation_detail') else result) is True

    calls = client._event_processor.send_event.call_args_list
    assert len(calls) == (0 if setting is False else 1)
    if calls:
        variation = calls[0][0][0].to_json_dict()['variations'][0]['variation']
        assert variation['id'] == flag['fallthrough']['variations'][0]['id']
        assert variation['value'] == 'true'


@pytest.mark.parametrize('setting', SETTINGS)
def test_external_json_preserves_insights_setting(setting):
    with FBClient(Config('unused', 'http://fake', 'http://fake', offline=True)) as client:
        assert client.initialize_from_external_json(payload(setting))
        flag = client._get_flag_internal(FLAG_KEY)
        assert flag.get('insightsEnabled', MISSING) == setting
        event = FlagEvent(FBUser.from_dict(USER))
        client._evaluator.evaluate(flag, FBUser.from_dict(USER), event)
        assert bool(event.is_send_event) == (setting is not False)
        # Enabling insights does not replace offline event suppression.
        client.variation(FLAG_KEY, USER, False)
        assert isinstance(client._event_processor, NullEventProcessor)


@pytest.mark.parametrize('key,user', [
    ('ff-test-off', USER),
    ('ff-evaluation-test', {'key': 'test-target-user'}),
    ('ff-evaluation-test', {'key': 'rule-user', 'graduated': 'true'}),
    ('ff-evaluation-test', {'key': 'fallthrough-user'}),
])
def test_insights_does_not_change_evaluation_or_experiment_eligibility(client, key, user):
    sync(client, payload(True))
    flag = client._get_flag_internal(key)
    user = FBUser.from_dict(dict(user, name='Test User'))
    enabled_event = FlagEvent(user)
    before = client._evaluator.evaluate(flag, user, enabled_event)
    flag = dict(flag, insightsEnabled=False)
    disabled_event = FlagEvent(user)
    after = client._evaluator.evaluate(flag, user, disabled_event)
    assert (after.id, after.value, after.reason, after.is_send_to_expt) == (
        before.id, before.value, before.reason, before.is_send_to_expt)
    assert enabled_event.is_send_event
    assert not disabled_event.is_send_event


def test_patch_updates_future_evaluations_but_preserves_snapshot_eligibility(client):
    sync(client, payload(True))
    enabled_snapshot = client.get_all_latest_flag_variations(USER)
    sync(client, payload(False, 'patch', 2))
    assert client._get_flag_internal(FLAG_KEY)['insightsEnabled'] is False
    disabled_snapshot = client.get_all_latest_flag_variations(USER)
    assert client.variation(FLAG_KEY, USER) is True
    client._event_processor.send_event.assert_not_called()
    enabled_snapshot.get(FLAG_KEY)
    assert client._event_processor.send_event.call_count == 1

    sync(client, payload(True, 'patch', 3))
    assert client._get_flag_internal(FLAG_KEY)['insightsEnabled'] is True
    disabled_snapshot.get_variation(FLAG_KEY)
    assert client._event_processor.send_event.call_count == 1
    assert client.variation(FLAG_KEY, USER) is True
    assert client._event_processor.send_event.call_count == 2


def test_metrics_and_identify_are_unaffected_and_closed_client_stays_silent(client):
    sync(client, payload(False))
    client.track_metric(USER, 'purchase')
    client.identify(USER)
    events = [call[0][0] for call in client._event_processor.send_event.call_args_list]
    assert [type(event) for event in events] == [MetricEvent, UserEvent]
    sync(client, payload(True, 'patch', 2))
    client.stop()
    client.variation(FLAG_KEY, USER)
    assert client._event_processor.send_event.call_count == 2


def test_default_processor_only_delivers_enabled_evaluations(client):
    sender = Mock()
    processor = DefaultEventProcessor(client._config, sender)
    client._event_processor = processor
    sync(client, payload(True))
    client.variation(FLAG_KEY, USER)
    sync(client, payload(False, 'patch', 2))
    client.variation(FLAG_KEY, USER)
    client.get_all_latest_flag_variations(USER).get(FLAG_KEY)
    # Shutdown drains accepted events, including the one collected before disable.
    client.stop()
    delivered = [event for call in sender.postJson.call_args_list
                 for event in json.loads(call[0][1])]
    assert len(delivered) == 1
    assert delivered[0]['variations'][0]['featureFlagKey'] == FLAG_KEY
