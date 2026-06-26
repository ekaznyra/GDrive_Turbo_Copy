import random

import pytest

from fakes import FakeHttpError, make_error
from gdrive_turbo_copy.models import ErrorClass
from gdrive_turbo_copy.retry import (
    RetryPolicy,
    classify_error,
    execute_with_retry,
    full_jitter_delay,
    parse_retry_after,
)


@pytest.mark.parametrize(
    "status, reason, expected",
    [
        (429, "rateLimitExceeded", ErrorClass.TRANSIENT),
        (403, "userRateLimitExceeded", ErrorClass.TRANSIENT),
        (403, "rateLimitExceeded", ErrorClass.TRANSIENT),
        (500, "backendError", ErrorClass.TRANSIENT),
        (502, "", ErrorClass.TRANSIENT),
        (503, "", ErrorClass.TRANSIENT),
        (504, "", ErrorClass.TRANSIENT),
        (403, "storageQuotaExceeded", ErrorClass.FATAL_QUOTA),
        (403, "dailyLimitExceeded", ErrorClass.FATAL_QUOTA),
        (403, "teamDriveFileLimitExceeded", ErrorClass.FATAL_QUOTA),
        (403, "numChildrenInNonRootLimitExceeded", ErrorClass.FATAL_QUOTA),
        (403, "insufficientFilePermissions", ErrorClass.FATAL_PERMISSION),
        (404, "notFound", ErrorClass.FATAL_PERMISSION),
        (401, "authError", ErrorClass.FATAL_PERMISSION),
        (400, "badRequest", ErrorClass.FATAL_OTHER),
    ],
)
def test_classify(status, reason, expected):
    assert classify_error(make_error(status, reason)) is expected


def test_rate_limit_403_not_treated_as_permission():
    # A 403 that is a rate limit must be transient, not fatal-permission.
    assert classify_error(make_error(403, "userRateLimitExceeded")) is ErrorClass.TRANSIENT


def test_full_jitter_bounds():
    rng = random.Random(1234)
    for attempt in range(1, 8):
        for _ in range(50):
            d = full_jitter_delay(attempt, base=1.0, cap=32.0, rng=rng)
            assert 0.0 <= d <= min(32.0, 1.0 * 2 ** (attempt - 1))


def test_parse_retry_after_seconds():
    assert parse_retry_after(make_error(429, "rateLimitExceeded", retry_after=7)) == 7.0


def test_parse_retry_after_http_date():
    # Mon, 01 Jan 2035 00:00:10 GMT relative to a fixed "now".
    err = make_error(503, "", retry_after="Mon, 01 Jan 2035 00:00:10 GMT")
    import calendar
    import time as _t

    ref = calendar.timegm(_t.strptime("2035-01-01 00:00:00", "%Y-%m-%d %H:%M:%S"))
    delay = parse_retry_after(err, now=ref)
    assert delay is not None and 9.0 <= delay <= 11.0


def test_parse_retry_after_absent():
    assert parse_retry_after(make_error(429, "rateLimitExceeded")) is None


def test_execute_retries_then_succeeds():
    calls = {"n": 0}
    slept: list[float] = []

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise make_error(503, "backendError")
        return "ok"

    result = execute_with_retry(
        flaky, policy=RetryPolicy(max_attempts=5, base_delay=1, max_delay=8),
        rng=random.Random(0), sleep=slept.append,
    )
    assert result == "ok"
    assert calls["n"] == 3
    assert len(slept) == 2  # two retries before success


def test_execute_gives_up_after_max_attempts():
    def always():
        raise make_error(500, "backendError")

    with pytest.raises(FakeHttpError):
        execute_with_retry(always, policy=RetryPolicy(max_attempts=3), sleep=lambda d: None)


def test_execute_does_not_retry_fatal():
    calls = {"n": 0}

    def denied():
        calls["n"] += 1
        raise make_error(403, "insufficientFilePermissions")

    with pytest.raises(FakeHttpError):
        execute_with_retry(denied, policy=RetryPolicy(max_attempts=5), sleep=lambda d: None)
    assert calls["n"] == 1  # no retry


def test_execute_respects_retry_after():
    slept: list[float] = []
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise make_error(429, "rateLimitExceeded", retry_after=5)
        return "done"

    execute_with_retry(flaky, sleep=slept.append, rng=random.Random(0))
    assert slept == [5.0]


def test_retry_events_recorded():
    events = []
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise make_error(503, "backendError")
        return 1

    execute_with_retry(flaky, sleep=lambda d: None, on_event=events.append)
    assert len(events) == 1
    assert events[0].error_class == ErrorClass.TRANSIENT.value
