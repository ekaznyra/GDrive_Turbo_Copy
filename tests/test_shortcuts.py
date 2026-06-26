from fakes import FakeDriveClient, folder_link
from gdrive_turbo_copy.copier import Copier
from gdrive_turbo_copy.models import CopyConfig, VerifyMode


def _config(client, src_id, dst_id, **kw):
    return CopyConfig(
        source_link=folder_link(src_id), dest_link=folder_link(dst_id),
        workers=1, verify_mode=VerifyMode.CHECKSUM, **kw,
    )


def test_shortcut_to_file_is_resolved_and_copied():
    c = FakeDriveClient()
    src_root = c.add_folder("SourceRoot")
    dst_parent = c.add_folder("DestParent")
    vault = c.add_folder("Vault")
    target = c.add_file("real.txt", vault, size=5, md5="m", mime="text/plain")
    sc = c.add_shortcut("link.txt", src_root, target)

    result = Copier(c, _config(c, src_root, dst_parent)).run()

    assert result.completed
    assert result.copied_count == 1
    copies = [
        n for n in c.nodes.values()
        if (n.get("appProperties") or {}).get("source_shortcut_id") == sc
    ]
    assert len(copies) == 1
    assert copies[0]["name"] == "link.txt"
    assert copies[0]["appProperties"]["source_file_id"] == target


def test_shortcut_loop_does_not_recurse_forever():
    c = FakeDriveClient()
    src_root = c.add_folder("SourceRoot")
    dst_parent = c.add_folder("DestParent")
    folder_a = c.add_folder("A", src_root)
    # A shortcut inside A that points back to A -> a cycle.
    c.add_shortcut("loop", folder_a, folder_a)

    result = Copier(c, _config(c, src_root, dst_parent)).run()

    # Terminates, no crash; the loop is detected and skipped.
    assert result.completed
    assert result.copied_count == 0


def test_unresolvable_shortcut_is_recorded_as_failed():
    c = FakeDriveClient()
    src_root = c.add_folder("SourceRoot")
    dst_parent = c.add_folder("DestParent")
    c.add_shortcut("dangling", src_root, "nonexistent_target_0001")

    result = Copier(c, _config(c, src_root, dst_parent)).run()

    reasons = {fi.reason for fi in result.failed_items}
    assert "cannotAccessShortcutTarget" in reasons
    assert not result.fully_ok  # failures keep the run from being "fully ok"
