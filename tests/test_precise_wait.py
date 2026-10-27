import threading
import time

import numpy as np

from app.human import merge_close_colors
from app.precise_wait import PreciseWaiter


def test_paced_stream_keeps_requested_average_rate():
    waiter = PreciseWaiter(threading.Event())
    started = time.perf_counter()
    for _ in range(100):
        waiter.pace(.002)
    elapsed = time.perf_counter()-started
    # Event.wait(.002) takes ~15.6 ms on Windows: 100 samples would last ~1.5 s.
    assert .19 <= elapsed <= .32


def test_long_wait_is_interrupted_quickly_by_stop():
    stop = threading.Event()
    waiter = PreciseWaiter(stop)
    threading.Timer(.05, stop.set).start()
    started = time.perf_counter()
    assert waiter.wait(5) is True
    assert time.perf_counter()-started < .2


def test_pace_does_not_burst_after_long_work():
    waiter = PreciseWaiter(threading.Event())
    waiter.pace(.001)
    time.sleep(.05)  # A guard/screenshot took real time.
    started = time.perf_counter()
    waiter.pace(.004)
    # The stream restarts instead of returning immediately to "catch up" 50 ms.
    assert time.perf_counter()-started >= .003


def test_merge_close_colors_joins_only_indistinguishable_entries():
    palette = [(244, 190, 168), (20, 20, 28), (21, 21, 29), (15, 15, 23), (60, 60, 70)]
    labels = np.array([[0, 1, 1, 2], [3, 1, 4, 0]], np.uint8)
    merged, kept, count = merge_close_colors(labels, palette, 12)
    assert count == 2
    assert kept == [(20, 20, 28), (244, 190, 168), (60, 60, 70)]  # Most frequent member keeps its exact colour.
    assert [kept[i] for i in merged.ravel()] == [(244, 190, 168), (20, 20, 28), (20, 20, 28), (20, 20, 28),
                                                (20, 20, 28), (20, 20, 28), (60, 60, 70), (244, 190, 168)]
    same, unchanged, none = merge_close_colors(labels, palette, 0)
    assert none == 0 and unchanged == palette and same is labels
    # Light/chromatic neighbours keep their own regions (merging them lost detail).
    light = [(244, 190, 168), (240, 186, 165), (20, 20, 28)]
    _, kept_light, merged_light = merge_close_colors(np.array([[0, 1, 2]], np.uint8), light, 12)
    assert merged_light == 0 and kept_light == light
