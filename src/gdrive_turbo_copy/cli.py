"""Command-line interface for gdrive-turbo-copy.

Example::

    gdrive-turbo-copy \\
        --source "https://drive.google.com/drive/folders/SOURCE_ID" \\
        --dest   "https://drive.google.com/drive/folders/DEST_ID" \\
        --workers 4 --verify-mode checksum --dry-run
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .logging_utils import setup_logging
from .models import (
    DEFAULT_MAX_COPY_SIZE_GB,
    DEFAULT_MAX_TPS,
    DEFAULT_WORKERS,
    GIB,
    CopyConfig,
    VerifyMode,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gdrive-turbo-copy",
        description="Fast, resumable, server-side Google Drive folder-to-folder copier.",
    )
    parser.add_argument("--source", required=True, help="Source Drive folder link or ID.")
    parser.add_argument("--dest", required=True, help="Destination Drive folder link or ID.")
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS, help="Parallel workers (1-16, default 4)."
    )
    parser.add_argument(
        "--max-size-gb", type=float, default=DEFAULT_MAX_COPY_SIZE_GB,
        help="Stop before copying more than this many GB (default 730; 0 = unlimited).",
    )
    parser.add_argument(
        "--verify-mode", choices=[m.value for m in VerifyMode], default=VerifyMode.CHECKSUM.value,
        help="Duplicate detection mode (default checksum).",
    )
    parser.add_argument(
        "--exclude", default="", help="Comma-separated name fragments to skip (e.g. 'tmp,.log')."
    )
    parser.add_argument("--from-page", type=int, default=0, help="Root pagination start (0 = no limit).")
    parser.add_argument("--to-page", type=int, default=0, help="Root pagination end (0 = no limit).")
    parser.add_argument(
        "--allow-name-only", action="store_true",
        help="Permit unsafe name-only duplicate matching (not recommended).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview only; create/copy nothing.")
    parser.add_argument(
        "--max-tps", type=float, default=DEFAULT_MAX_TPS,
        help=f"Proactive client-side rate cap, requests/sec (default {DEFAULT_MAX_TPS:g}; 0 = off).",
    )
    parser.add_argument(
        "--no-preserve-metadata", action="store_true",
        help="Do not preserve modifiedTime/createdTime/description on copies.",
    )
    parser.add_argument(
        "--ignore-default-visibility", action="store_true",
        help="Bypass any domain default-sharing policy on the new copies.",
    )
    parser.add_argument(
        "--keep-revision-forever", action="store_true",
        help="Pin the copy's head revision against auto-pruning (binary files; uses storage).",
    )
    parser.add_argument(
        "--fast-list", action="store_true",
        help="Batch sibling folders into one list call (faster on wide trees; opt-in).",
    )
    parser.add_argument(
        "--skip-completed-folders", action="store_true",
        help="On resume, skip re-listing subtrees copied in full last run (faster; "
             "won't pick up newly-added files in those subtrees; default-path only).",
    )
    parser.add_argument(
        "--no-colab", action="store_true",
        help="Skip Colab auth; use ADC / service-account credentials.",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level (default INFO).")
    parser.add_argument("--json-logs", action="store_true", help="Emit JSON log lines.")
    return parser


def config_from_args(args: argparse.Namespace) -> CopyConfig:
    excludes = [s.strip() for s in (args.exclude or "").split(",") if s.strip()]
    return CopyConfig(
        source_link=args.source,
        dest_link=args.dest,
        workers=args.workers,
        max_copy_size_gb=args.max_size_gb,
        verify_mode=VerifyMode(args.verify_mode),
        exclude_substrings=excludes,
        dry_run=args.dry_run,
        from_page=args.from_page,
        to_page=args.to_page,
        allow_name_only=args.allow_name_only,
        max_tps=args.max_tps,
        preserve_metadata=not args.no_preserve_metadata,
        ignore_default_visibility=args.ignore_default_visibility,
        keep_revision_forever=args.keep_revision_forever,
        fast_list=args.fast_list,
        skip_completed_folders=args.skip_completed_folders,
    )


def _print_summary(result) -> None:
    line = "=" * 56
    print("\n" + line)
    print("  GDRIVE TURBO COPY — RESULT")
    print(line)
    if result.dry_run:
        print(
            f"  [DRY-RUN] would copy {result.would_copy_count} files "
            f"(~{result.would_copy_bytes / GIB:.2f} GB). Nothing was created."
        )
    else:
        print(f"  Copied:   {result.copied_count} files")
        print(f"  Skipped:  {result.skipped_count} (already present / copied)")
        if result.skipped_complete_folders:
            print(f"  Skipped folders: {result.skipped_complete_folders} (complete subtrees, not re-listed)")
        print(f"  Failed:   {len(result.failed_items)} (this run)")
        if result.previous_failed_items:
            print(f"  Prior failures unresolved: {len(result.previous_failed_items)}")
        print(f"  Volume:   {result.copied_bytes / GIB:.2f} GB")
    if result.stop_reason:
        print(f"  Stop reason: {result.stop_reason}")
    if result.log_save_failed:
        print(f"  WARNING: resume log save failed: {result.log_save_error}")
    print(line)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logger = setup_logging(args.log_level, json_format=args.json_logs)

    config = config_from_args(args)
    errors = config.validate()
    if errors:
        for err in errors:
            logger.error("invalid input: %s", err)
        return 2

    # Heavy/Google imports happen here so --help and validation stay dependency-free.
    import signal

    from .auth import make_service_factory
    from .concurrency import AdaptiveConcurrencyController
    from .copier import Copier
    from .drive_client import DriveClient
    from .pacer import make_pacer

    try:
        factory = make_service_factory(prefer_colab=not args.no_colab)
    except Exception as exc:
        logger.error("authentication failed: %s", exc)
        return 3

    controller = AdaptiveConcurrencyController(copy_workers=max(1, min(args.workers, 16)))
    pacer = make_pacer(config.max_tps)
    client = DriveClient(factory, controller=controller, pacer=pacer, logger=logger)
    copier = Copier(client, config, logger=logger)

    # Flush progress and stop gracefully on Ctrl-C / SIGTERM instead of dying
    # mid-write and losing un-logged progress.
    def _on_signal(signum, _frame):
        logger.warning("received signal %s; stopping gracefully and saving progress...", signum)
        copier.request_stop(f"Interrupted by signal {signum}; progress saved to the resume log.")

    for _sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
        if _sig is not None:
            try:
                signal.signal(_sig, _on_signal)
            except (ValueError, OSError):  # not in main thread / unsupported
                pass

    result = copier.run()
    _print_summary(result)

    if result.stop_reason and result.copied_count == 0 and not result.dry_run:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
