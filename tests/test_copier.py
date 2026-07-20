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


def test_metadata_preserved_in_copy_body():
    c = FakeDriveClient()
    src_root = c.add_folder("SourceRoot")
    dst_parent = c.add_folder("DestParent")
    c.add_file(
        "doc.txt", src_root, size=3, md5="m", mime="text/plain",
        modified="2020-01-02T03:04:05.000Z", created="2019-01-01T00:00:00.000Z",
        description="hello world",
    )
    result = Copier(c, _cfg(src_root, dst_parent)).run()
    assert result.copied_count == 1
    body = c.last_copy_body
    assert body["modifiedTime"] == "2020-01-02T03:04:05.000Z"
    assert body["createdTime"] == "2019-01-01T00:00:00.000Z"
    assert body["description"] == "hello world"


def test_metadata_not_sent_when_disabled():
    c = FakeDriveClient()
    src_root = c.add_folder("SourceRoot")
    dst_parent = c.add_folder("DestParent")
    c.add_file("doc.txt", src_root, size=3, md5="m", mime="text/plain", modified="2020-01-02T03:04:05.000Z")
    Copier(c, _cfg(src_root, dst_parent, preserve_metadata=False)).run()
    assert "modifiedTime" not in c.last_copy_body


def test_oversized_single_file_is_skipped_and_reported():
    from gdrive_turbo_copy.models import GIB, MAX_SINGLE_FILE_COPY_GB

    c = FakeDriveClient()
    src_root = c.add_folder("SourceRoot")
    dst_parent = c.add_folder("DestParent")
    big = int((MAX_SINGLE_FILE_COPY_GB + 1) * GIB)
    c.add_file("huge.bin", src_root, size=big, md5="m")
    result = Copier(c, _cfg(src_root, dst_parent, max_copy_size_gb=0)).run()
    assert result.copied_count == 0
    assert any(fi.reason == "fileTooLargeToCopy" for fi in result.failed_items)


def test_copy_flags_passed_through():
    c = FakeDriveClient()
    src_root = c.add_folder("SourceRoot")
    dst_parent = c.add_folder("DestParent")
    c.add_file("a.txt", src_root, size=3, md5="m", mime="text/plain")
    Copier(c, _cfg(src_root, dst_parent, ignore_default_visibility=True, keep_revision_forever=True)).run()
    assert c.last_copy_kwargs == {"ignore_default_visibility": True, "keep_revision_forever": True}


def test_preflight_blocks_unwritable_destination():
    c = FakeDriveClient()
    src_root = c.add_folder("SourceRoot")
    dst_parent = c.add_folder("DestParent")
    c.add_file("a.txt", src_root, size=3, md5="m", mime="text/plain")
    c.nodes[dst_parent]["capabilities"] = {"canAddChildren": False}
    result = Copier(c, _cfg(src_root, dst_parent)).run()
    assert result.copied_count == 0
    assert result.stop_reason and "permission to add" in result.stop_reason.lower()


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


def test_copy_verified_from_response_without_extra_metadata_fetch():
    c = FakeDriveClient()
    src_root = c.add_folder("SourceRoot")
    dst_parent = c.add_folder("DestParent")
    src_file = c.add_file("a.txt", src_root, size=3, md5="ma", mime="text/plain")
    result = Copier(c, _cfg(src_root, dst_parent)).run()
    assert result.copied_count == 1 and result.completed and not result.failed_items
    # The copied file's own id must never be fetched: verification uses the
    # fields already returned by files.copy (the source is fetched once for its
    # root metadata, which is unrelated).
    copied = next(
        n for n in c.nodes.values()
        if (n.get("appProperties") or {}).get("source_file_id") == src_file
    )
    assert copied["id"] not in c.get_metadata_calls


def test_copy_falls_back_to_metadata_fetch_when_md5_missing_in_response():
    # Simulate a copy response that omits md5 (Drive occasionally lags on
    # computing it): the copier must fetch metadata so the md5 check is not
    # silently downgraded to a size-only match.
    c = FakeDriveClient()
    src_root = c.add_folder("SourceRoot")
    dst_parent = c.add_folder("DestParent")
    src_file = c.add_file("a.txt", src_root, size=3, md5="ma", mime="text/plain")

    real_copy = c.copy_file

    def copy_without_md5(file_id, body, **kw):
        created = real_copy(file_id, body, **kw)
        created.pop("md5Checksum", None)  # response lacks the checksum
        return created

    c.copy_file = copy_without_md5
    result = Copier(c, _cfg(src_root, dst_parent)).run()
    assert result.copied_count == 1 and result.completed and not result.failed_items
    copied = next(
        n for n in c.nodes.values()
        if (n.get("appProperties") or {}).get("source_file_id") == src_file
    )
    assert copied["id"] in c.get_metadata_calls  # fallback fetch happened


def test_flush_threshold_widens_as_log_grows():
    c = FakeDriveClient()
    src_root = c.add_folder("SourceRoot")
    dst_parent = c.add_folder("DestParent")
    copier = Copier(c, _cfg(src_root, dst_parent))
    for count, expected in [(0, 50), (1999, 50), (2000, 200), (10_000, 1000), (50_000, 2000)]:
        copier._state.copied_ids = {f"id{i}" for i in range(count)}
        assert copier._flush_threshold() == expected
