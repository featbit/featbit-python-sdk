"""Repeatable concurrency, memory-retention, and thread-lifecycle audit."""

import argparse
import gc
import json
import sys
import threading
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fbclient.client import FBClient  # noqa: E402
from fbclient.config import Config  # noqa: E402


def sdk_thread_ids():
    return {
        thread.ident for thread in threading.enumerate()
        if thread.name.startswith("featbit-")
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluations", type=int, default=80000)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--max-retained-bytes", type=int, default=2 * 1024 * 1024)
    args = parser.parse_args()
    if args.evaluations < 1:
        parser.error("--evaluations must be at least 1")
    if args.workers < 1:
        parser.error("--workers must be at least 1")

    baseline_threads = sdk_thread_ids()
    config = Config("resource-audit",
                    event_url="http://offline",
                    streaming_url="ws://offline",
                    offline=True)
    client = FBClient(config)
    bootstrap = (ROOT / "tests" / "fbclient_test_data.json").read_text()
    if not client.initialize_from_external_json(bootstrap):
        raise SystemExit("could not initialize offline audit data")

    user = {"key": "warmup", "name": "Warmup"}
    for _ in range(2000):
        client.variation("ff-test-bool", user, False)

    gc.collect()
    tracemalloc.start()
    baseline_bytes = tracemalloc.get_traced_memory()[0]
    errors = []
    per_worker, remainder = divmod(args.evaluations, args.workers)
    workloads = [
        per_worker + (1 if worker < remainder else 0)
        for worker in range(args.workers)
    ]

    def evaluate(work):
        worker, evaluation_count = work
        completed = 0
        try:
            for index in range(evaluation_count):
                key = "audit-%s-%s" % (worker, index)
                value = client.variation(
                    "ff-test-bool",
                    {"key": key, "name": key},
                    False,
                )
                if not isinstance(value, bool):
                    raise AssertionError("evaluation returned a non-boolean value")
                completed += 1
        except Exception as error:
            errors.append("%s: %s" % (type(error).__name__, error))
        return completed

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        completed = sum(executor.map(evaluate, enumerate(workloads)))
    elapsed = time.perf_counter() - started
    client.stop()
    client.stop()
    gc.collect()
    final_bytes = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()

    leaked_threads = sorted(
        thread.name for thread in threading.enumerate()
        if thread.name.startswith("featbit-")
        and thread.ident not in baseline_threads
    )
    retained_bytes = max(0, final_bytes - baseline_bytes)
    result = {
        "evaluations": completed,
        "workers": args.workers,
        "seconds": round(elapsed, 4),
        "evaluations_per_second": round(completed / elapsed) if elapsed else 0,
        "concurrent_errors": errors,
        "leaked_sdk_threads": leaked_threads,
        "baseline_traced_bytes": baseline_bytes,
        "final_traced_bytes": final_bytes,
        "retained_traced_bytes": retained_bytes,
        "allowed_retained_bytes": args.max_retained_bytes,
    }
    result["status"] = "ok" if (
        not errors
        and not leaked_threads
        and retained_bytes <= args.max_retained_bytes
    ) else "failed"
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
