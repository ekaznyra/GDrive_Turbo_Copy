import json

import pytest

from fakes import FakeDriveClient
from gdrive_turbo_copy.models import FailedItem
from gdrive_turbo_copy.resume_store import (
    CURRENT_SCHEMA_VERSION,
    IntegrityError,
    ResumeState,
    ResumeStore,
    compute_integrity,
    deserialize,
    log_name_for,
    migrate,
    serialize,
)


def test_round_trip():
    state = ResumeState(
        account="me@example.com", source_root_id="src", dest_root_id="dst", run_id="r1",
        copied_ids={"a", "b", "c"}, folder_map={"s1": "d1"},
        completed_folders={"f1", "f2"},
        failed_items=[FailedItem("x", "x.bin", "application/octet-stream", "copyFailed", "boom")],
        copied_bytes=12345,
    )
    blob = serialize(state)
    back = deserialize(blob)
    assert back.copied_ids == {"a", "b", "c"}
    assert back.folder_map == {"s1": "d1"}
    assert back.completed_folders == {"f1", "f2"}
    assert back.copied_bytes == 12345
    assert back.run_id == "r1"
    assert len(back.failed_items) == 1
    assert back.schema_version == CURRENT_SCHEMA_VERSION


def test_integrity_detects_tampering():
    state = ResumeState(copied_ids={"a", "b"}, copied_bytes=10)
    blob = serialize(state)
    raw = json.loads(blob.decode())
    raw["copied_file_ids"].append("INJECTED")  # tamper without fixing hash
    with pytest.raises(IntegrityError):
        deserialize(json.dumps(raw).encode())


def test_integrity_present_and_valid():
    blob = serialize(ResumeState(copied_ids={"z"}))
    raw = json.loads(blob.decode())
    assert raw["integrity"] == compute_integrity(raw)


def test_migrate_v1():
    raw = {"copied_ids": ["a", "b"], "folder_map": {"s": "d"}, "lifetime_size_mb": 2}
    migrated = migrate(raw)
    assert migrated["schema_version"] == CURRENT_SCHEMA_VERSION
    assert set(migrated["copied_file_ids"]) == {"a", "b"}
    assert migrated["copied_bytes"] == int(2 * 1024 * 1024)


def test_migrate_v2_to_v3():
    raw = {"version": 2, "copied_file_ids": ["a"], "folder_map": {}, "lifetime_size_mb": 1, "failed_items": []}
    state = deserialize(json.dumps(raw).encode())  # no integrity -> skip check, migrate
    assert state.copied_ids == {"a"}
    assert state.copied_bytes == 1024 * 1024
    assert state.run_id is None


def test_migrate_v3_to_v4_adds_completed_folders():
    raw = {"schema_version": 3, "copied_file_ids": ["a"], "folder_map": {}, "copied_bytes": 0}
    state = deserialize(json.dumps(raw).encode())  # no integrity -> skip check, migrate
    assert state.schema_version == CURRENT_SCHEMA_VERSION
    assert state.completed_folders == set()


def test_legacy_log_without_integrity_loads():
    raw = {"schema_version": 2, "copied_file_ids": ["a", "b"], "folder_map": {"s": "d"}, "lifetime_size_mb": 0}
    state = deserialize(json.dumps(raw).encode())
    assert state.copied_ids == {"a", "b"}


def test_log_name_sanitizes_account():
    assert log_name_for("a/b@c.com") == ".gdrive_copy_resume.a_b_c.com.json"
    assert log_name_for(None) == ".gdrive_copy_resume.json"


def test_save_then_load_via_client():
    client = FakeDriveClient()
    root = client.add_folder("root")
    store = ResumeStore(client)
    # First load: nothing yet.
    state = store.load(root, "me@example.com")
    assert state.copied_ids == set()
    state.dest_root_id = root
    state.copied_ids = {"a", "b"}
    state.copied_bytes = 50
    store.save(state)
    # Fresh store re-reads.
    store2 = ResumeStore(client)
    loaded = store2.load(root, "me@example.com")
    assert loaded.copied_ids == {"a", "b"}
    assert loaded.copied_bytes == 50


def test_load_merges_multiple_accounts():
    client = FakeDriveClient()
    root = client.add_folder("root")
    s1 = ResumeStore(client)
    st1 = s1.load(root, "a@x.com")
    st1.dest_root_id = root
    st1.copied_ids = {"1", "2"}
    s1.save(st1)
    s2 = ResumeStore(client)
    st2 = s2.load(root, "b@x.com")
    st2.dest_root_id = root
    st2.copied_ids = {"3"}
    s2.save(st2)
    merged = ResumeStore(client).load(root, "a@x.com")
    assert merged.copied_ids == {"1", "2", "3"}


def test_folder_map_merge_first_wins_across_accounts():
    # Account A's mapping for source folder "S" must not be lost when account B's
    # (own) log is loaded with a conflicting mapping.
    client = FakeDriveClient()
    root = client.add_folder("root")
    sa = ResumeStore(client)
    sta = sa.load(root, "a@x.com")
    sta.dest_root_id = root
    sta.folder_map = {"S": "dstA"}
    sa.save(sta)
    sb = ResumeStore(client)
    stb = sb.load(root, "b@x.com")
    stb.dest_root_id = root
    stb.folder_map = {"S": "dstB"}
    sb.save(stb)
    merged = ResumeStore(client).load(root, "b@x.com")  # own log = b
    assert merged.folder_map["S"] == "dstA"  # first-wins; not overwritten/lost


def test_broken_log_raises_without_ignore():
    client = FakeDriveClient()
    root = client.add_folder("root")
    client.create_json_file(".gdrive_copy_resume.me_x.com.json", root, b"not json{", app_properties={})
    with pytest.raises(RuntimeError):
        ResumeStore(client).load(root, "me@x.com")
    # Tolerated when ignore_broken=True.
    state = ResumeStore(client).load(root, "me@x.com", ignore_broken=True)
    assert state.copied_ids == set()
