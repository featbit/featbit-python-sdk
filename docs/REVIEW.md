# Python Server SDK reliability review

This review covers the production risks requested for the Python Server SDK:
unit behavior, WebSocket synchronization, event processing, evaluation,
logging/error isolation, thread safety, shutdown, memory retention, redundant
code, and live FeatBit service interoperability.

## Review result

The review found and fixed the following concrete issues:

- `RepeatableTask` stored an `Event` in `Thread._stop`, which breaks Python's
  own `Thread.join()` cleanup path. It now uses a separate stop event and joins
  deterministically.
- WebSocket reconnect backoff used an uninterruptible sleep. Client shutdown
  now interrupts the wait, closes the socket defensively, stops the ping task,
  and joins the streaming thread.
- The notice broadcaster mutated its listener registry concurrently. Listener
  operations now use a lock and dispatch from an immutable snapshot; a queue
  sentinel makes shutdown immediate and repeatable.
- The event processor did not retain or join its dispatcher. It now owns the
  dispatcher lifecycle, joins the periodic flush task, and always completes a
  synchronous message even if message handling fails.
- `FBClient.stop()` could expose an extension exception and skip all later
  cleanup. Shutdown is now idempotent, producer-first, and isolates each
  component failure.
- Custom event processor errors could escape from `identify`, `track_*`, or
  `flush`. Event delivery is now best-effort and cannot fail the application
  request.
- Invalid offline bootstrap JSON and unsupported runtime fallback objects could
  raise from evaluation-related calls. They now return `False` or the supplied
  fallback, with a diagnostic log message.
- `Config` and the HTTP helper used mutable default objects. Each client now
  gets independent HTTP/WebSocket options and headers.
- A duplicate `FBUser.from_dict()` call in `track_metric` was removed.

Constructor/configuration validation still raises for invalid required
configuration. This is intentional fail-fast behavior before an SDK client is
usable; runtime evaluation, event, status, and shutdown paths are isolated.

## Automated evidence

Run from the repository root:

```shell
python -m pytest
python -m flake8 .
python scripts/resource_audit.py --evaluations 80000 --workers 8
python -m build
```

Result on Python 3.12.13 (2026-08-07):

- 83 unit/integration tests passed.
- Flake8 passed.
- 80,000 evaluations across 8 workers completed with 0 concurrent errors.
- Throughput was 12,490 evaluations/second on the final audit run.
- No FeatBit SDK worker threads remained after shutdown.
- 24,417 traced bytes remained after garbage collection, below the 2 MiB
  regression threshold.
- A clean wheel built from the source distribution contained 27 files, no
  `tests/` package, and no stale `featbit_openfeature/` package.

The tests specifically cover concurrent evaluation, status-listener ordering,
listener registration/removal under contention, event-processor failure
isolation, repeated client lifecycle, periodic task joining, and interrupting a
blocked WebSocket lifecycle.

## Live FeatBit service verification

Use a real environment Server Key without storing it in the repository:

```shell
export FEATBIT_ENV_SECRET='<server-key>'
export FEATBIT_FLAG_KEY='python-app-release'
python scripts/live_integration_check.py
```

Optional variables are `FEATBIT_STREAMING_URL`, `FEATBIT_EVENT_URL`, and
`FEATBIT_START_WAIT_SECONDS`. The script verifies:

1. authenticated WebSocket connection and initial data synchronization;
2. SDK status reaches `OK`;
3. remote flag evaluation returns value, reason, and variation ID;
4. feature-flag, identify, and custom metric events enter the delivery path;
5. explicit flush and final synchronous drain complete;
6. status changes to `OFF` and no SDK threads remain after close.

The secret is read only from the process environment and is never printed or
written to disk.

A recorded FeatBit Cloud run on 2026-07-24 reached the WebSocket connected
state, processed the initial data-sync payload, evaluated the remote
`python-app-release` flag, exercised the gray-release application under
concurrent HTTP traffic, and later demonstrated automatic reconnection after a
remote-host disconnect. The checked-in script turns that one-off validation
into a repeatable, secret-safe release check.

An additional run on 2026-08-07 used the official FeatBit Docker Compose stack.
It observed a remotely pushed rollout update in 0.5 seconds, completed 4,000
concurrent evaluations without errors, verified the default event-delivery
path, handled a status listener that re-entered `client.stop()` without a
deadlock, reached `OFF`, and left no SDK worker threads behind.

## Remaining operational considerations

- The SDK is designed as a long-lived singleton, not one client per request.
- Event delivery is intentionally best-effort so analytics failure cannot
  affect application availability.
- A custom `DataStorage`, `EventProcessor`, or `UpdateProcessor` remains
  responsible for its own internal correctness; the client isolates its
  runtime and shutdown exceptions.
- Memory thresholds are regression guards, not universal capacity limits;
  production sizing should use the application's real flag and segment data.
