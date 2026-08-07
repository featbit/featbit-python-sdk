
version: 1.1.8

## Break changes

- Runtime evaluation methods no longer raise `ValueError` solely because a
  supplied fallback has an unsupported type. If evaluation cannot produce a
  flag value, the original fallback object is returned unchanged and the SDK
  logs a diagnostic message. This intentional behavior change keeps runtime
  SDK failures from escaping into application request paths.

## New features

- expose the stable variation ID in evaluation details
- add data-update status change listeners

## Updates

- handle Python versions 3.12.x
- make client, WebSocket, event, and notice shutdown deterministic and idempotent
- isolate runtime event and shutdown failures from application code
- add concurrency, memory-retention, thread-lifecycle, and live-service audit tools
- exclude the test package from production wheels
