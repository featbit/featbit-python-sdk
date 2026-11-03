## New Features

- Support the per-flag `insightsEnabled` setting delivered by FeatBit. An explicit boolean `false` suppresses evaluation event collection without changing evaluation values, variation IDs, match reasons, or experiment eligibility. (#21)

## Compatibility

- Insights remain enabled when the setting is absent, null, or non-boolean, matching the evaluation server's default behavior.
- Custom metric and identify events are unaffected. Enabling insights does not override existing offline or closed-client event suppression.
- No breaking public API changes. Python 3.10 through 3.14 remain supported.

**Full Changelog**: https://github.com/featbit/featbit-python-sdk/compare/v1.1.10...v1.2.0
