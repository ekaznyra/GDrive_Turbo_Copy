"""Proactive client-side rate limiting (token bucket).

Drive's sustained write ceiling is low (~10 ops/sec/project). The adaptive
concurrency controller only reacts *after* a 429/403; this pacer is the steady
floor that keeps combined request rate under the limit so most rate-limit
errors never happen. It is shared across all operation types so it bounds the
total project transactions-per-second, not per-op.

The :class:`AdaptivePacer` goes one step further: it *learns* the account's
sustainable rate. It starts at the configured ceiling, multiplicatively backs
off when Drive throttles, and additively recovers after a streak of successes
(AIMD, the same control law TCP uses for congestion). A server-supplied
``Retry-After`` opens a *global* cooldown so every worker waits out the window
together, rather than each thread discovering the limit on its own.

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


class AdaptivePacer(TokenBucket):
    """A token bucket whose sustained rate adapts to Drive's limits (AIMD).

    It starts at ``max_rate`` — so throughput is identical to the fixed pacer
    when nothing throttles — and then:

    * :meth:`record_throttle` multiplicatively lowers the rate
      (``rate *= backoff``, floored at ``min_rate``). If Drive supplied a
      ``Retry-After``, it also opens a *global* cooldown: the next
      :meth:`acquire` on every worker blocks until the window elapses.
    * :meth:`record_success` additively raises the rate back toward
      ``max_rate`` after ``recover_after`` consecutive successes.

    Capacity (burst) tracks the current rate, so a lowered rate cannot be
    immediately defeated by a large backlog of accumulated tokens.
    """

    def __init__(
        self,
        max_rate: float,
        *,
        min_rate: float = 1.0,
        backoff: float = 0.5,
        recover_step: float = 1.0,
        recover_after: int = 25,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(max_rate, burst=max(1.0, max_rate), monotonic=monotonic, sleep=sleep)
        self.max_rate = float(max_rate)
        self.min_rate = max(0.1, float(min_rate))
        self._backoff = float(backoff)
        self._recover_step = float(recover_step)
        self._recover_after = max(1, int(recover_after))
        self._successes = 0
        self._cooldown_until = 0.0

    def acquire(self, tokens: float = 1.0) -> float:
        if self.rate <= 0:
            return 0.0
        slept = 0.0
        # Wait out any server-mandated cooldown first. Re-check after sleeping in
        # case another worker's throttle extended the window while we slept.
        while True:
            with self._lock:
                wait = self._cooldown_until - self._monotonic()
            if wait <= 0:
                break
            self._sleep(wait)
            slept += wait
        return slept + super().acquire(tokens)

    def record_throttle(self, *, retry_after: float | None = None) -> None:
        """React to a rate-limit signal: back off, and honor any Retry-After."""
        with self._lock:
            self._successes = 0
            self.rate = max(self.min_rate, self.rate * self._backoff)
            self.capacity = max(1.0, self.rate)
            if self._tokens > self.capacity:
                self._tokens = self.capacity
            if retry_after and retry_after > 0:
                deadline = self._monotonic() + float(retry_after)
                self._cooldown_until = max(self._cooldown_until, deadline)

    def record_success(self) -> None:
        """After a streak of clean calls, creep the rate back toward the ceiling."""
        with self._lock:
            if self.rate >= self.max_rate:
                self._successes = 0
                return
            self._successes += 1
            if self._successes >= self._recover_after:
                self.rate = min(self.max_rate, self.rate + self._recover_step)
                self.capacity = max(1.0, self.rate)
                self._successes = 0


class NullPacer:
    """A no-op pacer used when rate limiting is disabled."""

    def acquire(self, tokens: float = 1.0) -> float:
        return 0.0

    def record_throttle(self, *, retry_after: float | None = None) -> None:
        return None

    def record_success(self) -> None:
        return None


def make_pacer(
    max_tps: float,
    *,
    min_tps: float = 1.0,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
):
    """Return an :class:`AdaptivePacer` for ``max_tps`` > 0, else a NullPacer."""
    if max_tps and max_tps > 0:
        return AdaptivePacer(max_tps, min_rate=min_tps, monotonic=monotonic, sleep=sleep)
    return NullPacer()
