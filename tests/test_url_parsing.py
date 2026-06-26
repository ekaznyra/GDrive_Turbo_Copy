import pytest

from gdrive_turbo_copy.urls import extract_folder_id

VALID = "1AbC_dEfGhIjKlMnOpQrStUvWxYz0123456"


@pytest.mark.parametrize(
    "url, expected",
    [
        (f"https://drive.google.com/drive/folders/{VALID}", VALID),
        (f"https://drive.google.com/drive/folders/{VALID}?usp=sharing", VALID),
        (f"https://drive.google.com/open?id={VALID}", VALID),
        (f"https://drive.google.com/file/d/{VALID}/view", VALID),
        (f"https://drive.google.com/uc?id={VALID}&export=download", VALID),
        (VALID, VALID),
        (f"  {VALID}  ", VALID),
    ],
)
def test_extract_valid(url, expected):
    assert extract_folder_id(url) == expected


@pytest.mark.parametrize("url", ["", None, "   ", "not a link", "https://example.com/"])
def test_extract_invalid(url):
    assert extract_folder_id(url) is None


def test_folders_pattern_wins_over_bare():
    url = f"https://drive.google.com/drive/folders/{VALID}"
    assert extract_folder_id(url) == VALID
