"""Dataclasses, enums, constants, and the Drive client protocol.

This module is pure-Python: it imports no Google libraries so it can be used
directly in unit tests.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

# --- Constants ---------------------------------------------------------------

FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
GOOGLE_NATIVE_PREFIX = "application/vnd.google-apps."
TOOL_TAG = "GDrive_Turbo_Copy"

GIB = 1024**3
DEFAULT_WORKERS = 4
MAX_WORKERS = 16
WORKER_WARN_THRESHOLD = 8
# Slightly below Google's documented ~750 GB/day upload+copy quota to leave
# headroom and stop *before* hitting the hard limit. NOTE: server-side copy has
# its own (lower) effective ceiling and a per-second rate limit; the rate-limit
# circuit breaker handles the latter, and the run always stops gracefully on
# Google's own quota signal regardless of this byte budget. 0 = unlimited.
DEFAULT_MAX_COPY_SIZE_GB = 730.0
# Drive rejects copying a single file larger than the daily copy cap (~750 GB).
MAX_SINGLE_FILE_COPY_GB = 750.0
# Proactive client-side pacing: Drive's sustained write ceiling is low
# (~10 ops/sec/project). A token bucket below this avoids most 429s entirely.
# This is the *ceiling*; the AdaptivePacer starts here and auto-tunes the actual
# sustained rate down on throttling and back up on sustained success (AIMD).
DEFAULT_MAX_TPS = 10.0
# Stop gracefully after this many consecutive copy ops exhaust retries on rate
# limiting (a strong signal the daily/server-side-copy cap is hit; retrying for
# 24h is futile).
RATE_LIMIT_STOP_THRESHOLD = 8
# appProperties: each entry's key+value must be <= 124 bytes (UTF-8); <=30
# private entries per file (Drive limits).
APPPROP_MAX_ENTRY_BYTES = 124
APPPROP_MAX_ENTRIES = 30


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def validate_app_properties(props: dict[str, str]) -> None:
    """Raise ValueError if appProperties would violate Drive's documented limits."""
    if len(props) > APPPROP_MAX_ENTRIES:
        raise ValueError(f"appProperties has {len(props)} entries (>{APPPROP_MAX_ENTRIES}).")
    for key, value in props.items():
        size = len(str(key).encode("utf-8")) + len(str(value).encode("utf-8"))
        if size > APPPROP_MAX_ENTRY_BYTES:
            raise ValueError(
                f"appProperties entry {key!r} is {size} bytes (>{APPPROP_MAX_ENTRY_BYTES})."
            )


# --- Enums -------------------------------------------------------------------


class VerifyMode(str, Enum):
    """How an existing destination file is matched against a source file."""

    CHECKSUM = "checksum"  # strict: md5 only
    NAME_SIZE = "name_size"  # md5 first, then fall back to name+size
    NAME_ONLY = "name_only"  # unsafe; only used when explicitly allowed


class OperationType(str, Enum):
    """Drive operation categories for separate concurrency/rate control."""

    LIST = "list"
    COPY = "copy"
    CREATE_FOLDER = "create_folder"
    LOG_UPDATE = "log_update"
    METADATA = "metadata"


class ErrorClass(str, Enum):
    TRANSIENT = "transient"
    FATAL_QUOTA = "fatal_quota"
    FATAL_PERMISSION = "fatal_permission"
    FATAL_OTHER = "fatal_other"


# --- Control-flow exception --------------------------------------------------


class QuotaStopped(Exception):
    """Raised internally to unwind the copy when a quota/size limit is hit."""


# --- Drive file model --------------------------------------------------------


@dataclass
class DriveFile:
    id: str
    name: str
    mime_type: str
    size: int | None = None
    md5: str | None = None
    shortcut_target_id: str | None = None
    app_properties: dict[str, str] = field(default_factory=dict)
    trashed: bool = False
    modified_time: str | None = None
    created_time: str | None = None
    description: str | None = None

    @property
    def is_folder(self) -> bool:
        return self.mime_type == FOLDER_MIME

    @property
    def is_shortcut(self) -> bool:
        return self.mime_type == SHORTCUT_MIME

    @property
    def is_google_native(self) -> bool:
        return (
            self.mime_type.startswith(GOOGLE_NATIVE_PREFIX)
            and not self.is_folder
            and not self.is_shortcut
        )

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> DriveFile:
        size = data.get("size")
        try:
            size_val: int | None = int(size) if size is not None else None
        except (TypeError, ValueError):
            size_val = None
        shortcut = data.get("shortcutDetails") or {}
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            mime_type=data.get("mimeType", ""),
            size=size_val,
            md5=data.get("md5Checksum"),
            shortcut_target_id=shortcut.get("targetId"),
            app_properties=dict(data.get("appProperties") or {}),
            trashed=bool(data.get("trashed", False)),
            modified_time=data.get("modifiedTime"),
            created_time=data.get("createdTime"),
            description=data.get("description"),
        )


# --- Config ------------------------------------------------------------------


@dataclass
class CopyConfig:
    source_link: str
    dest_link: str
    workers: int = DEFAULT_WORKERS
    max_copy_size_gb: float = DEFAULT_MAX_COPY_SIZE_GB
    verify_mode: VerifyMode = VerifyMode.CHECKSUM
    exclude_substrings: list[str] = field(default_factory=list)
    dry_run: bool = False
    from_page: int = 0
    to_page: int = 0
    allow_name_only: bool = False
    max_tps: float = DEFAULT_MAX_TPS  # proactive client-side rate cap (0 = off)
    preserve_metadata: bool = True  # copy modifiedTime/createdTime/description
    ignore_default_visibility: bool = False  # opt-in: bypass domain default sharing
    keep_revision_forever: bool = False  # opt-in: pin the copy's head revision
    fast_list: bool = False  # opt-in: batch sibling folders into one list call
    skip_completed_folders: bool = False  # opt-in: on resume, skip re-listing subtrees copied in full

    def validate(self) -> list[str]:
        from .urls import extract_folder_id

        errors: list[str] = []
        if not (self.source_link or "").strip():
            errors.append("Source link must not be empty.")
        elif not extract_folder_id(self.source_link):
            errors.append("Source link is invalid (no folder id found).")
        if not (self.dest_link or "").strip():
            errors.append("Destination link must not be empty.")
        elif not extract_folder_id(self.dest_link):
            errors.append("Destination link is invalid (no folder id found).")
        if not (1 <= self.workers <= MAX_WORKERS):
            errors.append(f"workers must be between 1 and {MAX_WORKERS} (got {self.workers}).")
        if self.max_copy_size_gb < 0:
            errors.append(f"max_copy_size_gb must be >= 0 (got {self.max_copy_size_gb}).")
        if self.max_tps < 0:
            errors.append(f"max_tps must be >= 0 (got {self.max_tps}).")
        if self.from_page < 0:
            errors.append(f"from_page must be >= 0 (got {self.from_page}).")
        if self.to_page < 0:
            errors.append(f"to_page must be >= 0 (got {self.to_page}).")
        if self.from_page and self.to_page and self.from_page > self.to_page:
            errors.append(f"from_page ({self.from_page}) must be <= to_page ({self.to_page}).")
        return errors


# --- Failed item -------------------------------------------------------------


@dataclass
class FailedItem:
    source_id: str
    name: str
    mime_type: str
    reason: str
    error_message: str
    timestamp: str = field(default_factory=now_iso)
    parent_source_id: str | None = None
    shortcut_target_id: str | None = None
    source_shortcut_id: str | None = None
    effective_source_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FailedItem:
        return cls(
            source_id=data.get("source_id", ""),
            name=data.get("name", "?"),
            mime_type=data.get("mimeType", data.get("mime_type", "")),
            reason=data.get("reason", "unknown"),
            error_message=data.get("error_message", ""),
            timestamp=data.get("timestamp", now_iso()),
            parent_source_id=data.get("parent_source_id"),
            shortcut_target_id=data.get("shortcut_target_id"),
            source_shortcut_id=data.get("source_shortcut_id"),
            effective_source_id=data.get("effective_source_id"),
        )


# --- Result ------------------------------------------------------------------


@dataclass
class CopyResult:
    copied_count: int = 0
    skipped_count: int = 0
    skipped_complete_folders: int = 0
    failed_items: list[FailedItem] = field(default_factory=list)
    previous_failed_items: list[FailedItem] = field(default_factory=list)
    would_copy_count: int = 0
    would_copy_bytes: int = 0
    copied_bytes: int = 0
    had_listing_errors: bool = False
    completed: bool = False
    stop_reason: str | None = None
    dry_run: bool = False
    log_save_failed: bool = False
    log_save_error: str | None = None

    @property
    def has_failures(self) -> bool:
        return bool(self.failed_items or self.previous_failed_items)

    @property
    def fully_ok(self) -> bool:
        return (
            self.completed
            and not self.has_failures
            and not self.had_listing_errors
            and not self.dry_run
            and not self.log_save_failed
        )


# --- Drive client protocol ---------------------------------------------------


@runtime_checkable
class DriveClientProtocol(Protocol):
    """Contract the copier and resume store depend on.

    A real implementation lives in :mod:`gdrive_turbo_copy.drive_client`; tests
    supply an in-memory fake. All methods return raw API-shaped dicts.
    """

    def list_children(
        self,
        folder_id: str,
        *,
        exclude_substrings: Iterable[str] = (),
        order_by: str | None = None,
        page_token: str | None = None,
    ) -> tuple[list[dict], str | None]: ...

    def list_children_multi(
        self,
        parent_ids: list[str],
        *,
        exclude_substrings: Iterable[str] = (),
        page_token: str | None = None,
    ) -> tuple[list[dict], str | None]: ...

    def get_metadata(self, file_id: str, *, fields: str | None = None) -> dict: ...

    def copy_file(
        self,
        file_id: str,
        body: dict,
        *,
        ignore_default_visibility: bool = False,
        keep_revision_forever: bool = False,
    ) -> dict: ...

    def create_folder(
        self, name: str, parent_id: str, *, app_properties: dict | None = None
    ) -> dict: ...

    def search(
        self,
        query: str,
        *,
        fields: str | None = None,
        page_size: int = 100,
        page_token: str | None = None,
    ) -> tuple[list[dict], str | None]: ...

    def get_media(self, file_id: str) -> bytes: ...

    def create_json_file(
        self, name: str, parent_id: str, data: bytes, *, app_properties: dict | None = None
    ) -> dict: ...

    def update_file_content(self, file_id: str, data: bytes) -> dict: ...

    def trash_file(self, file_id: str) -> None: ...

    def about_user(self) -> dict: ...
