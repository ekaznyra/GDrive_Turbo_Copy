from gdrive_turbo_copy.copier import DestinationIndex
from gdrive_turbo_copy.models import DriveFile, VerifyMode


def dst(name, *, id="d1", size=None, md5=None, app=None):
    return DriveFile(id=id, name=name, mime_type="application/octet-stream", size=size, md5=md5, app_properties=app or {})


def src(name, *, id="s1", size=None, md5=None):
    return DriveFile(id=id, name=name, mime_type="application/octet-stream", size=size, md5=md5)


def test_app_props_match_takes_priority():
    items = [dst("a.bin", id="d1", size=10, md5="x", app={"source_file_id": "s1"})]
    idx = DestinationIndex.build(items)
    match = idx.pop_match(src("renamed.bin", id="s1", size=999, md5="zzz"), verify_mode=VerifyMode.CHECKSUM, allow_name_only=False)
    assert match is not None and match.id == "d1"
    # consumed
    assert idx.pop_match(src("renamed.bin", id="s1"), verify_mode=VerifyMode.CHECKSUM, allow_name_only=False) is None


def test_checksum_match():
    items = [dst("a.bin", size=10, md5="abc")]
    idx = DestinationIndex.build(items)
    assert idx.pop_match(src("a.bin", id="s9", size=10, md5="abc"), verify_mode=VerifyMode.CHECKSUM, allow_name_only=False) is not None


def test_checksum_no_match_when_md5_differs():
    items = [dst("a.bin", size=10, md5="abc")]
    idx = DestinationIndex.build(items)
    assert idx.pop_match(src("a.bin", id="s9", size=10, md5="DIFFERENT"), verify_mode=VerifyMode.CHECKSUM, allow_name_only=False) is None


def test_name_size_falls_back_to_size():
    items = [dst("a.bin", size=10, md5=None)]
    idx = DestinationIndex.build(items)
    assert idx.pop_match(src("a.bin", id="s9", size=10, md5=None), verify_mode=VerifyMode.NAME_SIZE, allow_name_only=False) is not None


def test_name_size_no_match_when_size_differs():
    items = [dst("a.bin", size=10)]
    idx = DestinationIndex.build(items)
    assert idx.pop_match(src("a.bin", id="s9", size=20), verify_mode=VerifyMode.NAME_SIZE, allow_name_only=False) is None


def test_name_only_disabled_by_default():
    items = [dst("a.bin", size=10)]
    idx = DestinationIndex.build(items)
    assert idx.pop_match(src("a.bin", id="s9", size=999), verify_mode=VerifyMode.NAME_ONLY, allow_name_only=False) is None


def test_name_only_enabled():
    items = [dst("a.bin", size=10)]
    idx = DestinationIndex.build(items)
    assert idx.pop_match(src("a.bin", id="s9", size=999), verify_mode=VerifyMode.NAME_ONLY, allow_name_only=True) is not None


def test_folders_excluded_from_index():
    folder = DriveFile(id="f1", name="docs", mime_type="application/vnd.google-apps.folder")
    idx = DestinationIndex.build([folder])
    assert idx.pop_match(src("docs", id="s1"), verify_mode=VerifyMode.NAME_SIZE, allow_name_only=True) is None


def test_no_false_match_for_unknown_name():
    items = [dst("a.bin", size=10, md5="abc")]
    idx = DestinationIndex.build(items)
    assert idx.pop_match(src("other.bin", id="s9", size=10, md5="abc"), verify_mode=VerifyMode.CHECKSUM, allow_name_only=False) is None
