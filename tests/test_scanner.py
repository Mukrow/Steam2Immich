from pathlib import Path

from steam2immich.scanner import extract_app_id_from_path, find_normal_screenshots


def test_find_normal_screenshots_discovers_supported_fixture_images(steam_root) -> None:
    # The scanner should find only supported image files in the fake Steam tree.
    screenshots = find_normal_screenshots(steam_root, "test-user")

    assert [path.name for path in screenshots] == [
        "20250101010101_1.jpg",
        "20250101010101_1_vr.jpg",
        "20250102020202_1.png",
    ]


def test_find_normal_screenshots_returns_empty_for_missing_directory(tmp_path) -> None:
    # A missing Steam screenshot directory should be non-fatal and return no files.
    screenshots = find_normal_screenshots(tmp_path / "missing-steam", "test-user")

    assert screenshots == []


def test_extract_app_id_from_steam_screenshot_path(steam_root) -> None:
    # App IDs should be read from Steam's userdata/760/remote path structure.
    path = steam_root / "userdata/test-user/760/remote/1086940/screenshots/shot.jpg"

    assert extract_app_id_from_path(path) == "1086940"


def test_extract_app_id_returns_none_for_non_steam_path() -> None:
    # Paths outside Steam's screenshot layout should not produce an app ID.
    assert extract_app_id_from_path(Path("screenshots/shot.jpg")) is None
