# Requirements Document

Feature: Resumable Multi-Account Copy

## Glossary

- **Manifest:** The durable JSON file recording the status of every discovered source item; the source of truth for resume.
- **Item:** A single source entry (file or folder) discovered under the source folder.
- **Per-account cap:** The maximum number of newly-copied bytes allowed under one Google account before handoff (default 750 GB).
- **Checkpoint:** The persisted snapshot (the manifest plus the stopping account and its cumulative size) that lets a different account resume exactly where the previous one stopped.
- **Account handoff:** Switching to a different authenticated Google account to continue the job after a cap is reached.
- **Status:** One of PENDING, COPIED, SKIPPED, or FAILED, assigned to each item in the manifest.
- **Transient error:** A retryable Drive API error (429, 500, 502, 503, 504, or a rate/quota 403).

## Introduction

This feature extends the existing "Copy Folder Google Drive to Google Drive" notebook so that very large copy jobs can span multiple Google accounts. Each account copies up to a configurable size cap (default 750 GB). When an account reaches its cap, the tool persists an exact checkpoint of what has been copied, what is still pending, and what failed, then resumes the remaining work under a different account. The loop continues, account by account, until every source file has been copied. A durable log/manifest file is produced so the user always knows where the job stopped and what remains.

The existing copy behavior (recursive copy, idempotent skip-existing, transient-error retry with backoff, name-based exclusion, pagination) must be preserved as the underlying copy engine.

## Requirements

### Requirement 1: Preserve the optimal copy engine

**User Story:** As a user, I want the copy to run as efficiently and safely as it does today, so that resuming across accounts does not regress existing behavior.

#### Acceptance Criteria
1. WHEN a file is copied THEN the system SHALL copy it recursively for folders and skip any file/folder that already exists at the destination (idempotency via `check_if_exists`).
2. WHEN a Drive API call returns a transient error (429, 500, 502, 503, 504, or a rate/quota 403) THEN the system SHALL retry it through `_execute_with_retry` with exponential backoff capped at 32s.
3. WHEN exclusion strings are configured THEN the system SHALL exclude files/folders whose names contain any of those strings.
4. WHEN a page range (`from_page`/`to_page`) is provided THEN the system SHALL honor it as it does today.

### Requirement 2: Per-account size cap

**User Story:** As a user, I want each account to copy only up to a size limit (default 750 GB), so that I stay within per-account quotas.

#### Acceptance Criteria
1. The system SHALL expose a configurable per-account size cap whose default value is 750 (GB).
2. WHILE copying under the current account, the system SHALL accumulate the copied byte total for that account.
3. WHEN the current account's accumulated copied size reaches or would exceed the cap THEN the system SHALL stop copying under that account before starting the next file.
4. WHEN the cap is reached THEN the system SHALL NOT count skipped/already-existing files toward the cap (only newly copied bytes count).

### Requirement 3: Durable progress manifest

**User Story:** As a user, I want a persistent log of what was copied, what is pending, and what failed, so that I can audit progress and the job can resume.

#### Acceptance Criteria
1. The system SHALL persist a manifest record for every discovered source item with a status of one of: PENDING, COPIED, SKIPPED, or FAILED.
2. WHEN an item is copied successfully THEN the system SHALL record it as COPIED with its size and the account that copied it.
3. WHEN an item already exists at the destination THEN the system SHALL record it as SKIPPED.
4. WHEN an item fails after retries THEN the system SHALL record it as FAILED with the error message, and SHALL continue with the next item.
5. The manifest SHALL be written to durable storage (a file) so it survives notebook/runtime restarts.

### Requirement 4: Checkpoint on cap reached

**User Story:** As a user, I want the exact stopping point recorded when an account hits its cap, so that the next account resumes precisely where the previous one stopped.

#### Acceptance Criteria
1. WHEN an account reaches its cap THEN the system SHALL persist a checkpoint identifying which items are COPIED/SKIPPED and which remain PENDING/FAILED.
2. WHEN the checkpoint is written THEN it SHALL record the account identifier that stopped and the cumulative size copied by that account.
3. The checkpoint SHALL be sufficient to resume without re-copying COPIED items.

### Requirement 5: Multi-account handoff and resume

**User Story:** As a user, I want to switch to another account and continue from the checkpoint, so that the overall job exceeds any single account's cap.

#### Acceptance Criteria
1. WHEN copying resumes THEN the system SHALL load the manifest and skip all items already marked COPIED or SKIPPED.
2. WHEN a new account is authenticated THEN the system SHALL reset the per-account accumulated size to zero while preserving the global manifest.
3. WHEN resuming THEN the system SHALL re-attempt items previously marked FAILED.
4. The system SHALL NOT require the user to manually identify the resume point; it SHALL be derived from the manifest.

### Requirement 6: Loop until complete

**User Story:** As a user, I want the process to keep going across as many accounts as needed, so that all files are eventually copied.

#### Acceptance Criteria
1. WHILE PENDING or FAILED items remain in the manifest, the system SHALL continue prompting for/using the next account and copying.
2. WHEN no PENDING or FAILED items remain THEN the system SHALL declare the job complete.
3. IF an account completes the remaining work below its cap THEN the system SHALL finish without requesting another account.

### Requirement 7: Human-readable final report

**User Story:** As a user, I want a readable summary of where the job stopped and what is left, so that I know the outcome.

#### Acceptance Criteria
1. WHEN an account session ends (cap reached or job complete) THEN the system SHALL print and persist a report with: total copied size, per-account size breakdown, count of COPIED/SKIPPED/FAILED/PENDING items.
2. WHEN failures exist THEN the report SHALL list the failed item names and their error messages.
3. WHEN PENDING items remain THEN the report SHALL state how many remain so the user knows another account is needed.
