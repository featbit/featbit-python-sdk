"""Validate this checkout against a real FeatBit evaluation service.

The environment secret is read only from the process environment and is never
printed or persisted by this script.
"""

import json
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fbclient.client import FBClient  # noqa: E402
from fbclient.config import Config  # noqa: E402
from fbclient.status_types import StateType  # noqa: E402


def sdk_threads():
    return {
        thread.ident: thread.name for thread in threading.enumerate()
        if thread.name.startswith("featbit-")
    }


def main():
    env_secret = os.environ.get("FEATBIT_ENV_SECRET")
    if not env_secret:
        raise SystemExit("FEATBIT_ENV_SECRET is required")

    streaming_url = os.environ.get(
        "FEATBIT_STREAMING_URL", "wss://app-eval.featbit.co"
    )
    event_url = os.environ.get(
        "FEATBIT_EVENT_URL", "https://app-eval.featbit.co"
    )
    flag_key = os.environ.get("FEATBIT_FLAG_KEY", "python-app-release")
    timeout = float(os.environ.get("FEATBIT_START_WAIT_SECONDS", "15"))
    states = []
    baseline_threads = sdk_threads()

    client = FBClient(Config(env_secret,
                             event_url=event_url,
                             streaming_url=streaming_url),
                      start_wait=timeout)

    def on_state_change(state):
        states.append(state.state_type.name)

    client.update_status_provider.add_listener(on_state_change)
    try:
        ready = client.initialize or client.update_status_provider.wait_for_OKState(
            timeout=timeout
        )
        if not ready:
            state = client.update_status_provider.current_state
            error = state.error_track
            raise SystemExit(
                "FeatBit SDK did not become ready: %s%s" % (
                    state.state_type.name,
                    " (%s)" % error.error_type if error else "",
                )
            )

        evaluations = []
        for index, plan in enumerate(("standard", "pro", "enterprise")):
            user_key = "python-sdk-live-%s" % index
            user = {"key": user_key, "name": user_key, "plan": plan}
            detail = client.variation_detail(flag_key, user, False)
            evaluations.append({
                "user_key": user_key,
                "variation": detail.variation,
                "variation_id": detail.variation_id,
                "reason": detail.reason,
            })
            client.identify(user)
            client.track_metric(user, "python-sdk-live-check", 1.0)

        client.flush()
        # Event delivery is asynchronous; stop() performs the final synchronous
        # drain, while this short interval also exercises explicit flush().
        time.sleep(1.0)
        before_close = client.update_status_provider.current_state.state_type
    finally:
        client.update_status_provider.remove_listener(on_state_change)
        client.stop()
        client.stop()

    current_threads = sdk_threads()
    leaked_threads = sorted(
        name for ident, name in current_threads.items()
        if ident not in baseline_threads
    )
    after_close = client.update_status_provider.current_state.state_type
    result = {
        "ready": ready,
        "state_before_close": before_close.name,
        "state_after_close": after_close.name,
        "observed_state_changes": states,
        "flag_key": flag_key,
        "evaluations": evaluations,
        "events_exercised": ["feature_flag", "identify", "custom_metric", "flush"],
        "leaked_sdk_threads": leaked_threads,
    }
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    if (before_close != StateType.OK
            or after_close != StateType.OFF
            or leaked_threads):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
