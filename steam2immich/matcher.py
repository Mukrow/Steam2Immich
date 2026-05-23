import logging
from pathlib import Path

from .models import ScreenshotCandidate, SteamScreenshot
from .scanner import SUPPORTED_EXTENSIONS, extract_app_id_from_path


logger = logging.getLogger("steam2immich.matcher")


def build_screenshot_candidates(
    normal_paths: list[Path],
    uncompressed_dir: Path | None = None,
    vdf_screenshots: list[SteamScreenshot] | None = None,
    app_names: dict[str, str] | None = None,
) -> list[ScreenshotCandidate]:
    candidates: list[ScreenshotCandidate] = []
    seen_normal_paths: set[Path] = set()
    uncompressed_index = build_uncompressed_index(uncompressed_dir)
    vdf_index = _index_vdf_screenshots(vdf_screenshots or [])
    app_names = app_names or {}

    for normal_path in normal_paths:
        resolved_normal_path = normal_path.resolve()
        if resolved_normal_path in seen_normal_paths:
            logger.debug("Skipping duplicate normal screenshot: %s", normal_path)
            continue

        seen_normal_paths.add(resolved_normal_path)

        app_id = extract_app_id_from_path(normal_path) or "unknown"
        vdf_screenshot = vdf_index.get(resolved_normal_path)
        if vdf_screenshot is not None:
            app_id = vdf_screenshot.app_id

        uncompressed_path = find_uncompressed_match_from_index(
            normal_path, uncompressed_index
        )
        chosen_path = uncompressed_path or normal_path

        candidates.append(
            ScreenshotCandidate(
                app_id=app_id,
                game_name=app_names.get(app_id, f"Steam App {app_id}"),
                normal_path=normal_path,
                uncompressed_path=uncompressed_path,
                chosen_path=chosen_path,
                timestamp=vdf_screenshot.timestamp if vdf_screenshot else None,
                caption=vdf_screenshot.caption if vdf_screenshot else None,
            )
        )

    return candidates


def _index_vdf_screenshots(
    vdf_screenshots: list[SteamScreenshot],
) -> dict[Path, SteamScreenshot]:
    index: dict[Path, SteamScreenshot] = {}

    for screenshot in vdf_screenshots:
        if screenshot.normal_path is None:
            continue

        index[screenshot.normal_path.resolve()] = screenshot

    return index


def build_uncompressed_index(uncompressed_dir: Path | None) -> dict[str, Path]:
    if uncompressed_dir is None:
        return {}

    if not uncompressed_dir.exists():
        logger.warning("Uncompressed screenshot directory does not exist: %s", uncompressed_dir)
        return {}

    logger.debug("Indexing uncompressed screenshots in %s", uncompressed_dir)
    index: dict[str, Path] = {}
    scanned = 0

    for path in uncompressed_dir.rglob("*"):
        if not _is_supported_file(path):
            continue

        scanned += 1
        for match_key in _possible_match_keys(path.stem):
            existing = index.get(match_key)
            if existing is None or _file_size(path) > _file_size(existing):
                index[match_key] = path

    logger.debug(
        "Indexed %d uncompressed screenshot file(s) into %d match key(s)",
        scanned,
        len(index),
    )
    return index


def find_uncompressed_match(
    normal_path: Path, uncompressed_dir: Path | None
) -> Path | None:
    return find_uncompressed_match_from_index(
        normal_path, build_uncompressed_index(uncompressed_dir)
    )


def find_uncompressed_match_from_index(
    normal_path: Path, uncompressed_index: dict[str, Path]
) -> Path | None:
    return uncompressed_index.get(normal_path.stem)


def _possible_match_keys(candidate_stem: str) -> set[str]:
    keys = {candidate_stem}

    for index, char in enumerate(candidate_stem):
        if char == "_" and index + 1 < len(candidate_stem):
            keys.add(candidate_stem[index + 1 :])

    return keys


def _is_supported_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        logger.warning("Could not read file size for candidate match: %s", path)
        return -1
