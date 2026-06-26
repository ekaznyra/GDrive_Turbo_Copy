# ⚡ GDrive_Turbo_Copy

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/ekaznyra/GDrive_Turbo_Copy/blob/main/GDrive_Turbo_Copy.ipynb)
[![CI](https://github.com/ekaznyra/GDrive_Turbo_Copy/actions/workflows/ci.yml/badge.svg)](https://github.com/ekaznyra/GDrive_Turbo_Copy/actions/workflows/ci.yml)

> Sao chép thư mục Google Drive **siêu tốc** (server-side), hỗ trợ **đa luồng**, **resume** khi bị ngắt, kiểm tra trùng và **xác minh sau khi copy**.
> Fast, **server-side** Google Drive folder-to-folder copier with multi-threading, resume, duplicate detection and post-copy verification.

**⚠️ Legal / pháp lý:** Chỉ sao chép dữ liệu bạn **có quyền hợp pháp** truy cập. Công cụ **không** sao chép *permissions, comments, revision history*. Không có cơ chế vượt quota hay lạm dụng nhiều tài khoản.

---

## What it does

- **Server-side copy** via the Drive API (`files.copy`) — Google copies on its servers, so **no download/upload bandwidth** is consumed.
- **Shared Drive support** (`supportsAllDrives` / `includeItemsFromAllDrives`).
- **Recursive folder tree** rebuild (folders can't be "copied" by the API, so the tree is recreated and files copied into it).
- **Resume after interruption** via a schema-versioned, integrity-hashed JSON log stored in the destination.
- **Idempotency** through `appProperties` (`source_file_id`, `source_md5`, `copied_by_tool`) plus checksum / name+size duplicate detection.
- **Post-copy verification**: every copy's metadata is fetched and checked (appProperties, name, MIME, and md5/size when available) before it's marked done.
- **Adaptive concurrency**: workers back off automatically on rate limits and recover after stable success; list / copy / create-folder / log-update operations are throttled separately.
- **Proactive rate pacing** (token bucket): a steady client-side floor (default ~10 req/s) so most `rateLimitExceeded`/429s never happen — not just reactive backoff.
- **Metadata fidelity**: preserves `modifiedTime` and `description` on each copy (set in the copy body, no extra round-trip); `createdTime` is sent best-effort (Drive often assigns a fresh creation time on copy).
- **Rate-limit circuit breaker**: after sustained per-copy throttling, stops gracefully (likely the daily/server-side-copy cap) instead of hammering for 24h.
- **Safe daily-quota guard**: stops *before* the configured byte budget (default **730 GB**), reserving bytes under a lock so concurrent workers can't overshoot.
- **Preflight**: fails fast if the destination folder isn't writable, before building a partial tree.
- **Dry-run** preview and a **`failed_report.json`** for anything that couldn't be copied.

> Inspired by best practices from open-source Drive tooling (rclone's pacer/metadata handling, the gdrive-copy resume pattern, official Drive API guidance). It deliberately does **not** implement multi-account/service-account rotation, `quotaUser` tricks, or any other quota-evasion mechanism.

## Architecture

The engine is split so the core logic imports **no Google libraries** and is fully unit-testable with a mocked client:

| Module | Responsibility |
|---|---|
| [`models.py`](src/gdrive_turbo_copy/models.py) | Dataclasses, enums, constants, `DriveClientProtocol` |
| [`retry.py`](src/gdrive_turbo_copy/retry.py) | Error classification, full-jitter backoff, `Retry-After`, structured retry events |
| [`concurrency.py`](src/gdrive_turbo_copy/concurrency.py) | Adaptive, per-operation concurrency control |
| [`resume_store.py`](src/gdrive_turbo_copy/resume_store.py) | Atomic, integrity-hashed, schema-migrating resume log |
| [`drive_client.py`](src/gdrive_turbo_copy/drive_client.py) | Real Drive API client (the only place Google libs are imported, besides auth) |
| [`auth.py`](src/gdrive_turbo_copy/auth.py) | Colab / ADC / service-account auth (lazy imports, no secrets in code) |
| [`copier.py`](src/gdrive_turbo_copy/copier.py) | The copy engine + pure duplicate-detection (`DestinationIndex`) |
| [`cli.py`](src/gdrive_turbo_copy/cli.py) | Command-line interface |

## Install

```bash
# From the repo
pip install "git+https://github.com/ekaznyra/GDrive_Turbo_Copy.git"

# For development (editable + tests + linter)
git clone https://github.com/ekaznyra/GDrive_Turbo_Copy.git
cd GDrive_Turbo_Copy
pip install -e ".[dev]"
```

## Colab usage

1. Open the notebook via the **Open In Colab** badge above.
2. Run the **Install** cell, then the **Input** cell, and fill in:
   - **Drive của bạn (đích)** — destination folder link (in *your* Drive).
   - **Drive nguồn** — source folder link.
   - Optional: pages, max size (GB), exclude fragments, workers, duplicate-check mode, dry-run.
3. Run the **Run** cell and authorize Drive access when prompted.

The notebook is a **thin wrapper** that imports this package, so the engine and the CLI share identical behavior.

## CLI usage

```bash
gdrive-turbo-copy \
  --source "https://drive.google.com/drive/folders/SOURCE_ID" \
  --dest   "https://drive.google.com/drive/folders/DEST_ID" \
  --workers 4 \
  --verify-mode checksum \
  --max-size-gb 730 \
  --dry-run
```

Outside Colab, authentication uses Application Default Credentials or a service
account. Pass `--no-colab` and either run `gcloud auth application-default login`
or set `GDRIVE_SERVICE_ACCOUNT_FILE=/path/key.json`.

Key flags:

| Flag | Default | Meaning |
|---|---|---|
| `--workers` | `4` | Parallel workers (1–16; >8 warns). |
| `--max-size-gb` | `730` | Stop before copying more than this; `0` = unlimited. |
| `--max-tps` | `10` | Proactive client-side rate cap (req/s); `0` disables pacing. |
| `--verify-mode` | `checksum` | `checksum` (strict md5), `name_size`, or `name_only`. |
| `--exclude` | – | Comma-separated name fragments to skip (`tmp,.log`). |
| `--from-page` / `--to-page` | `0` | Paginate the **root** folder's direct children (`0` = no limit). |
| `--allow-name-only` | off | Permit unsafe name-only matching. |
| `--no-preserve-metadata` | off | Don't copy `modifiedTime`/`createdTime`/`description`. |
| `--ignore-default-visibility` | off | Bypass a domain default-sharing policy on the copies. |
| `--keep-revision-forever` | off | Pin the copy's head revision (binary files; uses storage). |
| `--fast-list` | off | Batch sibling folders into one list call — faster on wide trees (opt-in). |
| `--dry-run` | off | Preview only. |

## Resume & idempotency

Progress is saved to `.gdrive_copy_resume.<account>.json` in the destination root. It stores the schema version, account, source/destination root IDs, run ID, copied file IDs, folder map, copied bytes, failed items, `updated_at`, and an **integrity hash** (SHA-256). On load the hash is verified; a corrupted log is rejected rather than silently skipping files. Logs from multiple accounts in the same destination are merged.

Every copied file carries `appProperties` (`source_file_id`, `source_md5`, `copied_by_tool`) and every created folder carries `source_folder_id` — so re-runs detect and skip already-copied items even if the log is gone. Logs are only cleaned (moved to **trash**, never permanently deleted) when a run finishes fully successfully.

## Running tests

Tests mock all Drive calls — **no real credentials are needed**.

```bash
pip install -e ".[dev]"
pytest -q              # run the suite
ruff check src tests   # lint
```

## Limitations

- **Not copied:** sharing permissions, comments, revision history (by design).
- Google enforces a **~750 GB/day** upload+copy quota per account; server-side `files.copy` also has its own (lower) effective ceiling and a per-second rate. The byte guard (default 730 GB) plus the rate-limit circuit breaker stop gracefully on either signal, and the run resumes later.
- Pagination (`from-page`/`to-page`) applies only to the **root** folder's direct children; subfolders are always traversed in full.
- No quota bypass, multi-account abuse, or limit-evasion is implemented or supported.

### Deferred / future work

These were evaluated against open-source tooling and intentionally left out for now (correctness/effort trade-offs); contributions welcome:

- **Mid-folder resume cursor**: persist each folder's `pageToken` so a crash inside a huge folder resumes mid-page instead of re-listing it.
- **Shared-drive `corpora=drive` scoping** and **gzip transport** tuning (efficiency only).

> **Fast-list is now implemented** (`--fast-list`, opt-in): it ORs up to 50 sibling folders into one `files.list` to cut enumeration time on wide trees. It includes the mandatory safety net — if a multi-parent batch returns empty or a parent yields no rows, those folders are re-listed individually, so a folder is **never silently skipped**.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Stops with a "quota" message | Daily copy/upload limit reached. Re-run after ~24h; the resume log continues automatically. |
| `Destination equals or is inside the source tree` | Choose a destination **outside** the source folder. |
| Many `cannotAccessShortcutTarget` failures | Shortcuts point to files you can't access; see `failed_report.json`. |
| Re-running re-copies files | Ensure the destination still contains the prior copies (detected via `appProperties`/checksum) and that the resume log wasn't deleted. |
| `Resume log integrity hash mismatch` | A log was corrupted; the tool refuses it to avoid skipping files. Trash the bad `.gdrive_copy_resume.*.json` and re-run. |
| Rate-limit warnings in logs | Normal under load — workers auto-throttle. Lower `--workers` if persistent. |

## License

[MIT](LICENSE)
