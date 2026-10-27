"""Interruptible waits that honour short durations on Windows.

threading.Event.wait(timeout) rounds to the system timer tick (~15.6 ms by
default on Windows). The executor waits once per mouse sample, so a requested
2 ms pause silently became ~15 ms and real drawing ran several times slower
than the selected speed. time.sleep() uses a high-resolution waitable timer
since Python 3.11, but it cannot be interrupted, so long waits are split:
a coarse Event.wait for the bulk, then short sleeps that re-check stop.
"""
from __future__ import annotations

import contextlib
import sys
import threading
import time

_CHUNK = .004        # Longest uninterruptible sleep; F9 latency stays below this.
_COARSE_MARGIN = .02  # Event.wait may overshoot by one Windows tick.
_CATCH_UP = .004     # Pacing never bursts more than this to recover lost time.


class PreciseWaiter:
    def __init__(self, stop_event: threading.Event):
        self.stop_event = stop_event
        self._target = None

    def wait(self, seconds: float) -> bool:
        """Wait about `seconds`; return True as soon as stop is requested."""
        if seconds <= 0:
            return self.stop_event.is_set()
        until = time.perf_counter()+seconds
        if seconds > _COARSE_MARGIN*2:
            if self.stop_event.wait(seconds-_COARSE_MARGIN):
                return True
        while True:
            if self.stop_event.is_set():
                return True
            remaining = until-time.perf_counter()
            if remaining <= 0:
                return False
            time.sleep(min(remaining, _CHUNK))

    def reset_pace(self):
        self._target = None

    def pace(self, seconds: float) -> bool:
        """Deadline-based pacing for a stream of samples.

        Small overshoots of one wait are absorbed by the next one, so the
        average sample interval equals the requested speed. Recovery is bounded:
        after a long guard or screenshot the stream restarts instead of
        flushing a burst of moves the game could merge or drop.
        """
        now = time.perf_counter()
        if self._target is None or self._target < now-_CATCH_UP:
            self._target = now
        self._target += max(0., seconds)
        return self.wait(self._target-now)

    @staticmethod
    @contextlib.contextmanager
    def high_resolution():
        """Request a 1 ms system timer while drawing (restored on exit)."""
        winmm = None
        if sys.platform == "win32":
            try:
                import ctypes
                winmm = ctypes.WinDLL("winmm")
                if winmm.timeBeginPeriod(1) != 0:
                    winmm = None
            except OSError:
                winmm = None
        try:
            yield
        finally:
            if winmm is not None:
                winmm.timeEndPeriod(1)
