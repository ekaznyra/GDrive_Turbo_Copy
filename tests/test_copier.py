from fakes import FakeDriveClient, folder_link
from gdrive_turbo_copy.copier import Copier
from gdrive_turbo_copy.models import TOOL_TAG, CopyConfig, VerifyMode


def _tree():
    c = FakeDriveClient()
    src_root = c.add_folder("SourceRoot")
    dst_parent = c.add_folder("DestParent")
    c.add_file("a.txt", src_root, size=3, md5="ma", mime="text/plain")
    c.add_file("b.txt", src_root, size=4, md5="mb", mime="text/plain")
    sub = c.add_folder("sub", src_root)
    c.add_file("c.txt", sub, size=5, md5="mc", mime="text/plain")
    return c, src_root, dst_parent


def _cfg(src_id, dst_id, **kw):
    return CopyConfig(source_link=folder_link(src_id), dest_link=folder_link(dst_id), workers=1, verify_mode=VerifyMode.CHECKSUM, **kw)


def test_basic_recursive_copy():
    c, src_root, dst_parent = _tree()
    result = Copier(c, _cfg(src_root, dst_parent)).run()
    assert result.completed
    assert result.copied_count == 3
    assert result.skipped_count == 0
    assert not result.failed_items
    # Destination root folder created with source_folder_id appProperties.
    roots = [n for n in c.nodes.values() if (n.get("appProperties") or {}).get("source_folder_id") == src_root]
    assert len(roots) == 1
    # Every copied file carries the tool tag + source id.
    copied_files = [n for n in c.nodes.values() if (n.get("appProperties") or {}).get("copied_by_tool") == TOOL_TAG and n["mimeType"] == "text/plain"]
    assert len(copied_files) == 3


def test_resume_is_idempotent():
    c, src_root, dst_parent = _tree()
    first = Copier(c, _cfg(src_root, dst_parent)).run()
    assert first.copied_count == 3
    # Second run over the same destination copies nothing.
    second = Copier(c, _cfg(src_root, dst_parent)).run()
    assert second.copied_count == 0
    assert second.skipped_count == 3
    assert second.completed


def test_dry_run_creates_nothing():
    c, src_root, dst_parent = _tree()
    before = len(c.nodes)
    result = Copier(c, _cfg(src_root, dst_parent, dry_run=True)).run()
    assert result.dry_run
    assert result.would_copy_count == 3
    assert result.copied_count == 0
    assert len(c.nodes) == before  # nothing created


def test_exclude_substrings_skip_files():
    c = FakeDriveClient()
    src_root = c.add_folder("SourceRoot")
    dst_parent = c.add_folder("DestParent")
    c.add_file("keep.txt", src_root, size=3, md5="m1", mime="text/plain")
    c.add_file("skip.tmp", src_root, size=3, md5="m2", mime="text/plain")
    result = Copier(c, _cfg(src_root, dst_parent, exclude_substrings=[".tmp"])).run()
    assert result.copied_count == 1


def test_destination_inside_source_is_rejected():
    c = FakeDriveClient()
    src_root = c.add_folder("SourceRoot")
    inside = c.add_folder("inside", src_root)
    result = Copier(c, _cfg(src_root, inside)).run()
    assert result.copied_count == 0
    assert result.stop_reason and "inside the source" in result.stop_reason.lower()


def test_google_native_file_verified_without_md5():
    c = FakeDriveClient()
    src_root = c.add_folder("SourceRoot")
    dst_parent = c.add_folder("DestParent")
    # A Google Doc: no size, no md5.
    c.add_file("Design Doc", src_root, size=None, md5=None, mime="application/vnd.google-apps.document")
    result = Copier(c, _cfg(src_root, dst_parent)).run()
    assert result.copied_count == 1
    assert result.completed
    assert not result.failed_items
