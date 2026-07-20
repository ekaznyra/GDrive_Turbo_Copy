"""DriveClient must feed rate-limit signals back to the adaptive pacer.

These use a tiny fake ``service`` (no googleapiclient network calls) to drive the
retry path and assert the pacer receives throttle/success callbacks.
"""

from __future__ import annotations

from fakes import make_error
from gdrive_turbo_copy.drive_client import DriveClient
from gdrive_turbo_copy.retry import RetryPolicy


class RecordingPacer:
    def __init__(self) -> None:
        self.acquires = 0
        self.throttles: list[float | None] = []
        self.successes = 0

    def acquire(self, tokens: float = 1.0) -> float:
        self.acquires += 1
        return 0.0

    def record_throttle(self, *, retry_after: float | None = None) -> None:
        self.throttles.append(retry_after)

    def record_success(self) -> None:
        self.successes += 1


class _Request:
    def __init__(self, execute) -> None:
        self._execute = execute

    def execute(self):
        return self._execute()


class _Files:
    def __init__(self, execute) -> None:
        self._execute = execute

    def list(self, **_kwargs):
        return _Request(self._execute)


class _Service:
    def __init__(self, execute) -> None:
        self._execute = execute

    def files(self):
        return _Files(self._execute)


def _client(execute, pacer):
    # base/max delay 0 => full-jitter backoff is 0, so retries don't really sleep.
    return DriveClient(
        lambda: _Service(execute),
        pacer=pacer,
        retry_policy=RetryPolicy(max_attempts=5, base_delay=0.0, max_delay=0.0),
    )


def test_throttle_then_success_feeds_pacer():
    calls = {"n": 0}

    def execute():
        calls["n"] += 1
        if calls["n"] == 1:
            # retry_after=0 keeps the (real) sleep at zero while still exercising
            # the Retry-After forwarding path end-to-end.
            raise make_error(429, "rateLimitExceeded", retry_after=0)
        return {"files": [], "nextPageToken": None}

    pacer = RecordingPacer()
    files, token = _client(execute, pacer).list_children("folder0000000")

    assert files == [] and token is None
    assert pacer.throttles == [0.0]  # one throttle, Retry-After forwarded
    assert pacer.successes == 1  # one success recorded after the retry cleared
    assert pacer.acquires == 2  # paced before each HTTP attempt (incl. the retry)


def test_clean_call_records_success_only():
    def execute():
        return {"files": [], "nextPageToken": None}

    pacer = RecordingPacer()
    _client(execute, pacer).list_children("folder0000000")

    assert pacer.throttles == []
    assert pacer.successes == 1
    assert pacer.acquires == 1
