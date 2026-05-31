# Usage Guide

This guide covers how to use each tool in the Google Drive Transfer notebook.

## Overview

The notebook contains two main tools:

1. **Permission Manager** — Share or unshare files/folders with another user
2. **Shared with Me Copier** — Copy items from "Shared with me" to your Drive

---

## Tool 1: Permission Manager

Use this tool to **share or unshare** files and folders in your Google Drive (including Shared Drives) with another user.

### Parameters

| Parameter           | Description                                         | Default              |
|---------------------|-----------------------------------------------------|----------------------|
| `action`            | `Share` or `Unshare`                                | `Share`              |
| `shared_drive_name` | Name of a Shared Drive (leave blank for My Drive)   | *(empty)*            |
| `source_path`       | Path to the file or folder                          | *(empty)*            |
| `destination_email` | Email of the user to share with                     | *(empty)*            |
| `sharing_scope`     | `Files and Folders`, `Files Only`, `Folders Only`   | `Files and Folders`  |
| `sharing_role`      | `writer`, `commenter`, `reader` (Share only)        | `writer`             |
| `send_notification` | Send email notification to recipient                | `False`              |

### Example: Share a Folder

1. Set `action` = `Share`
2. Leave `shared_drive_name` blank (or enter a Shared Drive name)
3. Set `source_path` = `/My Project Folder`
4. Set `destination_email` = `colleague@example.com`
5. Set `sharing_role` = `writer`
6. Run the cell

### Example: Unshare Files in a Folder

1. Set `action` = `Unshare`
2. Set `source_path` = `/Confidential Reports`
3. Set `destination_email` = `former-employee@example.com`
4. Set `sharing_scope` = `Files Only`
5. Run the cell

### How It Works

1. **Path Resolution** — The tool navigates the drive folder tree to find the target item by path
2. **Item Listing** — If the target is a folder, it lists all contents based on the selected scope
3. **Batch Execution** — Permissions are added or removed in batch for efficiency

---

## Tool 2: Shared with Me Copier

Use this tool to **copy files and folders** from your "Shared with me" list into your own Google Drive.

### Parameters

| Parameter                       | Description                                                     | Default              |
|---------------------------------|-----------------------------------------------------------------|----------------------|
| `specific_item_name`            | Name of a specific item to copy (leave blank for all)           | *(empty)*            |
| `destination_folder_name`       | Target folder in My Drive (leave blank for root)                | *(empty)*            |
| `copy_scope`                    | `Files and Folders`, `Files Only`, `Folders Only`               | `Files and Folders`  |
| `skip_existing_items`           | Skip items that already exist in the destination                | `True`               |
| `max_retries_per_chunk`         | Maximum retry attempts per batch chunk                          | `5`                  |
| `initial_retry_delay_seconds`   | Initial delay (in seconds) before retrying a failed batch       | `15`                 |

### Example: Copy a Specific Shared Folder

1. Set `specific_item_name` = `Team Project Files`
2. Set `destination_folder_name` = `Backups`
3. Leave other settings as default
4. Run the cell

### Example: Copy All Shared Files

1. Leave `specific_item_name` blank
2. Set `destination_folder_name` = `All Shared Files Backup`
3. Set `copy_scope` = `Files Only`
4. Run the cell

### How It Works

1. **Authentication** — Connects to Google Drive with a long timeout for large operations
2. **Destination Setup** — Finds or validates the destination folder in your Drive
3. **Source Listing** — Lists items in "Shared with me" (or finds a specific item)
4. **Duplicate Check** — Optionally checks for existing items to avoid re-copying
5. **Batch Copy** — Copies files in chunks with automatic retry and exponential backoff
6. **Recursive Processing** — For folders, creates the folder structure and recursively copies all contents

### Performance Notes

- **Batch Size**: The tool processes up to 999 items per batch (Google API limit)
- **Retry Logic**: Failed batches are retried with exponential backoff (delay doubles each attempt)
- **Timeout**: Network operations have a 10-minute timeout for large files
- **Progress Bars**: Real-time progress tracking via `tqdm`

---

## Tips

- **Run incrementally**: Use `skip_existing_items = True` so you can re-run the notebook to resume an interrupted transfer.
- **Start small**: Test with a single folder before processing your entire "Shared with me" list.
- **Check quotas**: Google Drive API has daily usage limits. If you hit quota errors, wait and re-run.
- **Shared Drives**: The Permission Manager lists available Shared Drives at the top of the cell output — copy the exact name from there.
