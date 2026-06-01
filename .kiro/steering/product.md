# Product

**Copy Folder Google Drive to Google Drive - 1TouchPro**

A Google Colab notebook tool that copies the entire contents of one Google Drive folder into another folder, either within the same account or across different Google Drive accounts.

## Core Capabilities
- Recursively copies files and subfolders from a source Drive folder to a destination Drive folder.
- Supports copying between different Google accounts (source can be a shared drive/folder).
- Skips files and folders that already exist at the destination (idempotent re-runs).
- Filters out files/folders whose names contain user-specified excluded strings.
- Supports page-range selection (`from_page`/`to_page`) to copy a subset of large folder listings.
- Enforces a configurable maximum total copy size (in GB) and stops cleanly when exceeded.
- Retries transient Drive API errors (rate limits, 5xx) with exponential backoff.

## Target User
End users (often non-developers) running the notebook in Google Colab. The UI is provided via `ipywidgets` text inputs and the interface labels are primarily in Vietnamese.

## Key User Inputs
- **Your drive / dest:** destination folder link.
- **Shared drive / source:** source folder link.
- **Từ trang / Đến trang:** page range (0 = no pagination limit).
- **Tổng dung lượng tối đa (GB):** max total copy size.
- **Bỏ file, folder có chứa nội dung:** comma-separated exclusion strings.

## Conventions
- User-facing labels and messages may be in Vietnamese; keep them consistent with existing text.
- Preserve idempotent behavior: never duplicate files/folders that already exist at the destination.
