"""Retry classification and execution for Drive API calls.

Pure-Python and duck-typed: it does not import ``googleapiclient``. Any
exception exposing ``.resp.status`` and/or ``.content`` (as the Google
``HttpError`` does) is understood, which also makes it trivial to test with
fake error objects.
"""

from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Callable, TypeVar

from .logging_utils import get_logger, log_event
from .models import ErrorClass

T = TypeVar("T")

# Transient HTTP statuses (network/server hiccups + rate limiting).
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# 403 reasons that mean "slow down", not "you can't do this".
_RATE_LIMIT_REASONS = {"ratelimitexceeded", "userratelimitexceeded"}

# Fatal: never retry. Quota that resets only after ~24h, or hard limits.
_FATAL_QUOTA_REASONS = {
    "storagequotaexceeded",
    "dailylimitexceeded",
    "teamdrivefilelimitexceeded",
    "numchildreninnonrootlimitexceeded",
    "activeitemcreationlimitexceeded",
}
_FATAL_QUOTA_SUBSTRINGS = (
    "storagequotaexceeded",
    "dailylimitexceeded",
    "upload limit",
    "creation limit",
    "the number of children",
)
_FATAL_PERMISSION_REASONS = {"insufficientfilepermissions"}
# Copy-specific non-retryable reasons: the file simply cannot be copied. Named
# explicitly so they are never retried (even if the status is not 403) and so
# the failed report reason is precise.
_FATAL_SKIP_REASONS = {
    "cannotcopyfile",
    "filenotexportable",
    "downloadrestrictedforrevision",
    "cannotmodifyinheritedteamdrivepermission",
}


def parse_http_error(error: BaseException) -> tuple[str, str, int | None]:
    """Return ``(reason, message, status)`` extracted from an exception."""
    reason = ""
    message = str(error)
    status: int | None = None

    resp = getattr(error, "resp", None)
    if resp is not None:
        raw_status = getattr(resp, "status", None)
        if raw_status is None and isinstance(resp, dict):
            raw_status = resp.get("status")
        try:
            status = int(raw_status) if raw_status is not None else None
        except (TypeError, ValueError):
            status = None

    content = getattr(error, "content", None)
    if content is not None:
        try:
            if isinstance(content, (bytes, bytearray)):
                content = content.decode("utf-8", "replace")
            data = json.loads(content)
            err = data.get("error", {}) if isinstance(data, dict) else {}
            errors = err.get("errors") or []
            if errors:
                reason = errors[0].get("reason", "") or reason
                message = errors[0].get("message", message) or message
            else:
                message = err.get("message", message) or message
                reason = err.get("status", "") or reason
        except Exception:  # pragma: no cover - defensive parse
            pass
    return reason, message, status


def classify_error(error: BaseException) -> ErrorClass:
    """Classify an exception into a retry/fatal category."""
    reason, message, status = parse_http_error(error)
    reason_l = (reason or "").lower()
    blob = f"{message} {error}".lower()

    if reason_l in _FATAL_QUOTA_REASONS or any(s in blob for s in _FATAL_QUOTA_SUBSTRINGS):
        return ErrorClass.FATAL_QUOTA
    if reason_l in _RATE_LIMIT_REASONS:
        return ErrorClass.TRANSIENT
    if status in _RETRYABLE_STATUS:
        return ErrorClass.TRANSIENT
    if reason_l in _FATAL_SKIP_REASONS:
        return ErrorClass.FATAL_PERMISSION
    if reason_l in _FATAL_PERMISSION_REASONS or status in (401, 403, 404):
        return ErrorClass.FATAL_PERMISSION
    return ErrorClass.FATAL_OTHER


def parse_retry_after(error: BaseException, *, now: float | None = None) -> float | None:
    """Parse a ``Retry-After`` header (delta-seconds or HTTP-date) if present."""
    resp = getattr(error, "resp", None)
    if resp is None:
        return None
    value = None
    try:
        if isinstance(resp, dict):
            value = resp.get("retry-after") or resp.get("Retry-After")
        else:
            getter = getattr(resp, "get", None)
            if callable(getter):
                value = getter("retry-after")
    except Exception:  # pragma: no cover - defensive
        value = None
    if not value:
        return None
    # Numeric delta-seconds.
    try:
        return max(0.0, float(int(str(value).strip())))
    except (TypeError, ValueError):
        pass
    # HTTP-date.
    try:
        dt = parsedate_to_datetime(value)
        if dt is None:
            return None
        ref = now if now is not None else time.time()
        return max(0.0, dt.timestamp() - ref)
    except Exception:
        return None


def full_jitter_delay(
    attempt: int, *, base: float = 1.0, cap: float = 32.0, rng: random.Random = random
) -> float:
    """Exponential backoff with full jitter (AWS-style): ``U(0, min(cap, base*2^(n-1)))``."""
    exp = min(cap, base * (2 ** max(0, attempt - 1)))
    return rng.uniform(0, exp)


@dataclass
class RetryPolicy:
    max_attempts: int = 6
    base_delay: float = 1.0
    max_delay: float = 32.0


@dataclass
class RetryEvent:
    operation: str
    attempt: int
    max_attempts: int
    error_class: str
    reason: str
    status: int | None
    delay: float
    message: str
    retry_after: float | None = None


def execute_with_retry(
    func: Callable[[], T],
    *,
    operation: str = "drive_op",
    policy: RetryPolicy | None = None,
    rng: random.Random = random,
    sleep: Callable[[float], None] = time.sleep,
    logger: logging.Logger | None = None,
    on_event: Callable[[RetryEvent], None] | None = None,
) -> T:
    """Call ``func`` with retries on transient errors.

    Fatal errors (permission, missing, quota) are re-raised immediately. The
    ``sleep`` and ``rng`` parameters are injectable for deterministic tests.
    """
    policy = policy or RetryPolicy()
    logger = logger or get_logger("retry")
    attempt = 0
    while True:
        attempt += 1
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 - we classify then re-raise
            cls = classify_error(exc)
            reason, message, status = parse_http_error(exc)
            if cls is not ErrorClass.TRANSIENT or attempt >= policy.max_attempts:
                raise
            retry_after = parse_retry_after(exc)
            delay = (
                retry_after
                if retry_after is not None
                else full_jitter_delay(
                    attempt, base=policy.base_delay, cap=policy.max_delay, rng=rng
                )
            )
            event = RetryEvent(
                operation=operation,
                attempt=attempt,
                max_attempts=policy.max_attempts,
                error_class=cls.value,
                reason=reason or cls.value,
                status=status,
                delay=delay,
                message=message[:200],
                retry_after=retry_after,
            )
            log_event(
                logger,
                logging.WARNING,
                "drive_retry",
                op=operation,
                attempt=attempt,
                max_attempts=policy.max_attempts,
                status=status,
                reason=event.reason,
                delay=round(delay, 2),
                retry_after=retry_after is not None,
            )
            if on_event is not None:
                on_event(event)
            sleep(delay)
