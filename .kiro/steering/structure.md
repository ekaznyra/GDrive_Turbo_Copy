# Project Structure

## Layout
```
.
├── Copy_Folder_Google_Drive_to_Google_Drive.ipynb   # The entire application
├── README.md                                         # Usage guide (Vietnamese)
└── .kiro/steering/                                   # AI assistant guidance
```

This is a single-notebook project. Essentially all logic lives in the notebook; there are no separate Python modules, packages, or build artifacts.

## Notebook Organization
The notebook contains two code cells:
1. **Input cell** (`#@title Input`) — defines `ipywidgets` text inputs and `display()`s them. Holds all user-configurable values.
2. **Run cell** (`#@title Run`) — defines the core classes/helpers and the main execution block that reads widget values and starts the copy.

When editing, keep these two cells separate: widget definitions in Input, logic and execution in Run.

## Code Organization (within the Run cell)
- **Module-level helpers:** `_escape()`, `_is_transient()`, and the `SizeLimitExceeded` exception.
- **`DownloadFromDrive` class** — the core engine. Key methods:
  - `get_user_credential()` — authenticates and builds the Drive service.
  - `_execute_with_retry()` — central wrapper for all Drive API calls.
  - `get_childs_from_folder()` — lists folder children with pagination, exclusion filtering.
  - `copy_file()` — copies one file, or recurses into subfolders.
  - `copy_multiple_files()` — iterates and copies a list of files.
  - `create_folder()` / `check_if_exists()` — destination folder creation and idempotency checks.
  - `extract_folder_id_from_url()` — pulls a Drive folder ID from a share link.
  - `copy_drive_to_drive()` — top-level orchestration entry point.
- **Main block** — instantiates `DownloadFromDrive`, sets `_limit_size` and `excluded_strings`, then calls `copy_drive_to_drive(...)`.

## State Conventions
- Instance state on `DownloadFromDrive`: `_total_size` (MB, accumulated), `_limit_size` (GB, configured), `excluded_strings` (list).
- The leading-underscore attributes are treated as internal but are set directly from the main block (e.g. `downloader._limit_size = ...`); follow this existing pattern rather than introducing setters.

## Editing Guidance
- Keep the project self-contained in the single notebook unless explicitly asked to refactor into modules.
- Route any new Drive API call through `_execute_with_retry()`.
- Preserve method naming and the recursive copy flow when extending functionality.
