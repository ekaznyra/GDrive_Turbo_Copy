"""Parsing of Google Drive folder/file links into IDs."""

from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"folders/([A-Za-z0-9_-]{10,})"),
    re.compile(r"id=([A-Za-z0-9_-]{10,})"),
    re.compile(r"/d/([A-Za-z0-9_-]{10,})"),
]
_BARE_ID = re.compile(r"([A-Za-z0-9_-]{25,})")


def extract_folder_id(url: str | None) -> str | None:
    """Extract a Drive folder/file ID from a share link, ``open?id=`` URL,
    ``/d/`` URL, or a bare ID. Returns ``None`` when nothing plausible is found.
    """
    if not url:
        return None
    url = url.strip()
    for pattern in _PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    match = _BARE_ID.search(url)
    return match.group(0) if match else None
