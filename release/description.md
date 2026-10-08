## Bug Fixes

- Fix a streaming regression introduced in 1.1.8 where flag updates stopped shortly after startup, leaving applications evaluating stale values. Flag updates now continue normally. (#18, #19)

Users running online streaming mode with **1.1.8 or 1.1.9** should upgrade to **1.1.10** as soon as it is available and update pinned dependencies or lock files as needed.

**Full Changelog**: https://github.com/featbit/featbit-python-sdk/compare/v1.1.9...v1.1.10
