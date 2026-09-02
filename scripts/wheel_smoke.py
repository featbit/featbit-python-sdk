#!/usr/bin/env python3
"""Exercise the installed wheel through the public offline client API."""

import argparse
import base64
import json
import site
import threading
from importlib import metadata
from pathlib import Path

import fbclient
from fbclient.client import FBClient
from fbclient.config import Config


PACKAGE_NAME = "fb-python-sdk"
FAKE_ENV_SECRET = base64.b64encode(b"fake_env_secret").decode()
FAKE_URL = "http://fake"
USER_ENABLED = {"key": "test-user-1", "name": "test-user-1", "country": "us"}
USER_DISABLED = {
    "key": "test-user-3",
    "name": "test-user-3",
    "country": "cn",
    "major": "cs",
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", type=Path, required=True)
    parser.add_argument("--expected-version")
    parser.add_argument("--expected-version-file", type=Path)
    return parser.parse_args()


def assert_installed_package():
    package_path = Path(fbclient.__file__).resolve()
    site_paths = [Path(path).resolve() for path in site.getsitepackages()]
    assert any(package_path.is_relative_to(path) for path in site_paths), (
        "fbclient was not imported from the wheel environment: %s" % package_path
    )


def assert_metadata(expected_version):
    distribution = metadata.distribution(PACKAGE_NAME)
    if expected_version:
        assert distribution.version == expected_version

    package_metadata = distribution.metadata
    assert package_metadata["Requires-Python"] == ">=3.10, <3.15"
    classifiers = package_metadata.get_all("Classifier") or []
    assert "Programming Language :: Python :: 3.10" in classifiers
    assert "Programming Language :: Python :: 3.14" in classifiers
    requirements = distribution.requires or []
    assert any(requirement.startswith("urllib3<3,>=1.26.5") for requirement in requirements)
    return distribution.version


def featbit_thread_ids():
    return {
        thread.ident
        for thread in threading.enumerate()
        if thread.ident is not None and thread.name.startswith("featbit-")
    }


def exercise_client(bootstrap_path):
    baseline_threads = featbit_thread_ids()
    states = []
    config = Config(
        FAKE_ENV_SECRET,
        event_url=FAKE_URL,
        streaming_url=FAKE_URL,
        offline=True,
    )
    client = FBClient(config)

    def on_status_change(state):
        states.append(state.state_type.name)

    client.update_status_provider.add_listener(on_status_change)
    try:
        assert client.initialize_from_external_json(bootstrap_path.read_text())
        assert client.initialize
        assert states == ["OK"]
        assert client.variation("ff-test-bool", USER_ENABLED, False) is True
        assert client.variation("ff-test-bool", USER_DISABLED, True) is False
        assert client.variation("missing-flag", USER_ENABLED, False) is False
        for _ in range(100):
            assert client.variation("ff-test-bool", USER_ENABLED, False) is True
    finally:
        client.update_status_provider.remove_listener(on_status_change)
        client.stop()
        client.stop()

    leaked_threads = featbit_thread_ids() - baseline_threads
    assert not leaked_threads, "FeatBit worker threads leaked: %s" % leaked_threads
    return states


def main():
    args = parse_args()
    expected_version = args.expected_version
    if args.expected_version_file:
        expected_version = json.loads(
            args.expected_version_file.read_text()
        )["version"]
    assert_installed_package()
    version = assert_metadata(expected_version)
    states = exercise_client(args.bootstrap)
    print(json.dumps({"package": PACKAGE_NAME, "states": states, "version": version}))


if __name__ == "__main__":
    main()
