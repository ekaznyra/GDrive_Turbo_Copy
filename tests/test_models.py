import pytest

from gdrive_turbo_copy.models import (
    APPPROP_MAX_ENTRIES,
    TOOL_TAG,
    validate_app_properties,
)


def test_valid_app_properties_ok():
    validate_app_properties(
        {"source_file_id": "1" * 33, "source_md5": "a" * 32, "copied_by_tool": TOOL_TAG}
    )  # must not raise


def test_oversized_entry_rejected():
    with pytest.raises(ValueError):
        validate_app_properties({"k": "x" * 200})  # key+value > 124 bytes


def test_too_many_entries_rejected():
    props = {f"k{i}": "v" for i in range(APPPROP_MAX_ENTRIES + 1)}
    with pytest.raises(ValueError):
        validate_app_properties(props)
