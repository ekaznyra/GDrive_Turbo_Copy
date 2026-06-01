# Tech Stack

## Runtime & Environment
- **Language:** Python 3
- **Primary environment:** Google Colab (IPython Notebook). The code depends on Colab-only features and is not designed to run standalone without modification.
- **Distribution:** Single `.ipynb` notebook, also openable directly via the "Open In Colab" badge.

## Key Libraries
- `google.colab.auth` — user authentication (`auth.authenticate_user()`). Colab-only.
- `googleapiclient.discovery.build` — builds the Drive API v3 client (`build('drive', 'v3')`).
- `ipywidgets` — text input widgets for the notebook UI.
- Standard library: `time` (timing, backoff delays), `re` (extracting folder IDs from URLs).

All of these are preinstalled in Colab; **no `pip install` step is required**.

## Google Drive API Usage
- Uses Drive API **v3**.
- All file operations pass `supportsAllDrives=True`; listing calls also pass `includeItemsFromAllDrives=True` to support shared drives.
- Folder IDs are extracted from share URLs via the regex `[-\w]{25,}`.
- Drive query strings must escape backslashes and single quotes — use the existing `_escape()` helper for any value interpolated into a query.

## Conventions & Patterns
- **Retry logic:** Wrap every Drive API call in `_execute_with_retry()`. Transient errors (429, 500, 502, 503, 504, and rate/quota 403s) are retried with exponential backoff capped at 32s. Use `_is_transient()` to classify errors; do not add bare retries elsewhere.
- **Size limit:** Track copied size in MB on `self._total_size`; the limit is in GB on `self._limit_size`. Exceeding the limit raises `SizeLimitExceeded`, which is caught at the top level to end cleanly.
- **Custom exceptions:** Use `SizeLimitExceeded` for the size-limit stop condition; let it propagate rather than swallowing it in `copy_file`.
- **Idempotency:** Always call `check_if_exists()` before copying a file or creating a folder.
- **Logging:** Progress and errors are reported via `print()` (no logging framework). Keep this style for user visibility in Colab output.

## Running
1. Open the notebook in Google Colab.
2. Run the **Input** cell and fill in the widget fields.
3. Run the **Run** cell, authenticate when prompted, and the copy executes.

There is no build, compile, or automated test step — the notebook is run cell-by-cell interactively.
