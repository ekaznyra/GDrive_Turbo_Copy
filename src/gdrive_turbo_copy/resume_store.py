"""Resume log: schema-versioned, integrity-hashed, atomic, Drive-backed.

The resume log lets an interrupted copy continue without re-copying. It is a
single JSON file stored *inside the destination root folder*, one per account
(``.gdrive_copy_resume.<account>.json``). Multiple accounts' logs in the same
destination are merged on load (their copied-id sets are unioned).

Pure serialization/migration/integrity logic is separated from the Drive I/O so
it can be unit-tested without any client.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .logging_utils import get_logger, log_event
from .models import TOOL_TAG, DriveClientProtocol, FailedItem, now_iso

CURRENT_SCHEMA_VERSION = 4
LOG_PREFIX = ".gdrive_copy_resume"
LOG_SUFFIX = ".json"
FAILED_REPORT_NAME = "failed_report.json"


class IntegrityError(Exception):
    """Raised when a resume log's integrity hash does not match its content."""


@dataclass
class ResumeState:
    schema_version: int = CURRENT_SCHEMA_VERSION
    account: str | None = None
    source_root_id: str | None = None
    dest_root_id: str | None = None
    run_id: str | None = None
    copied_ids: set[str] = field(default_factory=set)
    folder_map: dict[str, str] = field(default_factory=dict)
    completed_folders: set[str] = field(default_factory=set)
    failed_items: list[FailedItem] = field(default_factory=list)
    copied_bytes: int = 0
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)


# --- Pure serialization / migration / integrity ------------------------------


def _canonical_payload(state: ResumeState) -> dict[str, Any]:
    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "account": state.account,
        "source_root_id": state.source_root_id,
        "dest_root_id": state.dest_root_id,
        "run_id": state.run_id,
        "copied_file_ids": sorted(state.copied_ids),
        "folder_map": dict(sorted(state.folder_map.items())),
        "completed_folder_ids": sorted(state.completed_folders),
        "failed_items": [fi.to_dict() for fi in state.failed_items],
        "copied_bytes": int(state.copied_bytes),
        "created_at": state.created_at,
        "updated_at": state.updated_at,
    }


def compute_integrity(payload: dict[str, Any]) -> str:
    """SHA-256 over the canonical JSON of the payload excluding ``integrity``."""
    body = {k: v for k, v in payload.items() if k != "integrity"}
    raw = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def serialize(state: ResumeState) -> bytes:
    payload = _canonical_payload(state)
    payload["integrity"] = compute_integrity(payload)
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def migrate(raw: dict[str, Any]) -> dict[str, Any]:
    """Migrate a raw log dict (any prior schema) up to the current schema."""
    version = int(raw.get("schema_version", raw.get("version", 1)) or 1)
    data = dict(raw)
    if version < 2:
        # v1 used either "copied_ids" or "copied_file_ids".
        if "copied_file_ids" not in data:
            data["copied_file_ids"] = raw.get("copied_ids", [])
    if version < 3:
        # v2 tracked "lifetime_size_mb"; v3 tracks exact bytes + root ids + run id.
        if "copied_bytes" not in data:
            mb = float(raw.get("lifetime_size_mb", 0) or 0)
            data["copied_bytes"] = int(mb * 1024 * 1024)
        data.setdefault("source_root_id", None)
        data.setdefault("dest_root_id", None)
        data.setdefault("run_id", None)
    if version < 4:
        # v4 adds fully-copied subtree tracking for fast resume.
        data.setdefault("completed_folder_ids", [])
    data["schema_version"] = CURRENT_SCHEMA_VERSION
    return data


def deserialize(data: bytes | str, *, verify_integrity: bool = True) -> ResumeState:
    raw = json.loads(data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else data)
    if not isinstance(raw, dict):
        raise IntegrityError("Resume log is not a JSON object.")
    stored_hash = raw.get("integrity")
    if verify_integrity and stored_hash is not None:
        if compute_integrity(raw) != stored_hash:
            raise IntegrityError("Resume log integrity hash mismatch (possibly corrupted).")
    migrated = migrate(raw)
    copied = set(migrated.get("copied_file_ids", migrated.get("copied_ids", [])) or [])
    failed = [FailedItem.from_dict(d) for d in (migrated.get("failed_items") or [])]
    return ResumeState(
        schema_version=CURRENT_SCHEMA_VERSION,
        account=migrated.get("account"),
        source_root_id=migrated.get("source_root_id"),
        dest_root_id=migrated.get("dest_root_id"),
        run_id=migrated.get("run_id"),
        copied_ids=copied,
        folder_map=dict(migrated.get("folder_map") or {}),
        completed_folders=set(migrated.get("completed_folder_ids") or []),
        failed_items=failed,
        copied_bytes=int(migrated.get("copied_bytes", 0) or 0),
        created_at=migrated.get("created_at") or now_iso(),
        updated_at=migrated.get("updated_at") or now_iso(),
    )


def log_name_for(account: str | None) -> str:
    if account:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", account)
        return f"{LOG_PREFIX}.{safe}{LOG_SUFFIX}"
    return f"{LOG_PREFIX}{LOG_SUFFIX}"


# --- Drive-backed store ------------------------------------------------------


class ResumeStore:
    def __init__(self, client: DriveClientProtocol, *, logger: logging.Logger | None = None) -> None:
        self.client = client
        self.logger = logger or get_logger("resume")
        self.own_log_file_id: str | None = None
        self.own_log_name: str | None = None

    def load(
        self,
        parent_id: str,
        account: str | None,
        *,
        ignore_broken: bool = False,
        start_fresh: bool = False,
    ) -> ResumeState:
        """Load and merge all resume logs found in ``parent_id``.

        The current account's log is authoritative for scalar fields; every
        log's ``copied_ids`` are unioned to avoid re-copying across accounts.
        """
        self.own_log_name = log_name_for(account)
        merged = ResumeState(account=account, dest_root_id=parent_id)

        try:
            log_files = self._list_log_files(parent_id)
        except Exception as exc:
            if start_fresh:
                log_event(self.logger, logging.WARNING, "resume_list_failed_start_fresh", error=str(exc))
                return merged
            raise RuntimeError(
                f"Could not list resume logs ({exc}); stopping to avoid duplicate copies. "
                f"Pass start_fresh=True to ignore."
            ) from exc

        if not log_files:
            log_event(self.logger, logging.INFO, "resume_none_found", parent=parent_id)
            return merged

        for entry in log_files:
            try:
                raw = self.client.get_media(entry["id"])
                state = deserialize(raw)
            except Exception as exc:
                if not ignore_broken:
                    raise RuntimeError(
                        f"Could not read resume log {entry['name']}: {exc}. "
                        f"Pass ignore_broken=True to skip it."
                    ) from exc
                log_event(self.logger, logging.WARNING, "resume_log_skipped", name=entry["name"], error=str(exc))
                continue
            merged.copied_ids |= state.copied_ids
            for src, dst in state.folder_map.items():
                merged.folder_map.setdefault(src, dst)
            merged.completed_folders |= state.completed_folders
            merged.failed_items.extend(state.failed_items)
            if entry["name"] == self.own_log_name:
                self.own_log_file_id = entry["id"]
                merged.run_id = state.run_id
                merged.copied_bytes = state.copied_bytes
                merged.created_at = state.created_at
                merged.source_root_id = state.source_root_id or merged.source_root_id
                # folder_map is merged first-wins above (setdefault) so an existing
                # destination subfolder from any account is reused rather than
                # duplicated; the copier re-verifies each cached folder before use.
        log_event(
            self.logger,
            logging.INFO,
            "resume_loaded",
            logs=len(log_files),
            copied_ids=len(merged.copied_ids),
            prior_failures=len(merged.failed_items),
        )
        return merged

    def _list_log_files(self, parent_id: str) -> list[dict]:
        out: list[dict] = []
        page_token: str | None = None
        while True:
            files, page_token = self.client.list_children(parent_id, page_token=page_token)
            for f in files:
                if str(f.get("name", "")).startswith(LOG_PREFIX):
                    out.append(f)
            if not page_token:
                break
        return out

    def save(self, state: ResumeState) -> None:
        """Atomically persist ``state``.

        The full payload (with integrity hash) is built first, then written in a
        single Drive update/create call. Drive replaces file content atomically,
        and the integrity hash lets a torn/partial read be detected and rejected
        on load. Internal pointers are only updated after the API confirms.
        """
        state.updated_at = now_iso()
        data = serialize(state)
        if self.own_log_file_id:
            self.client.update_file_content(self.own_log_file_id, data)
            return
        created = self.client.create_json_file(
            self.own_log_name or log_name_for(state.account),
            state.dest_root_id or "",
            data,
            app_properties={"copied_by_tool": TOOL_TAG},
        )
        # Confirmed: only now record the file id.
        self.own_log_file_id = created.get("id")

    def export_failed_report(self, parent_id: str, failed: list[FailedItem]) -> None:
        if not failed or not parent_id:
            return
        report = {
            "generated_at": now_iso(),
            "total_failed": len(failed),
            "items": [fi.to_dict() for fi in failed],
        }
        data = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
        existing = self._find_owned(parent_id, FAILED_REPORT_NAME)
        if existing:
            self.client.update_file_content(existing, data)
        else:
            self.client.create_json_file(
                FAILED_REPORT_NAME, parent_id, data, app_properties={"copied_by_tool": TOOL_TAG}
            )

    def cleanup(self, parent_id: str) -> None:
        """Trash (never delete) tool-owned logs and the failed report."""
        page_token: str | None = None
        while True:
            files, page_token = self.client.list_children(parent_id, page_token=page_token)
            for f in files:
                ap = f.get("appProperties") or {}
                is_ours = ap.get("copied_by_tool") == TOOL_TAG
                name = str(f.get("name", ""))
                is_log = name.startswith(LOG_PREFIX)
                is_report = name == FAILED_REPORT_NAME
                if is_ours and (is_log or is_report):
                    try:
                        self.client.trash_file(f["id"])
                    except Exception as exc:  # pragma: no cover - best effort
                        log_event(self.logger, logging.WARNING, "resume_cleanup_failed", name=name, error=str(exc))
            if not page_token:
                break

    def _find_owned(self, parent_id: str, name: str) -> str | None:
        page_token: str | None = None
        while True:
            files, page_token = self.client.list_children(parent_id, page_token=page_token)
            for f in files:
                ap = f.get("appProperties") or {}
                if f.get("name") == name and ap.get("copied_by_tool") == TOOL_TAG:
                    return f["id"]
            if not page_token:
                break
        return None
