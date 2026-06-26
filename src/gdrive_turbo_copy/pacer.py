"""Proactive client-side rate limiting (token bucket).

Drive's sustained write ceiling is low (~10 ops/sec/project). The adaptive
concurrency controller only reacts *after* a 429/403; this pacer is the steady
floor that keeps combined request rate under the limit so most rate-limit
errors never happen. It is shared across all operation types so it bounds the
total project transactions-per-second, not per-op.

``monotonic`` and ``sleep`` are injectable for deterministic tests.
"""

from __future__ import annotations

import threading
import time
from typing import Callable


class TokenBucket:
    """Classic token bucket. ``rate`` tokens/sec, capacity ``burst``."""

    def __init__(
        self,
        rate: float,
        *,
        burst: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.rate = float(rate)
        self.capacity = float(burst if burst is not None else max(1.0, rate))
        self._tokens = self.capacity
        self._last = monotonic()
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = threading.Lock()

    def _refill_locked(self) -> None:
        now = self._monotonic()
        elapsed = now - self._last
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            self._last = now

    def acquire(self, tokens: float = 1.0) -> float:
        """Block until ``tokens`` are available; return the seconds slept."""
        if self.rate <= 0:
            return 0.0
        slept_total = 0.0
        # Epsilon guards against floating-point dust (e.g. 0.2*5 landing just
        # below 1.0) causing an asymptotic spin that never quite reaches the
        # token count.
        eps = 1e-9
        while True:
            with self._lock:
                self._refill_locked()
                if self._tokens >= tokens - eps:
                    self._tokens = max(0.0, self._tokens - tokens)
                    return slept_total
                deficit = tokens - self._tokens
                wait = deficit / self.rate
            self._sleep(wait)
            slept_total += wait


class NullPacer:
    """A no-op pacer used when rate limiting is disabled."""

    def acquire(self, tokens: float = 1.0) -> float:
        return 0.0


def make_pacer(
    max_tps: float,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
):
    """Return a TokenBucket for ``max_tps`` > 0, else a NullPacer."""
    if max_tps and max_tps > 0:
        return TokenBucket(max_tps, monotonic=monotonic, sleep=sleep)
    return NullPacer()
