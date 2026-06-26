"""The copy engine.

Imports no Google libraries: it depends on the
:class:`~gdrive_turbo_copy.models.DriveClientProtocol`, so it can be driven by
the real :class:`~gdrive_turbo_copy.drive_client.DriveClient` or an in-memory
fake in tests.
"""

from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from dataclasses import dataclass, field

from .logging_utils import get_logger, log_event
from .models import (
    GIB,
    TOOL_TAG,
    WORKER_WARN_THRESHOLD,
    CopyConfig,
    CopyResult,
    DriveClientProtocol,
    DriveFile,
    ErrorClass,
    FailedItem,
    QuotaStopped,
    VerifyMode,
)
from .resume_store import ResumeState, ResumeStore
from .retry import classify_error, parse_http_error
from .urls import extract_folder_id

# --- Duplicate detection (pure, unit-tested) ---------------------------------


@dataclass
class DestinationIndex:
    """Index of files already present in a destination folder."""

    app_props: dict[str, DriveFile] = field(default_factory=dict)
    by_name: dict[str, list[DriveFile]] = field(default_factory=dict)

    @classmethod
    def build(cls, items: list[DriveFile]) -> DestinationIndex:
        idx = cls()
        for item in items:
            if item.is_folder:
                continue
            key = item.app_properties.get("source_shortcut_id") or item.app_properties.get(
                "source_file_id"
            )
            if key:
                idx.app_props[key] = item
            idx.by_name.setdefault(item.name, []).append(item)
        return idx

    def _remove_from_name(self, item: DriveFile) -> None:
        cands = self.by_name.get(item.name)
        if cands and item in cands:
            cands.remove(item)
            if not cands:
                self.by_name.pop(item.name, None)

    def pop_by_app_prop(self, effective_id: str | None) -> DriveFile | None:
        """Strict appProperties-only match (used when trusting a resume entry)."""
        if not effective_id:
            return None
        item = self.app_props.pop(effective_id, None)
        if item is not None:
            self._remove_from_name(item)
        return item

    def pop_match(
        self,
        source: DriveFile,
        *,
        verify_mode: VerifyMode,
        allow_name_only: bool,
        effective_id: str | None = None,
    ) -> DriveFile | None:
        """Find (and consume) a destination file matching ``source``."""
        eff = effective_id or source.id
        by_prop = self.pop_by_app_prop(eff)
        if by_prop is not None:
            return by_prop

        cands = self.by_name.get(source.name)
        if not cands:
            return None

        def same_size(item: DriveFile) -> bool:
            return source.size is not None and item.size is not None and source.size == item.size

        def same_md5(item: DriveFile) -> bool:
            return bool(source.md5 and item.md5 and source.md5 == item.md5)

        match: DriveFile | None = None
        if verify_mode is VerifyMode.NAME_ONLY:
            if allow_name_only:
                match = cands[0]
        elif verify_mode is VerifyMode.CHECKSUM:
            match = next((c for c in cands if same_md5(c)), None)
        else:  # NAME_SIZE: md5 first, then size
            match = next((c for c in cands if same_md5(c)), None)
            if match is None and source.size is not None:
                match = next((c for c in cands if same_size(c)), None)

        if match is None:
            return None
        self._remove_from_name(match)
        if match in self.app_props.values():
            for k, v in list(self.app_props.items()):
                if v is match:
                    self.app_props.pop(k, None)
        return match


# --- Engine ------------------------------------------------------------------


def generate_run_id() -> str:
    return uuid.uuid4().hex


class Copier:
    def __init__(
        self,
        client: DriveClientProtocol,
        config: CopyConfig,
        *,
        resume_store: ResumeStore | None = None,
        logger: logging.Logger | None = None,
        run_id: str | None = None,
    ) -> None:
        self.client = client
        self.config = config
        self.log = logger or get_logger("copier")
        self.resume = resume_store or ResumeStore(client, logger=self.log)
        self.run_id = run_id or generate_run_id()

        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._state = ResumeState(run_id=self.run_id)
        self._result = CopyResult(dry_run=config.dry_run)
        self._executor: ThreadPoolExecutor | None = None
        self._futures: set = set()
        self._dirty = 0
        self._flush_every = 50
        self._progress_every = 25
        self._copied_session = 0
        self._run_bytes = 0  # bytes reserved/copied this run (drives the size guard)

    # -- public -------------------------------------------------------------

    def run(self) -> CopyResult:
        cfg = self.config
        errors = cfg.validate()
        if errors:
            self._result.stop_reason = "Invalid input: " + "; ".join(errors)
            for err in errors:
                log_event(self.log, logging.ERROR, "invalid_input", detail=err)
            return self._result

        log_event(
            self.log,
            logging.INFO,
            "legal_notice",
            note="Only copy data you are legally permitted to access. "
            "Permissions, comments and revision history are NOT copied.",
        )

        source_id = extract_folder_id(cfg.source_link)
        dest_parent_id = extract_folder_id(cfg.dest_link)
        assert source_id and dest_parent_id  # validated above

        account = self._account_id()
        self._state.account = account
        self._state.source_root_id = source_id

        # Safety: destination must not be the source or inside the source tree.
        if dest_parent_id == source_id or self._is_descendant_of(dest_parent_id, source_id):
            self._result.stop_reason = (
                "Destination equals or is inside the source tree; this would recurse infinitely. "
                "Choose a destination outside the source."
            )
            log_event(self.log, logging.ERROR, "unsafe_destination", reason=self._result.stop_reason)
            return self._result

        try:
            src_meta = self.client.get_metadata(source_id, fields="id,name,mimeType")
        except Exception as exc:
            self._result.stop_reason = f"Cannot access source folder: {exc}"
            log_event(self.log, logging.ERROR, "source_inaccessible", error=str(exc))
            return self._result
        src_root = DriveFile.from_api(src_meta)

        try:
            dest_root_id = self._get_or_create_folder(
                dest_parent_id, src_root.name, source_folder_id=source_id
            )
        except QuotaStopped:
            return self._finalize(None, completed=False)
        except RuntimeError as exc:
            self._result.stop_reason = f"Could not create destination root folder: {exc}"
            log_event(self.log, logging.ERROR, "dest_root_failed", error=str(exc))
            return self._result
        self._state.dest_root_id = dest_root_id

        if dest_root_id:
            try:
                loaded = self.resume.load(dest_root_id, account)
            except RuntimeError as exc:
                self._result.stop_reason = str(exc)
                log_event(self.log, logging.ERROR, "resume_load_failed", error=str(exc))
                return self._result
            self._merge_resume(loaded)

        workers = max(1, min(cfg.workers, 16))
        if workers > WORKER_WARN_THRESHOLD:
            log_event(self.log, logging.WARNING, "high_worker_count", workers=workers)
        self._executor = ThreadPoolExecutor(max_workers=workers) if workers > 1 else None
        log_event(self.log, logging.INFO, "run_start", run_id=self.run_id, workers=workers, dry_run=cfg.dry_run)

        completed = False
        try:
            root_children = self._list_children(
                source_id, cfg.from_page, cfg.to_page, parent_source_id=source_id
            )
            log_event(self.log, logging.INFO, "root_listed", items=len(root_children))
            self._process_level(dest_root_id, root_children, {source_id}, parent_source_id=source_id)
            self._drain_futures()
            completed = not self._stop.is_set()
        except QuotaStopped:
            completed = False
        finally:
            if self._executor is not None:
                self._executor.shutdown(wait=True)
                self._executor = None
            if not cfg.dry_run and dest_root_id:
                self._save_log(force=True)

        return self._finalize(dest_root_id, completed)

    # -- recursion ----------------------------------------------------------

    def _process_level(
        self,
        dest_parent_id: str | None,
        children: list[DriveFile],
        visited: set[str],
        *,
        parent_source_id: str,
    ) -> None:
        index = self._build_index(dest_parent_id)
        for src in children:
            if self._stop.is_set():
                break
            if src.is_folder or src.is_shortcut:
                self._handle_container(dest_parent_id, src, index, visited, parent_source_id)
            else:
                self._submit_file(dest_parent_id, src, index, parent_source_id)

    def _handle_container(
        self,
        dest_parent_id: str | None,
        src: DriveFile,
        index: DestinationIndex,
        visited: set[str],
        parent_source_id: str,
    ) -> None:
        if src.is_shortcut:
            target = self._resolve_shortcut(src)
            if target is None:
                self._record_failed(
                    src,
                    reason="cannotAccessShortcutTarget",
                    message="Shortcut target is inaccessible.",
                    parent_source_id=parent_source_id,
                    source_shortcut_id=src.id,
                    shortcut_target_id=src.shortcut_target_id,
                    effective_source_id=src.id,
                )
                return
            if target.is_folder:
                self._copy_folder(dest_parent_id, target, visited, parent_source_id, shortcut_id=src.id)
            else:
                self._copy_file(dest_parent_id, target, index, parent_source_id, shortcut_id=src.id)
            return
        self._copy_folder(dest_parent_id, src, visited, parent_source_id, shortcut_id=None)

    def _copy_folder(
        self,
        dest_parent_id: str | None,
        folder: DriveFile,
        visited: set[str],
        parent_source_id: str,
        *,
        shortcut_id: str | None,
    ) -> None:
        if folder.id in visited:
            log_event(self.log, logging.WARNING, "shortcut_loop_skipped", folder=folder.name, id=folder.id)
            return
        log_event(self.log, logging.INFO, "folder_enter", name=folder.name)
        try:
            sub_dest_id = self._get_or_create_folder(
                dest_parent_id, folder.name, source_folder_id=folder.id, shortcut_id=shortcut_id
            )
        except QuotaStopped:
            raise
        except RuntimeError as exc:
            self._record_failed(
                folder, reason="createFolderFailed", message=str(exc),
                parent_source_id=parent_source_id, source_shortcut_id=shortcut_id,
                effective_source_id=shortcut_id or folder.id,
            )
            return
        children = self._list_children(folder.id, 0, 0, parent_source_id=folder.id)
        if children and (sub_dest_id or self.config.dry_run):
            self._process_level(
                sub_dest_id, children, visited | {folder.id}, parent_source_id=folder.id
            )

    # -- file copy ----------------------------------------------------------

    def _submit_file(
        self,
        dest_parent_id: str | None,
        src: DriveFile,
        index: DestinationIndex,
        parent_source_id: str,
    ) -> None:
        if self._executor is None:
            self._copy_file(dest_parent_id, src, index, parent_source_id)
            return
        max_pending = max(self.config.workers * 4, 16)
        with self._lock:
            pending = len(self._futures)
        if pending >= max_pending:
            with self._lock:
                snapshot = set(self._futures)
            done, _ = wait(snapshot, return_when=FIRST_COMPLETED)
            with self._lock:
                self._futures -= done
            for fut in done:
                self._consume_future(fut)
        if self._stop.is_set():
            return
        fut = self._executor.submit(
            self._copy_file_worker, dest_parent_id, src, index, parent_source_id
        )
        with self._lock:
            self._futures.add(fut)

    def _copy_file_worker(self, dest_parent_id, src, index, parent_source_id) -> None:
        if self._stop.is_set():
            return
        try:
            self._copy_file(dest_parent_id, src, index, parent_source_id)
        except QuotaStopped:
            pass
        except Exception as exc:  # noqa: BLE001 - record unexpected worker failure
            reason, message, _ = parse_http_error(exc)
            self._record_failed(
                src, reason=reason or "workerError", message=message or str(exc),
                parent_source_id=parent_source_id, effective_source_id=src.id,
            )

    def _copy_file(
        self,
        dest_parent_id: str | None,
        src: DriveFile,
        index: DestinationIndex,
        parent_source_id: str,
        *,
        shortcut_id: str | None = None,
    ) -> None:
        eff_id = shortcut_id or src.id
        if self._stop.is_set():
            return

        # 1) Resume-log fast path: trust only if confirmed by appProperties at dest.
        with self._lock:
            already = eff_id in self._state.copied_ids
        if already:
            with self._lock:
                existing = index.pop_by_app_prop(eff_id)
                if existing is not None:
                    self._result.skipped_count += 1
                else:
                    self._state.copied_ids.discard(eff_id)
            if existing is not None:
                self._reconcile_failed(eff_id, src)
                return

        # 2) Detect a matching file already at the destination.
        with self._lock:
            existing = index.pop_match(
                src,
                verify_mode=self.config.verify_mode,
                allow_name_only=self.config.allow_name_only,
                effective_id=eff_id,
            )
        if existing is not None:
            self._record_existing(eff_id)
            self._reconcile_failed(eff_id, src)
            return

        size = src.size or 0
        if self.config.dry_run:
            with self._lock:
                self._result.would_copy_count += 1
                self._result.would_copy_bytes += size
            return

        # 3) Quota / size guard: reserve bytes *under the lock* before copying so
        #    concurrent workers cannot collectively overshoot the budget.
        with self._lock:
            projected = self._run_bytes + size
            if self.config.max_copy_size_gb > 0 and projected > self.config.max_copy_size_gb * GIB:
                self._result.stop_reason = (
                    f"Reached max copy size {self.config.max_copy_size_gb} GB before copying "
                    f"'{src.name}' ({size / GIB:.2f} GB). Re-run later to continue from the resume log."
                )
                self._stop.set()
                raise QuotaStopped(self._result.stop_reason)
            self._run_bytes += size  # reserve

        # 4) Server-side copy with idempotency appProperties.
        app_props = {
            "source_file_id": src.id,
            "source_md5": src.md5 or "",
            "copied_by_tool": TOOL_TAG,
        }
        if shortcut_id:
            app_props["source_shortcut_id"] = shortcut_id
        body = {"name": src.name, "parents": [dest_parent_id], "appProperties": app_props}
        try:
            created = self.client.copy_file(src.id, body)
        except QuotaStopped:
            raise
        except Exception as exc:  # noqa: BLE001
            self._release_reservation(size)
            self._handle_copy_exception(exc, src, parent_source_id, shortcut_id, eff_id)
            return

        new_id = created.get("id") if isinstance(created, dict) else None
        ok, detail = self._verify_copy(new_id, src, shortcut_id)
        if not ok:
            self._release_reservation(size)
            self._record_failed(
                src, reason="verificationFailed", message=detail,
                parent_source_id=parent_source_id, source_shortcut_id=shortcut_id,
                effective_source_id=eff_id,
            )
            return
        self._mark_copied(eff_id, size)
        self._reconcile_failed(eff_id, src)

    def _raise_if_fatal_quota(self, exc: Exception, context: str) -> None:
        """If ``exc`` is a fatal quota error, stop the run gracefully and raise QuotaStopped."""
        if classify_error(exc) is not ErrorClass.FATAL_QUOTA:
            return
        reason, message, _ = parse_http_error(exc)
        self._result.stop_reason = (
            f"Daily Drive copy/upload quota hit while {context}: "
            f"{reason or 'quotaExceeded'} — {message}. Re-run after the quota resets (~24h); "
            f"the resume log preserves progress."
        )
        self._stop.set()
        if self._state.dest_root_id and not self.config.dry_run:
            try:
                self._save_log(force=True)
            except Exception:  # pragma: no cover
                pass
        raise QuotaStopped(self._result.stop_reason)

    def _handle_copy_exception(self, exc, src, parent_source_id, shortcut_id, eff_id) -> None:
        self._raise_if_fatal_quota(exc, f"copying '{src.name}'")
        reason, message, _ = parse_http_error(exc)
        self._record_failed(
            src, reason=reason or "copyFailed", message=message or str(exc),
            parent_source_id=parent_source_id,
            shortcut_target_id=(src.id if shortcut_id else None),
            source_shortcut_id=shortcut_id, effective_source_id=eff_id,
        )

    def _verify_copy(
        self, new_id: str | None, src: DriveFile, shortcut_id: str | None
    ) -> tuple[bool, str]:
        if not new_id:
            return False, "copy returned no file id"
        try:
            meta = self.client.get_metadata(
                new_id, fields="id,name,mimeType,size,md5Checksum,appProperties"
            )
        except Exception as exc:  # noqa: BLE001
            return False, f"could not fetch copied file metadata: {exc}"
        dst = DriveFile.from_api(meta)
        ap = dst.app_properties
        if ap.get("source_file_id") != src.id:
            return False, "appProperties.source_file_id mismatch"
        if shortcut_id and ap.get("source_shortcut_id") != shortcut_id:
            return False, "appProperties.source_shortcut_id mismatch"
        if dst.name != src.name:
            return False, f"name mismatch ({dst.name!r} != {src.name!r})"
        if src.mime_type and dst.mime_type and src.mime_type != dst.mime_type:
            return False, f"mimeType mismatch ({dst.mime_type!r} != {src.mime_type!r})"
        if src.is_google_native or (src.md5 is None and src.size is None):
            # Native Docs/Sheets/Slides have no md5/size; ID + MIME + name + appProps verified above.
            return True, ""
        if src.md5 and dst.md5 and src.md5 != dst.md5:
            return False, "md5 checksum mismatch"
        if src.size is not None and dst.size is not None and src.size != dst.size:
            return False, f"size mismatch ({dst.size} != {src.size})"
        return True, ""

    # -- folders & shortcuts -----------------------------------------------

    def _get_or_create_folder(
        self,
        dest_parent_id: str | None,
        name: str,
        *,
        source_folder_id: str | None = None,
        shortcut_id: str | None = None,
    ) -> str | None:
        if dest_parent_id is None:
            # dry-run with no created parent yet.
            return None
        effective_key = shortcut_id or source_folder_id
        if effective_key:
            with self._lock:
                cached = self._state.folder_map.get(effective_key)
            if cached and self._verify_dest_folder(cached, effective_key, bool(shortcut_id)):
                return cached
            existing = self._find_dest_folder(dest_parent_id, source_folder_id, shortcut_id)
            if existing:
                with self._lock:
                    self._state.folder_map[effective_key] = existing
                return existing
        if self.config.dry_run:
            return None
        app_props = {"copied_by_tool": TOOL_TAG}
        if shortcut_id:
            app_props["source_shortcut_id"] = shortcut_id
            if source_folder_id:
                app_props["shortcut_target_id"] = source_folder_id
        elif source_folder_id:
            app_props["source_folder_id"] = source_folder_id
        try:
            created = self.client.create_folder(name, dest_parent_id, app_properties=app_props)
        except QuotaStopped:
            raise
        except Exception as exc:  # noqa: BLE001
            self._raise_if_fatal_quota(exc, f"creating folder '{name}'")
            raise RuntimeError(f"Could not create folder '{name}': {exc}") from exc
        new_id = created.get("id")
        if effective_key and new_id:
            with self._lock:
                self._state.folder_map[effective_key] = new_id
            self._save_log(force=False)
        return new_id

    def _find_dest_folder(
        self, parent_id: str, source_folder_id: str | None, shortcut_id: str | None
    ) -> str | None:
        key_name = "source_shortcut_id" if shortcut_id else "source_folder_id"
        key_val = shortcut_id or source_folder_id
        if not key_val:
            return None
        esc = key_val.replace("\\", "\\\\").replace("'", "\\'")
        query = (
            f"'{parent_id}' in parents and trashed = false "
            f"and mimeType = 'application/vnd.google-apps.folder' "
            f"and appProperties has {{ key='{key_name}' and value='{esc}' }}"
        )
        try:
            files, _ = self.client.search(query, fields="files(id,name)", page_size=10)
        except Exception as exc:  # noqa: BLE001
            self._raise_if_fatal_quota(exc, "searching for destination folder")
            log_event(self.log, logging.WARNING, "find_folder_failed", error=str(exc))
            return None
        if not files:
            return None
        if len(files) > 1:
            # Multiple destination folders with the same source key: pick the
            # deterministic-first to avoid creating yet another duplicate.
            chosen = sorted(files, key=lambda f: f["id"])[0]
            log_event(
                self.log, logging.WARNING, "duplicate_dest_folders",
                key=key_val, count=len(files), chosen=chosen["id"],
            )
            return chosen["id"]
        return files[0]["id"]

    def _verify_dest_folder(self, folder_id: str, effective_key: str, is_shortcut: bool) -> bool:
        key_name = "source_shortcut_id" if is_shortcut else "source_folder_id"
        try:
            item = self.client.get_metadata(
                folder_id, fields="id,mimeType,trashed,appProperties"
            )
        except Exception as exc:  # noqa: BLE001
            self._raise_if_fatal_quota(exc, "verifying destination folder")
            return False
        df = DriveFile.from_api(item)
        if df.trashed or not df.is_folder:
            return False
        return df.app_properties.get(key_name) == effective_key

    def _resolve_shortcut(self, src: DriveFile) -> DriveFile | None:
        if not src.shortcut_target_id:
            return None
        try:
            meta = self.client.get_metadata(
                src.shortcut_target_id,
                fields="id,name,mimeType,size,md5Checksum,shortcutDetails",
            )
        except Exception as exc:  # noqa: BLE001
            log_event(self.log, logging.WARNING, "shortcut_unresolved", name=src.name, error=str(exc))
            return None
        target = DriveFile.from_api(meta)
        target.name = src.name  # keep the shortcut's display name
        return target

    def _is_descendant_of(self, candidate_id: str, ancestor_id: str, *, max_nodes: int = 200) -> bool:
        if not candidate_id or not ancestor_id:
            return False
        seen: set[str] = set()
        stack = [candidate_id]
        while stack and len(seen) < max_nodes:
            cur = stack.pop()
            if cur == ancestor_id:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            try:
                meta = self.client.get_metadata(cur, fields="id,parents")
            except Exception:
                continue
            for parent in meta.get("parents") or []:
                if parent not in seen:
                    stack.append(parent)
        return False

    # -- listing ------------------------------------------------------------

    def _list_children(
        self, folder_id: str, from_page: int, to_page: int, *, parent_source_id: str
    ) -> list[DriveFile]:
        out: list[DriveFile] = []
        page_token: str | None = None
        page = 0
        lower = from_page if from_page > 0 else 1
        while True:
            try:
                files, page_token = self.client.list_children(
                    folder_id,
                    exclude_substrings=self.config.exclude_substrings,
                    page_token=page_token,
                )
            except Exception as exc:  # noqa: BLE001
                if classify_error(exc) is ErrorClass.FATAL_QUOTA:
                    self._result.stop_reason = f"Quota hit while listing {folder_id}: {exc}"
                    self._stop.set()
                    raise QuotaStopped(self._result.stop_reason) from exc
                reason, message, _ = parse_http_error(exc)
                self._record_failed(
                    DriveFile(id=folder_id, name=f"[folder:{folder_id}]", mime_type="application/vnd.google-apps.folder"),
                    reason=reason or "listingError",
                    message=f"Could not list (page {page + 1}): {message or exc}",
                    parent_source_id=parent_source_id,
                )
                with self._lock:
                    self._result.had_listing_errors = True
                log_event(self.log, logging.ERROR, "list_failed", folder=folder_id, error=str(exc))
                break
            page += 1
            if page >= lower and (to_page == 0 or page <= to_page):
                out.extend(DriveFile.from_api(f) for f in files)
            if not page_token or (to_page > 0 and page >= to_page):
                break
        return out

    def _build_index(self, dest_folder_id: str | None) -> DestinationIndex:
        if not dest_folder_id:
            return DestinationIndex()
        items: list[DriveFile] = []
        page_token: str | None = None
        while True:
            try:
                files, page_token = self.client.list_children(dest_folder_id, page_token=page_token)
            except Exception as exc:  # noqa: BLE001
                if classify_error(exc) is ErrorClass.FATAL_QUOTA:
                    self._result.stop_reason = f"Quota hit while indexing destination: {exc}"
                    self._stop.set()
                    raise QuotaStopped(self._result.stop_reason) from exc
                log_event(self.log, logging.WARNING, "index_failed", folder=dest_folder_id, error=str(exc))
                break
            items.extend(DriveFile.from_api(f) for f in files)
            if not page_token:
                break
        return DestinationIndex.build(items)

    # -- bookkeeping --------------------------------------------------------

    def _mark_copied(self, eff_id: str, size: int) -> None:
        with self._lock:
            self._state.copied_ids.add(eff_id)
            self._state.copied_bytes += size
            self._result.copied_count += 1
            self._result.copied_bytes += size
            self._dirty += 1
            self._copied_session += 1
            session = self._copied_session
        if session % self._progress_every == 0:
            log_event(
                self.log, logging.INFO, "progress",
                copied=session, gb=round(self._state.copied_bytes / GIB, 2),
            )
        self._maybe_flush()

    def _release_reservation(self, size: int) -> None:
        if size:
            with self._lock:
                self._run_bytes -= size

    def _record_existing(self, eff_id: str) -> None:
        with self._lock:
            self._state.copied_ids.add(eff_id)
            self._result.skipped_count += 1
            self._dirty += 1
        self._maybe_flush()

    def _record_failed(self, src: DriveFile, *, reason: str, message: str, **kw) -> None:
        item = FailedItem(
            source_id=src.id, name=src.name, mime_type=src.mime_type,
            reason=reason, error_message=message,
            parent_source_id=kw.get("parent_source_id"),
            shortcut_target_id=kw.get("shortcut_target_id"),
            source_shortcut_id=kw.get("source_shortcut_id"),
            effective_source_id=kw.get("effective_source_id"),
        )
        with self._lock:
            self._state.failed_items.append(item)
            self._result.failed_items.append(item)
        log_event(self.log, logging.WARNING, "item_failed", name=src.name, reason=reason)

    def _reconcile_failed(self, eff_id: str, src: DriveFile) -> None:
        if not self._result.previous_failed_items:
            return
        keys = {k for k in (eff_id, src.id) if k}
        with self._lock:
            self._result.previous_failed_items = [
                f
                for f in self._result.previous_failed_items
                if not (
                    f.effective_source_id in keys
                    or f.source_id in keys
                    or f.source_shortcut_id in keys
                    or f.shortcut_target_id in keys
                )
            ]
            self._state.failed_items = list(self._result.previous_failed_items) + [
                f for f in self._state.failed_items if f not in self._result.previous_failed_items
            ]

    def _maybe_flush(self) -> None:
        if self.config.dry_run:
            return
        with self._lock:
            due = self._dirty >= self._flush_every
        if due:
            self._save_log(force=False)

    def _save_log(self, *, force: bool) -> None:
        if self.config.dry_run or not self._state.dest_root_id:
            return
        with self._lock:
            if not force and self._dirty < self._flush_every:
                return
            self._dirty = 0
        try:
            self.resume.save(self._state)
        except Exception as exc:  # noqa: BLE001
            self._result.log_save_failed = True
            self._result.log_save_error = str(exc)
            log_event(self.log, logging.ERROR, "log_save_failed", error=str(exc))

    def _drain_futures(self) -> None:
        if self._executor is None:
            return
        with self._lock:
            remaining = set(self._futures)
        for fut in as_completed(remaining):
            self._consume_future(fut)
        with self._lock:
            self._futures.clear()

    def _consume_future(self, fut) -> None:
        try:
            fut.result()
        except Exception:  # noqa: BLE001 - worker already recorded failures
            pass

    def _account_id(self) -> str | None:
        try:
            from .auth import fetch_account_identifier

            return fetch_account_identifier(self.client)
        except Exception:
            return None

    def _merge_resume(self, loaded: ResumeState) -> None:
        self._state.copied_ids |= loaded.copied_ids
        for src, dst in loaded.folder_map.items():
            self._state.folder_map.setdefault(src, dst)
        self._state.copied_bytes = max(self._state.copied_bytes, loaded.copied_bytes)
        if loaded.created_at:
            self._state.created_at = loaded.created_at
        self._result.previous_failed_items = list(loaded.failed_items)

    # -- finalize -----------------------------------------------------------

    def _finalize(self, dest_root_id: str | None, completed: bool) -> CopyResult:
        result = self._result
        result.completed = completed
        # result.copied_bytes already reflects bytes copied *this run* (accumulated
        # in _mark_copied); self._state.copied_bytes is the persisted lifetime total.

        if result.fully_ok and dest_root_id:
            try:
                self.resume.cleanup(dest_root_id)
                log_event(self.log, logging.INFO, "logs_cleaned", note="moved to trash")
            except Exception as exc:  # noqa: BLE001
                log_event(self.log, logging.WARNING, "cleanup_failed", error=str(exc))

        all_failed = list(result.previous_failed_items) + list(result.failed_items)
        if all_failed and dest_root_id and not self.config.dry_run:
            try:
                self.resume.export_failed_report(dest_root_id, all_failed)
            except Exception as exc:  # noqa: BLE001
                log_event(self.log, logging.WARNING, "failed_report_error", error=str(exc))

        log_event(
            self.log, logging.INFO, "run_summary",
            copied=result.copied_count, skipped=result.skipped_count,
            failed=len(result.failed_items), prior_failed=len(result.previous_failed_items),
            gb=round(result.copied_bytes / GIB, 2), completed=completed,
            dry_run=self.config.dry_run, stop_reason=result.stop_reason or "",
        )
        return result
