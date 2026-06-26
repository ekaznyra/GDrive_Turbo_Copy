from gdrive_turbo_copy.pacer import NullPacer, TokenBucket, make_pacer


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
    assert isinstance(make_pacer(10), TokenBucket)
