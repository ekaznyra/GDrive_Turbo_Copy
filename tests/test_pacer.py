from gdrive_turbo_copy.pacer import AdaptivePacer, NullPacer, TokenBucket, make_pacer


class Clock:
    """Fake monotonic clock whose sleep() advances time deterministically."""

    def __init__(self) -> None:
        self.t = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


def test_burst_tokens_do_not_sleep():
    clock = Clock()
    bucket = TokenBucket(10, burst=2, monotonic=clock.monotonic, sleep=clock.sleep)
    assert bucket.acquire() == 0.0
    assert bucket.acquire() == 0.0  # burst of 2 consumed, no sleep
    assert clock.slept == []


def test_acquire_blocks_when_empty():
    clock = Clock()
    bucket = TokenBucket(10, burst=2, monotonic=clock.monotonic, sleep=clock.sleep)
    bucket.acquire()
    bucket.acquire()
    slept = bucket.acquire()  # bucket empty -> must wait ~1/rate = 0.1s
    assert abs(slept - 0.1) < 1e-9
    assert clock.slept and abs(clock.slept[0] - 0.1) < 1e-9


def test_rate_is_enforced_over_many_acquires():
    clock = Clock()
    bucket = TokenBucket(5, burst=1, monotonic=clock.monotonic, sleep=clock.sleep)
    for _ in range(11):
        bucket.acquire()
    # 1 free (burst) + 10 paced at 0.2s each ~= 2.0s of total sleeping.
    assert abs(clock.t - 2.0) < 1e-6


def test_null_pacer_and_make_pacer_disabled():
    assert isinstance(make_pacer(0), NullPacer)
    assert make_pacer(0).acquire() == 0.0
    # make_pacer returns an AdaptivePacer (a TokenBucket subclass) when enabled.
    pacer = make_pacer(10)
    assert isinstance(pacer, TokenBucket)
    assert isinstance(pacer, AdaptivePacer)


def test_null_pacer_feedback_is_noop():
    pacer = NullPacer()
    # These must exist and do nothing so the client can call them unconditionally.
    pacer.record_throttle(retry_after=5)
    pacer.record_success()
    assert pacer.acquire() == 0.0


def test_adaptive_starts_at_ceiling():
    clock = Clock()
    pacer = AdaptivePacer(10, monotonic=clock.monotonic, sleep=clock.sleep)
    assert pacer.rate == 10.0
    assert pacer.max_rate == 10.0


def test_adaptive_throttle_halves_rate_with_floor():
    clock = Clock()
    pacer = AdaptivePacer(
        8, min_rate=1.0, backoff=0.5, monotonic=clock.monotonic, sleep=clock.sleep
    )
    pacer.record_throttle()
    assert pacer.rate == 4.0
    pacer.record_throttle()
    assert pacer.rate == 2.0
    pacer.record_throttle()
    assert pacer.rate == 1.0
    pacer.record_throttle()
    assert pacer.rate == 1.0  # floored at min_rate, never below


def test_adaptive_recovers_additively_after_successes():
    clock = Clock()
    pacer = AdaptivePacer(
        10, backoff=0.5, recover_step=1.0, recover_after=3,
        monotonic=clock.monotonic, sleep=clock.sleep,
    )
    pacer.record_throttle()  # 10 -> 5
    assert pacer.rate == 5.0
    for _ in range(2):
        pacer.record_success()
    assert pacer.rate == 5.0  # not enough successes yet
    pacer.record_success()  # 3rd success -> +1
    assert pacer.rate == 6.0


def test_adaptive_recover_never_exceeds_ceiling():
    clock = Clock()
    pacer = AdaptivePacer(
        3, backoff=0.5, recover_step=1.0, recover_after=1,
        monotonic=clock.monotonic, sleep=clock.sleep,
    )
    pacer.record_throttle()  # 3 -> 1.5
    for _ in range(20):
        pacer.record_success()
    assert pacer.rate == 3.0  # clamped at max_rate


def test_adaptive_retry_after_opens_global_cooldown():
    clock = Clock()
    pacer = AdaptivePacer(10, monotonic=clock.monotonic, sleep=clock.sleep)
    # A Retry-After of 30s must make the *next* acquire wait out the full window.
    pacer.record_throttle(retry_after=30)
    slept = pacer.acquire()
    assert slept >= 30.0
    assert clock.slept and clock.slept[0] == 30.0


def test_adaptive_throttle_shrinks_burst_capacity():
    clock = Clock()
    pacer = AdaptivePacer(
        10, backoff=0.5, monotonic=clock.monotonic, sleep=clock.sleep
    )
    assert pacer.capacity == 10.0
    pacer.record_throttle()  # rate 10 -> 5
    assert pacer.capacity == 5.0
    # Tokens are clamped to the new capacity so a lowered rate is enforced.
    assert pacer._tokens <= 5.0
