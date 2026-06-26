"""Concrete Drive API client.

This is the only core module (besides :mod:`auth`) that imports Google
libraries. It implements :class:`~gdrive_turbo_copy.models.DriveClientProtocol`,
wraps every call in :func:`~gdrive_turbo_copy.retry.execute_with_retry`, and
routes operations through an optional adaptive concurrency controller.

A fresh ``service`` object is built per thread (Google's client objects are not
thread-safe) via the injected ``service_factory``.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from typing import Callable

from googleapiclient.http import MediaInMemoryUpload

from .concurrency import AdaptiveConcurrencyController
from .logging_utils import get_logger
from .models import FOLDER_MIME, OperationType
from .retry import RetryEvent, RetryPolicy, execute_with_retry

_LIST_FIELDS = (
    "files(id,name,mimeType,size,md5Checksum,shortcutDetails,appProperties,trashed),"
    "nextPageToken"
)
_FILE_FIELDS = "id,name,mimeType,size,md5Checksum,shortcutDetails,appProperties,trashed,parents"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class DriveClient:
    def __init__(
        self,
        service_factory: Callable[[], object],
        *,
        controller: AdaptiveConcurrencyController | None = None,
        retry_policy: RetryPolicy | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._factory = service_factory
        self._local = threading.local()
        self._controller = controller
        self._policy = retry_policy or RetryPolicy()
        self._logger = logger or get_logger("drive")

    # -- internals ----------------------------------------------------------

    def _svc(self):
        svc = getattr(self._local, "svc", None)
        if svc is None:
            svc = self._factory()
            self._local.svc = svc
        return svc

    def _run(self, op: OperationType, build_request: Callable[[], object]):
        if self._controller is not None:
            with self._controller.slot(op):
                return self._exec(op, build_request)
        return self._exec(op, build_request)

    def _exec(self, op: OperationType, build_request: Callable[[], object]):
        def on_event(event: RetryEvent) -> None:
            if self._controller is None:
                return
            if event.status == 429 or event.reason.lower() in (
                "ratelimitexceeded",
                "userratelimitexceeded",
            ):
                self._controller.record_throttle(op)

        result = execute_with_retry(
            lambda: build_request().execute(),
            operation=op.value,
            policy=self._policy,
            logger=self._logger,
            on_event=on_event,
        )
        if self._controller is not None:
            self._controller.record_success(op)
        return result

    # -- protocol -----------------------------------------------------------

    def list_children(
        self,
        folder_id: str,
        *,
        exclude_substrings: Iterable[str] = (),
        order_by: str | None = None,
        page_token: str | None = None,
    ):
        query = f"'{folder_id}' in parents and trashed = false"
        excludes = [s for s in exclude_substrings if s]
        if excludes:
            clause = " and ".join(f"not name contains '{_escape(s)}'" for s in excludes)
            query += f" and ({clause})"

        def build():
            return self._svc().files().list(
                q=query,
                orderBy=order_by or "name, createdTime",
                pageSize=1000,
                fields=_LIST_FIELDS,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )

        res = self._run(OperationType.LIST, build)
        return res.get("files", []), res.get("nextPageToken")

    def get_metadata(self, file_id: str, *, fields: str | None = None):
        def build():
            return self._svc().files().get(
                fileId=file_id, fields=fields or _FILE_FIELDS, supportsAllDrives=True
            )

        return self._run(OperationType.METADATA, build)

    def copy_file(self, file_id: str, body: dict):
        def build():
            return self._svc().files().copy(
                fileId=file_id, body=body, fields="id", supportsAllDrives=True
            )

        return self._run(OperationType.COPY, build)

    def create_folder(self, name: str, parent_id: str, *, app_properties: dict | None = None):
        body = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
        if app_properties:
            body["appProperties"] = app_properties

        def build():
            return self._svc().files().create(body=body, fields="id", supportsAllDrives=True)

        return self._run(OperationType.CREATE_FOLDER, build)

    def search(
        self,
        query: str,
        *,
        fields: str | None = None,
        page_size: int = 100,
        page_token: str | None = None,
    ):
        def build():
            return self._svc().files().list(
                q=query,
                fields=fields or _LIST_FIELDS,
                pageSize=page_size,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )

        res = self._run(OperationType.LIST, build)
        return res.get("files", []), res.get("nextPageToken")

    def get_media(self, file_id: str) -> bytes:
        def build():
            return self._svc().files().get_media(fileId=file_id)

        return self._run(OperationType.METADATA, build)

    def create_json_file(
        self, name: str, parent_id: str, data: bytes, *, app_properties: dict | None = None
    ):
        body: dict = {"name": name, "parents": [parent_id]}
        if app_properties:
            body["appProperties"] = app_properties

        def build():
            # Fresh media per attempt: MediaInMemoryUpload streams are single-use.
            media = MediaInMemoryUpload(data, mimetype="application/json", resumable=False)
            return self._svc().files().create(
                body=body, media_body=media, fields="id", supportsAllDrives=True
            )

        return self._run(OperationType.LOG_UPDATE, build)

    def update_file_content(self, file_id: str, data: bytes):
        def build():
            # Fresh media per attempt: MediaInMemoryUpload streams are single-use.
            media = MediaInMemoryUpload(data, mimetype="application/json", resumable=False)
            return self._svc().files().update(
                fileId=file_id, media_body=media, supportsAllDrives=True
            )

        return self._run(OperationType.LOG_UPDATE, build)

    def trash_file(self, file_id: str) -> None:
        def build():
            return self._svc().files().update(
                fileId=file_id, body={"trashed": True}, supportsAllDrives=True
            )

        self._run(OperationType.LOG_UPDATE, build)

    def about_user(self) -> dict:
        def build():
            return self._svc().about().get(fields="user(emailAddress)")

        return self._run(OperationType.METADATA, build)
