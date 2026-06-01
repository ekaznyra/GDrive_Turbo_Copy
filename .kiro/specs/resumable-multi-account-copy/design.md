# Design: Resumable Multi-Account Copy

## Overview

This design extends the existing single-notebook Drive copier so a job can span multiple Google accounts, each capped at a configurable size (default 750 GB). A durable JSON manifest records the status of every discovered source item. When an account hits its cap, the manifest is the checkpoint; the user re-authenticates with another account and the loop resumes from the manifest until no PENDING or FAILED items remain.

The existing copy mechanics (recursive copy, idempotent skip-existing via `check_if_exists`, transient-error retry through `_execute_with_retry`, name exclusion, pagination) are preserved and wrapped, not rewritten.

## Architecture

The architecture follows the **Layered** breakdown selected in `architecture_selection.md` (read before writing this section). Four components in an acyclic top-down call chain:

```
                 ┌────────────────┐
                 │  Orchestrator  │   account loop, global totals, report
                 └───┬───────┬────┘
        allowed?     │       │  copy(item)        record(result)
         ┌───────────▼─┐   ┌─▼───────────┐   ┌──────────────────┐
         │ SizeGovernor│   │  CopyEngine │──▶│   ProgressStore   │
         │ cap, bytes  │   │ drive_service│   │ manifest + file  │
         └─────────────┘   └─────────────┘   └──────────────────┘
```

Per item the Orchestrator: (1) asks `SizeGovernor.can_copy(size)`, (2) if allowed calls `CopyEngine.copy_item(...)`, (3) records the outcome in `ProgressStore` and adds bytes to `SizeGovernor`. No callbacks, no cycles. `ProgressStore` is the sole owner/writer of the manifest, encapsulating the dominant coupling point behind a narrow interface.

### Why this shape (from selection)
- Cap is enforced **before** each copy (Orchestrator queries SizeGovernor first), so `account_bytes ≤ cap` always holds.
- Manifest is flushed by ProgressStore after every item, making resume crash-safe.
- Account handoff resets only SizeGovernor's accumulator; the manifest is untouched.

## Components and Interfaces

### CopyEngine
Wraps the current `DownloadFromDrive` API behavior.

```python
class CopyEngine:
    def __init__(self, drive_service, excluded_strings): ...
    def list_children(self, folder_id, from_page, to_page) -> list[Item]:
        """Existing get_childs_from_folder logic (pagination + exclusion + retry)."""
    def ensure_folder(self, dest_parent_id, name) -> str:
        """Existing create_folder/check_if_exists logic; idempotent."""
    def copy_item(self, dest_parent_id, item) -> CopyResult:
        """Copy a single non-folder file. Returns CopyResult(status, bytes, error)."""
    def exists(self, dest_parent_id, name) -> str:
        """Existing check_if_exists."""
```
- `copy_item` returns `SKIPPED` (bytes=0) when the file already exists, `COPIED` with byte size on success, `FAILED` with the error string after retries are exhausted. It never raises for a single-file failure (continues the loop), matching REQ-3.4.
- All API calls route through the existing `_execute_with_retry` (REQ-1.2).

### SizeGovernor
```python
class SizeGovernor:
    def __init__(self, cap_gb=750):
        self.cap_bytes = cap_gb * 1024**3
        self.account_bytes = 0
    def can_copy(self) -> bool:
        return self.account_bytes < self.cap_bytes
    def add(self, n_bytes):           # only newly COPIED bytes (REQ-2.4)
        self.account_bytes += n_bytes
    def reached(self) -> bool:
        return self.account_bytes >= self.cap_bytes
    def reset(self):                  # new account handoff (REQ-5.2)
        self.account_bytes = 0
```
- Cap check is pre-copy: the Orchestrator stops the account before starting a file when `not can_copy()` (INV1, REQ-2.3). SKIPPED items never call `add` (REQ-2.4).

### ProgressStore
Owns the manifest and its on-disk file. The manifest is keyed by source file ID so resume is derived, not indexed.

```python
class ProgressStore:
    def __init__(self, path): ...                     # e.g. /content/copy_manifest.json
    def load(self) -> None:                           # rehydrate if file exists (REQ-5.1)
    def register(self, item, dest_parent_id) -> None: # add as PENDING if unknown
    def status_of(self, item_id) -> str
    def mark(self, item_id, status, bytes=0, account=None, error=None) -> None:
        # update + flush to disk immediately (REQ-3, INV5)
    def pending_or_failed(self) -> list                # drives the loop (REQ-6.1)
    def summary(self) -> dict                          # counts + per-account totals (REQ-7)
```

Manifest record shape:
```json
{
  "id": "<source file id>",
  "name": "Movie.mkv",
  "parent_path": "Root/Sub",
  "dest_parent_id": "<dest folder id>",
  "size": 1234567,
  "status": "PENDING|COPIED|SKIPPED|FAILED",
  "account": "user@example.com",
  "error": null
}
```
- Writes are atomic: serialize to a temp file then `os.replace`, so an interrupted write cannot corrupt the manifest (INV5).
- `load()` on startup makes COPIED/SKIPPED items skippable and re-queues FAILED items (REQ-5.1, REQ-5.3).

### Orchestrator
```python
class Orchestrator:
    def __init__(self, engine_factory, store, cap_gb=750): ...
    def discover(self, source_folder_id, dest_root_id, from_page, to_page):
        """Walk source tree, ensure dest folders, register every file in the manifest as PENDING."""
    def run_account_session(self, account_email):
        """Reset governor; iterate pending_or_failed(); enforce cap; copy; record; report."""
    def is_complete(self) -> bool:
        return len(self.store.pending_or_failed()) == 0
```

`engine_factory` builds a `CopyEngine` from a freshly authenticated `drive_service`, so each account session gets its own client (REQ-5.2).

## Data Models

### Item (discovered source entry)
| Field | Type | Notes |
|-------|------|-------|
| `id` | str | Source Drive file/folder ID (manifest key) |
| `name` | str | File or folder name |
| `mimeType` | str | `application/vnd.google-apps.folder` marks a folder |
| `size` | int | Bytes; 0 for folders and native Google Docs |

### ManifestRecord (one per discovered file)
| Field | Type | Notes |
|-------|------|-------|
| `id` | str | Source file ID; primary key |
| `name` | str | Display name (for the report) |
| `parent_path` | str | Human-readable source path, for reporting |
| `dest_parent_id` | str | Destination folder ID the file copies into |
| `size` | int | Bytes |
| `status` | enum | `PENDING` \| `COPIED` \| `SKIPPED` \| `FAILED` |
| `account` | str \| null | Email of the account that copied/skipped it |
| `error` | str \| null | Error message when `status == FAILED` |

### CopyResult (returned by CopyEngine.copy_item)
| Field | Type | Notes |
|-------|------|-------|
| `status` | enum | `COPIED` \| `SKIPPED` \| `FAILED` |
| `bytes` | int | Newly copied bytes; 0 for SKIPPED/FAILED |
| `error` | str \| null | Populated only on FAILED |

### Manifest file (on disk)
```json
{
  "version": 1,
  "source_root_id": "<id>",
  "dest_root_id": "<id>",
  "records": [ { "...ManifestRecord..." } ]
}
```
Persisted atomically (temp file + `os.replace`) after every status change.

### SizeGovernor state
| Field | Type | Notes |
|-------|------|-------|
| `cap_bytes` | int | `cap_gb * 1024**3`; `0` means no cap |
| `account_bytes` | int | Newly-copied bytes for the current account; reset on handoff |

## State Transitions (manifest item)

### Discovery (once, or resumed/extended each session)
1. Orchestrator recursively lists the source tree via CopyEngine, mirroring folders at the destination with `ensure_folder` (idempotent).
2. Every file is registered in ProgressStore as PENDING with its `dest_parent_id` and size.
3. Discovery is itself idempotent: already-registered IDs are left at their current status, so re-running discovery on resume only adds genuinely new files.

> Note: discovery mirrors the destination folder structure first (folders are created, not size-counted), so folder creation is never blocked by the cap. Only file copies consume the cap.

### Per-account session loop
```
governor.reset()
for item in store.pending_or_failed():
    if not governor.can_copy():
        break                      # cap reached → stop this account
    if engine.exists(item.dest_parent_id, item.name):
        store.mark(item.id, SKIPPED, account=email)
        continue
    result = engine.copy_item(item.dest_parent_id, item)
    store.mark(item.id, result.status, result.bytes, email, result.error)
    if result.status == COPIED:
        governor.add(result.bytes)
        if governor.reached():
            break                  # cap hit after this copy → stop
report = store.summary(); print(report); persist(report)
```

### Multi-account control (main cell)
```
store.load()
orch.discover(source_id, dest_id, from_page, to_page)
while not orch.is_complete():
    auth.authenticate_user()                 # user switches account here
    email = current_user_email(service)
    orch.run_account_session(email)
    if orch.is_complete():
        print("All files copied."); break
    print(f"Cap reached. {remaining} items remain — re-run this cell with another account.")
```
Because Colab auth is interactive, the natural handoff is: the cell finishes when the cap is hit, the user re-authenticates with a different account, and re-runs the same cell. The manifest makes this safe and exact (REQ-4, REQ-5). The `while` loop also supports the case where one account can finish a re-auth in-session.

## State Transitions (manifest item)

```
            register
   (none) ──────────▶ PENDING
                        │ copy ok          │ exists           │ error
                        ▼                   ▼                  ▼
                      COPIED              SKIPPED            FAILED
                                                              │ retry on next session
                                                              ▼
                                                       COPIED / SKIPPED
```
Invariant: each item has exactly one status; COPIED/SKIPPED are terminal within a run; FAILED is retried on the next session (INV3, REQ-5.3).

## Error Handling
- **Transient API errors:** handled inside CopyEngine via `_execute_with_retry` (exponential backoff cap 32s). Unchanged from today.
- **Per-file hard failure:** recorded as FAILED with the error message; the loop continues (REQ-3.4). Re-attempted next session.
- **Folder creation failure:** the file(s) under it stay PENDING (their `dest_parent_id` was never created); reported and retried next session.
- **Manifest write failure:** atomic temp-file + replace prevents partial writes; if the disk write itself fails the session aborts loudly rather than continuing with an unpersisted state (protects INV5).
- **Cap default footgun:** unlike the current code where `_limit_size = 0` triggers immediately, the cap defaults to 750 GB; `0` is treated as "no cap" explicitly in `can_copy`/`reached`.

## Storage Location
- Manifest: `/content/copy_manifest.json` by default. To survive Colab runtime resets, the user may point it at a mounted Drive path (e.g. `/content/drive/MyDrive/copy_manifest.json`). Documented as a config value.
- Report: `/content/copy_report.txt`, rewritten at each session end (REQ-7).

## Testing Strategy
Manual/interactive, consistent with the notebook (no test framework today):
1. **Idempotency:** run twice; second run marks everything SKIPPED, copies nothing.
2. **Cap stop:** set a tiny cap (e.g. 0.001 GB); confirm it stops mid-list and the manifest shows the exact COPIED/PENDING split.
3. **Resume:** delete account auth, re-run with another account; confirm COPIED items are skipped and PENDING ones proceed.
4. **Failure path:** point at a file lacking copy permission; confirm FAILED is recorded with an error and the loop continues, then retried next session.
5. **Crash safety:** interrupt mid-run; confirm the manifest reflects only completed items and resume works.

## Notebook Integration
- Keep the two-cell layout: the **Input** cell gains a cap field (default 750) and an optional manifest-path field.
- The **Run** cell defines `CopyEngine`, `SizeGovernor`, `ProgressStore`, `Orchestrator`, and the main multi-account loop. Existing `DownloadFromDrive` logic is refactored into `CopyEngine`/`Orchestrator` rather than deleted, preserving method behavior and `print`-based progress output.
