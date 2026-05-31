from datetime import datetime

from steam2immich.vdf_parser import parse_screenshots_vdf, parse_shortcut_names


def test_parse_screenshots_vdf_reads_fixture_metadata(steam_root) -> None:
    # The parser should convert Steam VDF entries into enriched screenshot metadata.
    screenshots = parse_screenshots_vdf(steam_root, "test-user")

    first = next(screenshot for screenshot in screenshots if screenshot.app_id == "1086940")
    assert first.normal_path == (
        steam_root
        / "userdata/test-user/760/remote/1086940/screenshots/20250101010101_1.jpg"
    )
    assert first.thumbnail_path == (
        steam_root
        / "userdata/test-user/760/remote/1086940/screenshots/thumbnails/20250101010101_1.jpg"
    )
    assert first.timestamp == datetime.fromtimestamp(1735689661)
    assert first.caption == "A dummy Steam screenshot"


def test_parse_shortcut_names_reads_fixture_shortcuts(steam_root) -> None:
    # Shortcut names should be read from the special screenshots.vdf shortcut block.
    assert parse_shortcut_names(steam_root, "test-user") == {"999999": "Fixture Shortcut"}


def test_parse_screenshots_vdf_returns_empty_for_missing_file(tmp_path) -> None:
    # Missing Steam metadata should not prevent disk-only screenshot discovery.
    assert parse_screenshots_vdf(tmp_path, "test-user") == []


def test_parse_screenshots_vdf_returns_empty_for_malformed_file(tmp_path) -> None:
    # Malformed Steam metadata should be handled as a non-fatal empty parse.
    path = tmp_path / "userdata/test-user/760/screenshots.vdf"
    path.parent.mkdir(parents=True)
    path.write_text('"screenshots" {', encoding="utf-8")

    assert parse_screenshots_vdf(tmp_path, "test-user") == []
