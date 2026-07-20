"""GDrive Turbo Copy: fast, resumable, server-side Google Drive folder copier.

The package is split so that the *core* logic (models, retry classification,
duplicate detection, resume store, copier engine) imports **no** Google
libraries. Google-specific code lives only in :mod:`gdrive_turbo_copy.drive_client`
and :mod:`gdrive_turbo_copy.auth`. This keeps the engine unit-testable with
mocked clients and no real Drive credentials.
"""

from __future__ import annotations

from .copier import Copier
from .models import (
    CopyConfig,
    CopyResult,
    DriveFile,
    FailedItem,
    OperationType,
    VerifyMode,
)
from .resume_store import ResumeState, ResumeStore

__version__ = "2.1.0"

__all__ = [
    "CopyConfig",
    "CopyResult",
    "DriveFile",
    "FailedItem",
    "OperationType",
    "VerifyMode",
    "Copier",
    "ResumeState",
    "ResumeStore",
    "__version__",
]
