from fakes import FakeDriveClient, folder_link, make_error
from gdrive_turbo_copy.copier import Copier
from gdrive_turbo_copy.models import GIB, CopyConfig, VerifyMode


def _config(src_id, dst_id, *, workers=1, **kw):
    return CopyConfig(
        source_link=folder_link(src_id), dest_link=folder_link(dst_id),
        workers=workers, verify_mode=VerifyMode.CHECKSUM, **kw,
    )


def test_size_guard_stops_before_exceeding_budget():
    c = FakeDriveClient()
    src_root = c.add_folder("SourceRoot")
    dst_parent = c.add_folder("DestParent")
    for i in range(3):
        c.add_file(f"f{i}.bin", src_root, size=GIB, md5=f"m{i}", mime="application/octet-stream")

    result = Copier(c, _config(src_root, dst_parent, max_copy_size_gb=1.5)).run()

    assert result.copied_count == 1  # one 1-GiB file fits; the next would exceed 1.5 GB
    assert not result.completed
    assert result.stop_reason and "max copy size" in result.stop_reason.lower()


def test_fatal_daily_quota_stops_and_preserves_progress():
    c = FakeDriveClient()
    src_root = c.add_folder("SourceRoot")
    dst_parent = c.add_folder("DestParent")
    c.add_file("a.bin", src_root, size=10, md5="a")
    c.add_file("b.bin", src_root, size=10, md5="b")
    # Drive returns dailyLimitExceeded on the first copy attempt.
    c.copy_error_on_call = 1
    c.copy_error = make_error(403, "dailyLimitExceeded", "User rate/daily limit exceeded")

    result = Copier(c, _config(src_root, dst_parent)).run()

    assert result.copied_count == 0
    assert not result.completed
    assert result.stop_reason and "quota" in result.stop_reason.lower()
    # A resume log was written so the run can continue later.
    assert any(n["name"].startswith(".gdrive_copy_resume") for n in c.nodes.values())


def test_size_guard_holds_under_concurrency():
    # With 8 workers and a 4.5 GB budget, exactly four 1-GiB files fit; the
    # reservation under lock must prevent concurrent workers from overshooting.
    c = FakeDriveClient()
    src_root = c.add_folder("SourceRoot")
    dst_parent = c.add_folder("DestParent")
    for i in range(10):
        c.add_file(f"f{i:02d}.bin", src_root, size=GIB, md5=f"m{i}")

    result = Copier(c, _config(src_root, dst_parent, max_copy_size_gb=4.5, workers=8)).run()

    assert result.copied_count == 4
    assert result.copied_bytes <= int(4.5 * GIB)
    assert not result.completed


def test_quota_during_folder_creation_stops_gracefully():
    # A FATAL_QUOTA raised while creating the destination root folder must be
    # converted to a graceful stop, not propagate as an unhandled exception.
    c = FakeDriveClient()
    src_root = c.add_folder("SourceRoot")
    dst_parent = c.add_folder("DestParent")
    c.add_file("a.bin", src_root, size=10, md5="a")
    c.create_error_on_call = 1
    c.create_error = make_error(403, "dailyLimitExceeded", "Daily quota exceeded")

    result = Copier(c, _config(src_root, dst_parent)).run()  # must not raise

    assert result.copied_count == 0
    assert not result.completed
    assert result.stop_reason and "quota" in result.stop_reason.lower()


def test_unlimited_when_max_size_zero():
    c = FakeDriveClient()
    src_root = c.add_folder("SourceRoot")
    dst_parent = c.add_folder("DestParent")
    for i in range(3):
        c.add_file(f"f{i}.bin", src_root, size=GIB, md5=f"m{i}")

    result = Copier(c, _config(src_root, dst_parent, max_copy_size_gb=0)).run()

    assert result.copied_count == 3
    assert result.completed
