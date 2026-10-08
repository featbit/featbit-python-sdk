version: 1.1.10

## Important upgrade notice

Versions 1.1.8 and 1.1.9 contain a streaming regression: the first server
`pong` reply can close the WebSocket without reconnecting, stopping subsequent
flag updates while applications continue evaluating cached values.

Users running online streaming mode should upgrade to 1.1.10 as soon as it is
available. Update pinned dependencies and lock files as needed.

```shell
pip install --upgrade 'fb-python-sdk>=1.1.10'
```

## Fixes and behavior changes

- Fix streaming stopping after the first ping/pong exchange.
- Process only `data-sync` messages; ignore other message types, including `pong`.
- Log and skip malformed JSON, invalid data-sync payloads, processing exceptions,
  and unsuccessful data application without closing the WebSocket or triggering
  reconnection from these message-handling paths.
- Include message contents in error logs to aid diagnosis.

These changes intentionally replace the invalid-message close behavior introduced
in 1.1.8. Skipped updates are not automatically retried by this change, and
rejected data-sync messages do not explicitly change the data-update status.

See [issue #18](https://github.com/featbit/featbit-python-sdk/issues/18) and
[PR #19](https://github.com/featbit/featbit-python-sdk/pull/19).

## Validation

- Full unit test suite: 92 passed on CPython 3.12.
- Local live-service check passed: flag changes continued to reach the SDK after
  the first heartbeat, with the data-update status remaining `OK`.
