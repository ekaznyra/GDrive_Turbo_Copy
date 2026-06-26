"""Adaptive, per-operation concurrency control.

Each :class:`~gdrive_turbo_copy.models.OperationType` gets its own limiter.
The limiter starts at the configured ceiling, halves on throttling
(``record_throttle``), and creeps back up by one after a run of successes
(``record_success``). Acquisition blocks while in-flight work would exceed the
current limit, so even a fixed-size thread pool will naturally back off.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from .models import OperationType


@dataclass
class _Limiter:
    limit: int
    min_limit: int
    max_limit: int
    in_flight: int = 0
    successes: int = 0
    increase_after: int = 20


class AdaptiveConcurrencyController:
    def __init__(
        self,
        *,
        copy_workers: int,
        list_workers: int | None = None,
        create_workers: int | None = None,
        log_workers: int = 1,
        metadata_workers: int | None = None,
        increase_after: int = 20,
    ) -> None:
        copy_workers = max(1, copy_workers)
        list_max = list_workers if list_workers is not None else max(2, copy_workers)
        create_max = create_workers if create_workers is not None else max(1, copy_workers // 2 or 1)
        meta_max = metadata_workers if metadata_workers is not None else copy_workers
        self._cond = threading.Condition()
        self._limiters: dict[OperationType, _Limiter] = {
            OperationType.COPY: _Limiter(copy_workers, 1, copy_workers, increase_after=increase_after),
            OperationType.LIST: _Limiter(
                max(1, list_max), 1, max(1, list_max), increase_after=increase_after
            ),
            OperationType.CREATE_FOLDER: _Limiter(
                max(1, create_max), 1, max(1, create_max), increase_after=increase_after
            ),
            OperationType.LOG_UPDATE: _Limiter(max(1, log_workers), 1, max(1, log_workers)),
            OperationType.METADATA: _Limiter(
                max(1, meta_max), 1, max(1, meta_max), increase_after=increase_after
            ),
        }

    def slot(self, op: OperationType) -> _Slot:
        return _Slot(self, op)

    def _acquire(self, op: OperationType) -> None:
        limiter = self._limiters[op]
        with self._cond:
            while limiter.in_flight >= limiter.limit:
                self._cond.wait()
            limiter.in_flight += 1

    def _release(self, op: OperationType) -> None:
        limiter = self._limiters[op]
        with self._cond:
            limiter.in_flight -= 1
            self._cond.notify_all()

    def record_success(self, op: OperationType) -> None:
        limiter = self._limiters[op]
        with self._cond:
            limiter.successes += 1
            if limiter.successes >= limiter.increase_after and limiter.limit < limiter.max_limit:
                limiter.limit += 1
                limiter.successes = 0
                self._cond.notify_all()

    def record_throttle(self, op: OperationType) -> None:
        limiter = self._limiters[op]
        with self._cond:
            limiter.successes = 0
            limiter.limit = max(limiter.min_limit, limiter.limit // 2)

    def limits(self) -> dict[OperationType, int]:
        with self._cond:
            return {op: lim.limit for op, lim in self._limiters.items()}


class _Slot:
    def __init__(self, controller: AdaptiveConcurrencyController, op: OperationType) -> None:
        self._controller = controller
        self._op = op

    def __enter__(self) -> _Slot:
        self._controller._acquire(self._op)
        return self

    def __exit__(self, *exc: object) -> bool:
        self._controller._release(self._op)
        return False
