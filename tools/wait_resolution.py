"""Measure how long short waits really take on this OS.

The executor paces every mouse sample with a short wait. On Windows the
default timer tick can turn a requested 2 ms into ~15 ms, which silently
slows real drawing. Run: python tools/wait_resolution.py
"""
import json
import statistics
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def measure(wait, requested, count=200):
    samples = []
    for _ in range(count):
        started = time.perf_counter()
        wait(requested)
        samples.append(time.perf_counter()-started)
    samples.sort()
    return dict(requested_ms=requested*1000, p50_ms=round(statistics.median(samples)*1000, 3),
                p95_ms=round(samples[int(len(samples)*.95)]*1000, 3), mean_ms=round(statistics.fmean(samples)*1000, 3))


def main():
    from app.precise_wait import PreciseWaiter
    event = threading.Event()
    waiter = PreciseWaiter(event)
    report = {}
    for requested in (.0005, .002, .005, .012):
        report[f"event_wait_{requested*1000:g}ms"] = measure(event.wait, requested)
        with waiter.high_resolution():
            report[f"precise_{requested*1000:g}ms"] = measure(waiter.wait, requested)
    # Paced loop: 100 samples of 2 ms must take ~200 ms in total.
    with waiter.high_resolution():
        waiter.reset_pace()
        started = time.perf_counter()
        for _ in range(100):
            waiter.pace(.002)
        report["paced_100x2ms_total_ms"] = round((time.perf_counter()-started)*1000, 1)
    started = time.perf_counter()
    for _ in range(100):
        event.wait(.002)
    report["event_100x2ms_total_ms"] = round((time.perf_counter()-started)*1000, 1)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
