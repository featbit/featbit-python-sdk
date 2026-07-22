# FeatBit OpenFeature provider for Python

The FeatBit Python SDK includes an optional server-side OpenFeature provider.
It translates the OpenFeature API to the existing, thread-safe `FBClient` and
does not replace FeatBit's WebSocket synchronization, evaluator, event
processor, logging, or storage implementations.

## Compatibility

- FeatBit's base SDK keeps its existing Python 3.6–3.12 compatibility range.
- The OpenFeature integration requires Python 3.10 or later because
  `openfeature-sdk` 0.10 requires Python 3.10 or later.
- The provider accepts an existing `FBClient`. The application owns that
  client and must call `stop()` during application shutdown.

## Installation

```shell
pip install "fb-python-sdk[openfeature]"
```

## Usage

```python
from fbclient.client import FBClient
from fbclient.config import Config
from featbit_openfeature import FeatBitProvider
from openfeature import api
from openfeature.evaluation_context import EvaluationContext

fb_client = FBClient(
    Config(
        env_secret="your-environment-secret",
        event_url="https://app-evaluation.featbit.co",
        streaming_url="wss://app-evaluation.featbit.co",
    ),
    start_wait=0,
)

api.set_provider_and_wait(FeatBitProvider(fb_client))
client = api.get_client()

details = client.get_string_details(
    "python-app-release",
    "v1",
    EvaluationContext(
        targeting_key="user-123",
        attributes={"name": "Alice", "releaseRing": "canary"},
    ),
)

print(details.value, details.variant, details.reason)

# Application shutdown
api.shutdown()
fb_client.stop()
```

Use the endpoint values shown on the FeatBit environment's SDK connection
page. Self-hosted installations normally use their own event and streaming
URLs.

## Context mapping

| OpenFeature field | FeatBit user field | Behavior |
| --- | --- | --- |
| `targeting_key` | `key` | Required; non-empty `attributes["key"]` is a compatibility fallback. |
| `attributes["name"]` | `name` | Falls back to the targeting key. |
| string, boolean, integer, float | customized property | Preserved. |
| `datetime` | customized property | Converted to ISO 8601; naive values use UTC. |
| list, map, or other structured value | — | Ignored because `FBUser` only retains scalar customized properties. |

## Evaluation mapping

The provider implements all five typed OpenFeature resolution methods:
boolean, string, integer, float, and object. Successful evaluations expose
FeatBit's variation ID as OpenFeature's `variant`.

| FeatBit reason | OpenFeature result |
| --- | --- |
| `flag off` | `DISABLED` |
| `target match`, `rule match` | `TARGETING_MATCH` |
| `client not ready` | `ERROR` / `PROVIDER_NOT_READY` |
| `flag not found` | `ERROR` / `FLAG_NOT_FOUND` |
| `user not specified` | `ERROR` / `TARGETING_KEY_MISSING` |
| `wrong type` | `ERROR` / `TYPE_MISMATCH` |
| unexpected exception | fallback value / `GENERAL` |

All typed resolution methods catch unexpected SDK or conversion errors and
return the caller's default value with OpenFeature error details. They do not
propagate those exceptions into application evaluation code. OpenFeature
provider initialization may still report `ProviderNotReadyError` or
`ProviderFatalError`, as required by the OpenFeature lifecycle.

## Provider events and tracking

- FeatBit flag-change notifications are emitted as
  `PROVIDER_CONFIGURATION_CHANGED` events.
- `track()` maps to `FBClient.track_metric()`; numeric tracking values are
  preserved. OpenFeature tracking attributes are ignored because FeatBit's
  current metric API does not accept them.
- `shutdown()` is idempotent and removes only the provider's flag-change
  listener. It does not stop the injected `FBClient`.
