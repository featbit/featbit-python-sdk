# FeatBit Server-Side SDK for Python

## Introduction

This is the Python Server-Side SDK for the 100% open-source feature flags management platform [FeatBit](https://github.com/featbit/featbit).

The FeatBit Server-Side SDK for Python is designed primarily for use in multi-user systems such as web servers and applications.

## Data synchonization

We use websocket to make the local data synchronized with the FeatBit server, and then store them in memory by
default. Whenever there is any change to a feature flag or its related data, this change will be pushed to the SDK and
the average synchronization time is less than 100 ms. Be aware the websocket connection may be interrupted due to
internet outage, but it will be resumed automatically once the problem is gone.

If you want to use your own data source, see [Offline Mode](#offline-mode).

## Get Started

### Installation
install the sdk in using pip, this version of the SDK is compatible with Python 3.6 through 3.11.

```shell
pip install fb-python-sdk
```

### Prerequisite

Before using the SDK, you need to obtain the environment secret and SDK URLs. 

Follow the documentation below to retrieve these values

- [How to get the environment secret](https://docs.featbit.co/sdk/faq#how-to-get-the-environment-secret)
- [How to get the SDK URLs](https://docs.featbit.co/sdk/faq#how-to-get-the-sdk-urls)
  
### Quick Start

> Note that the _**env_secret**_, _**streaming_url**_ and _**event_url**_ are required to initialize the SDK.

The following code demonstrates basic usage of the SDK.

```python
from fbclient import get, set_config
from fbclient.config import Config

env_secret = '<replace-with-your-env-secret>'
event_url = 'http://localhost:5100'
streaming_url = 'ws://localhost:5100'

set_config(Config(env_secret, event_url, streaming_url))
client = get()

if client.initialize:
    flag_key = '<replace-with-your-flag-key>'
    user_key = 'bot-id'
    user_name = 'bot'
    user = {'key': user_key, 'name': user_name}
    detail = client.variation_detail(flag_key, user, default=None)
    print(f'flag {flag_key} returns {detail.variation} for user {user_key}, reason: {detail.reason}')

# ensure that the SDK shuts down cleanly and has a chance to deliver events to FeatBit before the program exits
client.stop()
```

### Examples

- [Python Demo](https://github.com/featbit/featbit-samples/blob/main/samples/dino-game/demo-python/demo_python.py)

### FBClient

Applications **SHOULD instantiate a single FBClient instance** for the lifetime of the application. In the case where an application
needs to evaluate feature flags from different environments, you may create multiple clients, but they should still be
retained for the lifetime of the application rather than created per request or per thread.

#### Bootstrapping

The bootstrapping is in fact the call of constructor of `FBClient`, in which the SDK will be initialized and connect to FeatBit.

The constructor will return when it successfully connects, or when the timeout(default: 15 seconds) expires, whichever comes first. If it has not succeeded in connecting when the timeout elapses, you will receive the client in an uninitialized state where feature flags will return default values; it will still continue trying to connect in the background unless there has been a network error or you close the client(using `stop()`). You can detect whether initialization has succeeded by calling `initialize()`.

The best way to use the SDK as a singleton, first make sure you have called `fbclient.set_config()` at startup time. Then `fbclient.get()` will return the same shared `fbclient.client.FBClient` instance each time. The client will be initialized if it runs first time.
```python
from fbclient.config import Config
from fbclient import get, set_config 

set_config(Config(env_secret, event_url, streaming_url))
client = get()

if client.initialize:
    # the client is ready
```
You can also manage your `fbclient.client.FBClient`, the SDK will be initialized if you call `fbclient.client.FBClient` constructor. With constructor, you can set the timeout for initialization, the default value is 15 seconds.
```python
from fbclient.config import Config
from fbclient.client import FBClient

client = FBClient(Config(env_secret, event_url, streaming_url), start_wait=15)

if client.initialize:
    # the client is ready
```
If you prefer to have the constructor return immediately, and then wait for initialization to finish at some other point, you can use `fbclient.client.fbclient.update_status_provider` object, which provides an asynchronous way, as follows:

``` python
from fbclient.config import Config
from fbclient.client import FBClient

client = FBClient(Config(env_secret), start_wait=0)
if client.update_status_provider.wait_for_OKState():
    # the client is ready
```

It's possible to set a timeout in seconds for the `wait_for_OKState` method. If the timeout is reached, the method will return `False` and the client will still be in an uninitialized state. If you do not specify a timeout, the method will wait indefinitely.


> To check if the client is ready is optional. Even if the client is not ready, you can still evaluate feature flags, but the default value will be returned if SDK is not yet initialized.

### FBUser

A dictionary of attributes that can affect flag evaluation, usually corresponding to a user of your application.
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

If you would like to get variations of all feature flags in a special environment, you can use `fbclient.client.FBClient.get_all_latest_flag_variations`, SDK will return `fbclient.common_types.AllFlagStates`, that explain the details of all feature flags. `fbclient.common_types.AllFlagStates.get()` returns the detail of a given feature flag key.

```python
if client.initialize:
    user = {'key': user_key, 'name': user_name}
    all_flag_values = client.get_all_latest_flag_variations(user)
    # get all feature flag keys
    keys = all_flag_values.keys()
    for flag_key in keys:
        # get viariation detail
        detail = all_flag_values.get(flag_key, default=None)
        # get viariation
        value = all_flag_values.get_variation(flag_key, default=None)
```

> **Note**
> If evaluation happened before the client is initialized, or you provide the wrong flag key/user for evaluation, the `variation` calls will return the default value. The `fbclient.common_types.EvalDetail` will explain the details of the latest evaluation including error reason.

### Flag Tracking

`fbclient.client.FBClient.flag_tracker` registers a listener to be notified of feature flag changes in general.

Note that a flag value change listener is bound to a specific user and flag key.

The flag value change listener will be notified whenever the SDK receives any change to any feature flag's configuration,
or to a user segment that is referenced by a feature flag. To register a flag value change listener, use `add_flag_value_may_changed_listener` or `add_flag_value_changed_listener`

When you track a flag change using `add_flag_value_maybe_changed_listener`, this does not necessarily mean the flag's value has changed for any particular flag, only that some part of the flag configuration was changed so that it *_MAY_* return a different value than it previously returned for some user.

If you want to track a flag whose value *_MUST_* be changed, `add_flag_value_changed_listener` will register a listener that will be notified if and only if the flag value changes.

Change notices only work if the SDK is actually connecting to FeatBit feature flag center.
If the SDK is in offline mode, then it cannot know when there is a change, because flags are read on an as-needed basis.

```python
if client.initialize:
    #  flag value may be changed
    client.flag_tracker.add_flag_value_maybe_changed_listener(flag_key, user, flag_value_maybe_changed_callback_fn)
    #  flag value must be changed
    client.flag_tracker.add_flag_value_changed_listener(flag_key, user, flag_value_changed_callback_fn)

```
`flag_key`: the key of the feature flag to track

`user`: the user to evaluate the flag value

`callback_fn`: the function to be called for the flag value change
* the first argument is the flag key
* the second argument is the latest flag value



### Offline Mode

In some situations, you might want to stop making remote calls to FeatBit. Here is how:

```python
config = Config(env_secret, event_url, streaming_url, offline=True)
```
When you put the SDK in offline mode, no insight message is sent to the server and all feature flag evaluations return
fallback values because there are no feature flags or segments available. If you want to use your own data source,
SDK allows users to populate feature flags and segments data from a JSON string. Here is an example: [fbclient_test_data.json](tests/fbclient_test_data.json).

The format of the data in flags and segments is defined by FeatBit and is subject to change. Rather than trying to construct these objects yourself, it's simpler to request existing flags directly from the FeatBit server in JSON format and use this output as the starting point for your file. Here's how:

```shell
# replace http://localhost:5100 with your evaluation server url
curl -H "Authorization: <your-env-secret>" http://localhost:5100/api/public/sdk/server/latest-all > featbit-bootstrap.json
```

Then you can use this file to initialize the SDK in offline mode:

```python
// first load data from file and then
client.initialize_from_external_json(json)
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
  feature, [submit an issue](https://github.com/featbit/featbit-python-sdk/issues/new).

## See Also
- [Connect To Python Sdk](https://docs.featbit.co/sdk/overview#python)
