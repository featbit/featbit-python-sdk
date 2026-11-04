## Changes

- Remove `sendToExperiment` from evaluation event payloads and remove SDK-side experiment eligibility calculations. (#23)
- Stop depending on `exptIncludeAllTargets`, rule/fallthrough `includedInExpt`, and variation `exptRollout` fields. Evaluation works when the server omits these fields.
- Preserve flag evaluation results, percentage rollouts, variation IDs, match reasons, and `insightsEnabled` behavior. Custom metric tracking remains supported.

**Full Changelog**: https://github.com/featbit/featbit-python-sdk/compare/v1.2.0...v1.2.1
