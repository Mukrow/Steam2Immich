from steam2immich.matcher import build_screenshot_candidates, build_uncompressed_index
from steam2immich.scanner import find_normal_screenshots
from steam2immich.vdf_parser import parse_screenshots_vdf


def test_build_screenshot_candidates_enriches_from_vdf_and_app_names(
    steam_root, uncompressed_dir
) -> None:
    # Candidates should use VDF metadata, resolved game names, and matched uncompressed files.
    normal_paths = find_normal_screenshots(steam_root, "test-user")
    vdf_screenshots = parse_screenshots_vdf(steam_root, "test-user")

    candidates = build_screenshot_candidates(
        normal_paths,
        uncompressed_dir=uncompressed_dir,
        vdf_screenshots=vdf_screenshots,
        app_names={"1086940": "Baldur's Gate 3"},
    )

    first = next(candidate for candidate in candidates if candidate.caption == "A dummy Steam screenshot")
    assert first.game_name == "Baldur's Gate 3"
    assert first.uncompressed_path == uncompressed_dir / "1086940_20250101010101_1.png"
    assert first.chosen_path == first.uncompressed_path


def test_build_screenshot_candidates_deduplicates_normal_paths(steam_root) -> None:
    # Duplicate normal paths should produce only one candidate.
    normal_path = (
        steam_root
        / "userdata/test-user/760/remote/1086940/screenshots/20250101010101_1.jpg"
    )

    candidates = build_screenshot_candidates([normal_path, normal_path])

    assert len(candidates) == 1


def test_build_uncompressed_index_keeps_largest_matching_file(tmp_path) -> None:
    # When several uncompressed files map to the same normal stem, the largest should win.
    small = tmp_path / "20250101010101_1.png"
    large = tmp_path / "1086940_20250101010101_1.png"
    small.write_bytes(b"small")
    large.write_bytes(b"larger-content")

    index = build_uncompressed_index(tmp_path)

    assert index["20250101010101_1"] == large
