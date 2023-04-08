# FeatBit python sdk

## Introduction

This is the Python Server-Side SDK for the 100% open-source feature flags management
platform [FeatBit](https://github.com/featbit/featbit). It is intended for use in a multiple-users python server applications.

This SDK has two main purposes:

- Store the available feature flags and evaluate the feature flags by given user in the server side SDK
- Sends feature flags usage, and custom events for the insights and A/B/n testing.

## Data synchonization

We use websocket to make the local data synchronized with the FeatBit server, and then store them in memory by
default. Whenever there is any change to a feature flag or its related data, this change will be pushed to the SDK and
the average synchronization time is less than 100 ms. Be aware the websocket connection may be interrupted due to
internet outage, but it will be resumed automatically once the problem is gone.

If you want to use your own data source, see [Offline](#offline).

## Get Started

### Installation
install the sdk in using pip, this version of the SDK is compatible with Python 3.6 through 3.11.

```
pip install fb-python-sdk
```

### Basic usage

```python
from fbclient import get, set_config
from fbclient.config import Config

env_secret = '<replace-with-your-env-secret>'
event_url = 'http://localhost:5100'
streaming_url = '"ws://localhost:5100"'

set_config(Config(env_secret, event_url, streaming_url))
client = get()

if client.initialize:
    flag_key = '<replace-with-your-flag-key>'
    user_key = '<replace-with-your-user-key>'
    user_name = '<replace-with-your-user-name>'
    user = {'key': user_key, 'name': user_name}
    detail = client.variation_detail(flag_key, user, default=None)
    print(f'flag {flag_key} returns {detail.value} for user {user_key}')
    print(f'Reason Description: {detail.reason}')

# should close the client when you don't need it anymore
client.stop()
```
Note that the _**env_secret**_, _**streaming_url**_ and _**event_url**_ are required to initialize the SDK.

### Examples

- [Python Demo](https://github.com/featbit/featbit-samples/blob/main/samples/dino-game/demo-python/demo_python.py)

### FBClient

Applications SHOULD instantiate a single instance for the lifetime of the application. In the case where an application
needs to evaluate feature flags from different environments, you may create multiple clients, but they should still be
retained for the lifetime of the application rather than created per request or per thread.

### Bootstrapping

The bootstrapping is in fact the call of constructor of `FFCClient`, in which the SDK will be initialized and connect to feature flag center

The constructor will return when it successfully connects, or when the timeout(default: 15 seconds) expires, whichever comes first. If it has not succeeded in connecting when the timeout elapses, you will receive the client in an uninitialized state where feature flags will return default values; it will still continue trying to connect in the background unless there has been a network error or you close the client(using `stop()`). You can detect whether initialization has succeeded by calling `initialize()`.

The best way to use the SDK as a singleton, first make sure you have called `fbclient.set_config()` at startup time. Then `fbclient.get()` will return the same shared `fbclient.client.FFCClient` instance each time. The client will be initialized if it runs first time.
```python
from fbclient.config import Config
from fbclient import get, set_config 

set_config(Config(env_secret, event_url, streaming_url))
client = get()

if client.initialize:
    # your code

```
You can also manage your `fbclient.client.FBClient`, the SDK will be initialized if you call `fbclient.client.FBClient` constructor. With constructor, you can set the timeout for initialization, the default value is 15 seconds.
```python
from fbclient.config import Config
from fbclient.client import FBClient

client = FBClient(Config(env_secret, event_url, streaming_url), start_wait=15)

if client.initialize:
    # your code

```
If you prefer to have the constructor return immediately, and then wait for initialization to finish at some other point, you can use `fbclient.client.fbclient.update_status_provider` object, which provides an asynchronous way, as follows:

``` python
from fbclient.config import Config
from fbclient.client import FBClient

client = FFCClient(Config(env_secret), start_wait=0)
if client.update_status_provider.wait_for_OKState():
    # your code

```

### Offline

In the offline mode, SDK DOES not exchange any data with feature flag center, this mode is only use for internal test for instance.

To open the offline mode:
```python
config = Config(env_secret, event_url, streaming_url, offline=True)
```
When you put the SDK in offline mode, no insight message is sent to the server and all feature flag evaluations return
fallback values because there are no feature flags or segments available. If you want to use your own data source,
SDK allows users to populate feature flags and segments data from a JSON string.

Here is an example: [fbclient_test_data.json](tests/fbclient_test_data.json).

```shell
# replace http://localhost:5100 with your evaluation server url
curl -H "Authorization: <your-env-secret>" http://localhost:5100/api/public/sdk/server/latest-all > featbit-bootstrap.json
```

Then you can use this file to initialize the SDK in offline mode:

```python
// first load data from file and then
client.initialize_from_external_json(json)
```
### FBUser

`User`: A dictionary of attributes that can affect flag evaluation, usually corresponding to a user of your application.
This object contains built-in properties(`key`, `name`). The `key` and `name` are required. The `key` must uniquely identify each user; this could be a username or email address for authenticated users, or a ID for anonymous users. The `name` is used to search your user quickly. You may also define custom properties with arbitrary names and values.
For instance, the custom key should be a string; the custom value should be a string, number or boolean value

```python
user = {'key': user_key, 'name': user_name, 'age': age}
```

### Evaluation

SDK calculates the value of a feature flag for a given user, and returns a flag vlaue/an object that describes the way that the value was determined.

```python
if client.initialize:
    user = {'key': user_key, 'name': user_name, 'age': age}
    # evaluate the flag value
    flag_value = client.variation(flag_key, user, default_value)
    # evaluate the flag value and get the detail
    detail = client.variation_detail(flag_key, user, default=None)

```
If evaluation called before SDK client initialized or you set the wrong flag key or user for the evaluation, SDK will return the default value you set. The `fbclient.common_types.EvalDetail` will explain the details of the last evaluation including error raison.

If you would like to get variations of all feature flags in a special environment, you can use `fbclient.client.FBClient.get_all_latest_flag_variations`, SDK will return `fbclient.common_types.AllFlagStates`, that explain the details of all feature flags. `fbclient.common_types.AllFlagStates.get()` returns the detail of a given feature flag key.

```python
if client.initialize:
    user = {'key': user_key, 'name': user_name}
    all_flag_values = client.get_all_latest_flag_variations(user)
    detail = all_flag_values.get(flag_key, default=None)
    
```

### Experiments (A/B/n Testing)
We support automatic experiments for pageviews and clicks, you just need to set your experiment on our SaaS platform, then you should be able to see the result in near real time after the experiment is started.

In case you need more control over the experiment data sent to our server, we offer a method to send custom event.
```python
client.track_metric(user, event_name, numeric_value);
```
**numeric_value** is not mandatory, the default value is **1**.

Make sure `track_metric` is called after the related feature flag is evaluated by simply calling `variation` or `variation_detail`
otherwise, the custom event may not be included into the experiment result.

## Getting support

- If you have a specific question about using this sdk, we encourage you
  to [ask it in our slack](https://join.slack.com/t/featbit/shared_invite/zt-1ew5e2vbb-x6Apan1xZOaYMnFzqZkGNQ).
- If you encounter a bug or would like to request a
  feature, [submit an issue](https://github.com/featbit/dotnet-server-sdk/issues/new).

## See Also
- [Connect To Python Sdk](https://docs.featbit.co/docs/getting-started/4.-connect-an-sdk/server-side-sdks/python-sdk)