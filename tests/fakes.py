"""In-memory fakes for unit tests. No Google libraries, no network."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"


class FakeResp:
    def __init__(self, status: int, headers: dict | None = None) -> None:
        self.status = status
        self._headers = {k.lower(): v for k, v in (headers or {}).items()}

    def get(self, key, default=None):
        return self._headers.get(key.lower(), default)


class FakeHttpError(Exception):
    """Mimics googleapiclient.errors.HttpError closely enough for our code."""

    def __init__(self, status: int, reason: str = "", message: str = "", headers=None) -> None:
        super().__init__(message or reason or f"HTTP {status}")
        self.resp = FakeResp(status, headers)
        body = {"error": {"code": status, "message": message or reason, "errors": [{"reason": reason, "message": message or reason}]}}
        self.content = json.dumps(body).encode("utf-8")


def make_error(status: int, reason: str = "", message: str = "", retry_after=None) -> FakeHttpError:
    headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
    return FakeHttpError(status, reason, message, headers=headers)


def folder_link(file_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{file_id}"


class FakeDriveClient:
    """A tiny in-memory Drive. Implements DriveClientProtocol."""

    def __init__(self, *, email: str = "test@example.com") -> None:
        self.nodes: dict[str, dict] = {}
        self._counter = 0
        self.email = email
        # Test hooks:
        self.copy_calls = 0
        self.copy_error_on_call: int | None = None
        self.copy_error: Exception | None = None
        self.create_calls = 0
        self.create_error_on_call: int | None = None
        self.create_error: Exception | None = None

    # -- builders (test helpers) -------------------------------------------

    def _new_id(self, prefix: str = "id") -> str:
        self._counter += 1
        # Long enough to be parsed by extract_folder_id's folders/<id> pattern.
        return f"{prefix}{self._counter:010d}"

    def add_folder(self, name: str, parent: str | None = None, *, app_properties=None, id=None) -> str:
        fid = id or self._new_id("fld")
        self.nodes[fid] = {
            "id": fid, "name": name, "mimeType": FOLDER_MIME,
            "parents": [parent] if parent else [], "appProperties": dict(app_properties or {}),
            "trashed": False,
        }
        return fid

    def add_file(self, name, parent, *, size=None, md5=None, mime="application/octet-stream", app_properties=None, id=None) -> str:
        fid = id or self._new_id("file")
        self.nodes[fid] = {
            "id": fid, "name": name, "mimeType": mime,
            "size": (str(size) if size is not None else None), "md5Checksum": md5,
            "parents": [parent] if parent else [], "appProperties": dict(app_properties or {}),
            "trashed": False,
        }
        return fid

    def add_shortcut(self, name, parent, target_id, *, id=None) -> str:
        sid = id or self._new_id("sc")
        self.nodes[sid] = {
            "id": sid, "name": name, "mimeType": SHORTCUT_MIME,
            "parents": [parent] if parent else [], "appProperties": {},
            "shortcutDetails": {"targetId": target_id}, "trashed": False,
        }
        return sid

    # -- protocol ----------------------------------------------------------

    def list_children(self, folder_id, *, exclude_substrings: Iterable[str] = (), order_by=None, page_token=None):
        excludes = [s for s in exclude_substrings if s]
        out = []
        for node in self.nodes.values():
            if node.get("trashed"):
                continue
            if folder_id not in (node.get("parents") or []):
                continue
            if any(sub in node.get("name", "") for sub in excludes):
                continue
            out.append(dict(node))
        out.sort(key=lambda n: (n.get("name", ""), n["id"]))
        return out, None

    def get_metadata(self, file_id, *, fields=None):
        if file_id == "root":
            return {"id": "root"}
        node = self.nodes.get(file_id)
        if node is None or node.get("trashed"):
            raise make_error(404, "notFound", f"File not found: {file_id}")
        return dict(node)

    def copy_file(self, file_id, body):
        self.copy_calls += 1
        if self.copy_error_on_call is not None and self.copy_calls >= self.copy_error_on_call:
            raise self.copy_error or make_error(403, "dailyLimitExceeded", "Daily quota exceeded")
        src = self.nodes[file_id]
        new_id = self._new_id("copy")
        self.nodes[new_id] = {
            "id": new_id, "name": body["name"], "mimeType": src["mimeType"],
            "size": src.get("size"), "md5Checksum": src.get("md5Checksum"),
            "parents": list(body.get("parents") or []),
            "appProperties": dict(body.get("appProperties") or {}), "trashed": False,
        }
        return {"id": new_id}

    def create_folder(self, name, parent_id, *, app_properties=None):
        self.create_calls += 1
        if self.create_error_on_call is not None and self.create_calls >= self.create_error_on_call:
            raise self.create_error or make_error(403, "dailyLimitExceeded", "Daily quota exceeded")
        fid = self.add_folder(name, parent_id, app_properties=app_properties)
        return {"id": fid}

    def search(self, query, *, fields=None, page_size=100, page_token=None):
        parent = None
        m = re.search(r"'([^']+)' in parents", query)
        if m:
            parent = m.group(1)
        want_folder = "mimeType = '" + FOLDER_MIME + "'" in query
        ap = re.search(r"appProperties has \{ key='([^']+)' and value='([^']*)' \}", query)
        ap_key, ap_val = (ap.group(1), ap.group(2)) if ap else (None, None)
        out = []
        for node in self.nodes.values():
            if node.get("trashed"):
                continue
            if parent and parent not in (node.get("parents") or []):
                continue
            if want_folder and node.get("mimeType") != FOLDER_MIME:
                continue
            if ap_key and (node.get("appProperties") or {}).get(ap_key) != ap_val:
                continue
            out.append(dict(node))
        return out, None

    def get_media(self, file_id) -> bytes:
        node = self.nodes.get(file_id)
        if node is None:
            raise make_error(404, "notFound", f"File not found: {file_id}")
        return node.get("_content", b"")

    def create_json_file(self, name, parent_id, data, *, app_properties=None):
        fid = self._new_id("json")
        self.nodes[fid] = {
            "id": fid, "name": name, "mimeType": "application/json",
            "parents": [parent_id], "appProperties": dict(app_properties or {}),
            "_content": data, "trashed": False,
        }
        return {"id": fid}

    def update_file_content(self, file_id, data):
        self.nodes[file_id]["_content"] = data
        return {"id": file_id}

    def trash_file(self, file_id) -> None:
        if file_id in self.nodes:
            self.nodes[file_id]["trashed"] = True

    def about_user(self) -> dict:
        return {"user": {"emailAddress": self.email}}
