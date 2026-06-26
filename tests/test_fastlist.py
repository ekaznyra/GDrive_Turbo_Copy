from fakes import FakeDriveClient, folder_link
from gdrive_turbo_copy.copier import Copier
from gdrive_turbo_copy.models import CopyConfig, VerifyMode


def _cfg(src_id, dst_id, *, fast_list=False, **kw):
    return CopyConfig(
        source_link=folder_link(src_id), dest_link=folder_link(dst_id),
        workers=1, verify_mode=VerifyMode.CHECKSUM, fast_list=fast_list, **kw,
    )


def _wide_tree():
    """Root with 3 sibling subfolders, each containing 2 files, plus a nested
    sub-subfolder, to exercise batched listing + recursion."""
    c = FakeDriveClient()
    src_root = c.add_folder("SourceRoot")
    dst_parent = c.add_folder("DestParent")
    for letter in ("A", "B", "C"):
        fld = c.add_folder(f"folder{letter}", src_root)
        c.add_file(f"{letter}1.txt", fld, size=3, md5=f"{letter}1", mime="text/plain")
        c.add_file(f"{letter}2.txt", fld, size=4, md5=f"{letter}2", mime="text/plain")
    # nested folder under folderA's id (find it)
    folder_a = next(n["id"] for n in c.nodes.values() if n["name"] == "folderA")
    sub = c.add_folder("nested", folder_a)
    c.add_file("deep.txt", sub, size=5, md5="deep", mime="text/plain")
    return c, src_root, dst_parent


def test_fast_list_copies_everything():
    c, src_root, dst_parent = _wide_tree()
    result = Copier(c, _cfg(src_root, dst_parent, fast_list=True)).run()
    assert result.completed
    assert result.copied_count == 7  # 3*2 + 1 nested
    assert not result.failed_items
    assert c.multi_calls > 0  # the batched path was actually used


def test_fast_list_matches_default():
    c1, s1, d1 = _wide_tree()
    slow = Copier(c1, _cfg(s1, d1, fast_list=False)).run()
    c2, s2, d2 = _wide_tree()
    fast = Copier(c2, _cfg(s2, d2, fast_list=True)).run()
    assert fast.copied_count == slow.copied_count == 7


def test_fast_list_fallback_when_multi_returns_empty():
    # Drive returns empty for the multi-parent query: the fallback must re-list
    # each folder individually so NOTHING is silently skipped.
    c, src_root, dst_parent = _wide_tree()
    c.multi_returns_empty = True
    result = Copier(c, _cfg(src_root, dst_parent, fast_list=True)).run()
    assert result.completed
    assert result.copied_count == 7  # complete despite the flaky empty batch
    assert not result.failed_items


def test_fast_list_multi_parent_file_copied_under_every_parent():
    # A legacy file living in two sibling folders must be copied under BOTH in
    # fast-list mode (matching the default path) -- regression for the dropped
    # `break` in the parent-mapping loop.
    c = FakeDriveClient()
    src_root = c.add_folder("SourceRoot")
    dst_parent = c.add_folder("DestParent")
    fa = c.add_folder("folderA", src_root)
    fb = c.add_folder("folderB", src_root)
    # folderB also has its own file, so its batch bucket is non-empty even
    # without the shared file -> the empty-fallback would NOT save us here.
    c.add_file("only_b.txt", fb, size=2, md5="b", mime="text/plain")
    shared = c.add_file("shared.txt", fa, size=3, md5="s", mime="text/plain", extra_parents=[fb])

    result = Copier(c, _cfg(src_root, dst_parent, fast_list=True)).run()

    assert result.completed
    copies = [n for n in c.nodes.values()
              if (n.get("appProperties") or {}).get("source_file_id") == shared]
    assert len(copies) == 2  # one under destA, one under destB


def test_fast_list_dry_run():
    c, src_root, dst_parent = _wide_tree()
    result = Copier(c, _cfg(src_root, dst_parent, fast_list=True, dry_run=True)).run()
    assert result.would_copy_count == 7
    assert result.copied_count == 0
