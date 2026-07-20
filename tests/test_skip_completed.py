"""Fast resume: skip re-listing subtrees that were copied in full (opt-in)."""

from fakes import FakeDriveClient, folder_link
from gdrive_turbo_copy.copier import Copier
from gdrive_turbo_copy.models import CopyConfig, VerifyMode


def _cfg(src_id, dst_id, **kw):
    return CopyConfig(
        source_link=folder_link(src_id), dest_link=folder_link(dst_id),
        workers=1, verify_mode=VerifyMode.CHECKSUM, **kw,
    )


def _tree_with_two_subfolders():
    """root/{a.txt, subOK/{c.txt}, subBAD/{d.txt}} — d.txt is rigged to fail once."""
    c = FakeDriveClient()
    src_root = c.add_folder("SourceRoot")
    dst_parent = c.add_folder("DestParent")
    c.add_file("a.txt", src_root, size=3, md5="ma", mime="text/plain")
    sub_ok = c.add_folder("subOK", src_root)
    c.add_file("c.txt", sub_ok, size=5, md5="mc", mime="text/plain")
    sub_bad = c.add_folder("subBAD", src_root)
    d_id = c.add_file("d.txt", sub_bad, size=6, md5="md", mime="text/plain")
    return c, src_root, dst_parent, sub_ok, sub_bad, d_id


def test_completed_subtree_is_skipped_on_resume():
    c, src_root, dst_parent, sub_ok, sub_bad, d_id = _tree_with_two_subfolders()

    # Run 1: d.txt fails, so the run is not fully OK and the resume log persists.
    c.copy_fail_ids = {d_id}
    first = Copier(c, _cfg(src_root, dst_parent, skip_completed_folders=True)).run()
    assert first.copied_count == 2  # a.txt + c.txt
    assert any(fi.reason == "insufficientFilePermissions" for fi in first.failed_items)

    # Run 2: fix d.txt, resume. subOK was complete -> must NOT be re-listed.
    c.copy_fail_ids = set()
    c.list_children_calls = []
    second = Copier(c, _cfg(src_root, dst_parent, skip_completed_folders=True)).run()

    assert sub_ok not in c.list_children_calls  # completed subtree skipped
    assert sub_bad in c.list_children_calls  # incomplete subtree re-listed
    assert second.skipped_complete_folders == 1
    assert second.copied_count == 1  # only d.txt this run
    assert second.completed and not second.has_failures


def test_completed_skip_off_relists_everything():
    c, src_root, dst_parent, sub_ok, sub_bad, d_id = _tree_with_two_subfolders()
    c.copy_fail_ids = {d_id}
    Copier(c, _cfg(src_root, dst_parent, skip_completed_folders=True)).run()

    # Control: default behavior (flag off) re-lists the completed subtree.
    c.copy_fail_ids = set()
    c.list_children_calls = []
    second = Copier(c, _cfg(src_root, dst_parent)).run()  # skip_completed_folders defaults off
    assert sub_ok in c.list_children_calls
    assert second.skipped_complete_folders == 0


def test_skip_does_not_pick_up_new_file_in_completed_folder():
    c, src_root, dst_parent, sub_ok, sub_bad, d_id = _tree_with_two_subfolders()
    c.copy_fail_ids = {d_id}
    Copier(c, _cfg(src_root, dst_parent, skip_completed_folders=True)).run()

    # A new file lands in the completed subtree before the resume.
    c.copy_fail_ids = set()
    c.add_file("new.txt", sub_ok, size=9, md5="mn", mime="text/plain")

    resumed = Copier(c, _cfg(src_root, dst_parent, skip_completed_folders=True)).run()
    # subOK is skipped, so new.txt is NOT copied (documented trade-off).
    assert not any(
        (n.get("appProperties") or {}).get("source_file_id") == _new_id_of(c, "new.txt")
        for n in c.nodes.values()
    )
    # Only d.txt gets copied on the resume.
    assert resumed.copied_count == 1


def test_completed_folders_persisted_in_log():
    c, src_root, dst_parent, sub_ok, sub_bad, d_id = _tree_with_two_subfolders()
    c.copy_fail_ids = {d_id}
    Copier(c, _cfg(src_root, dst_parent, skip_completed_folders=True)).run()

    # The resume log JSON should record subOK (a fully-copied subtree).
    from gdrive_turbo_copy.resume_store import deserialize

    logs = [n for n in c.nodes.values() if str(n.get("name", "")).startswith(".gdrive_copy_resume")]
    assert logs, "resume log should persist because the run had a failure"
    state = deserialize(logs[0]["_content"])
    assert sub_ok in state.completed_folders
    assert sub_bad not in state.completed_folders


def _new_id_of(c, name):
    for fid, n in c.nodes.items():
        if n.get("name") == name and not (n.get("appProperties") or {}).get("copied_by_tool"):
            return fid
    return None
