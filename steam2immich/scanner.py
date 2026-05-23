import logging
from pathlib import Path


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

logger = logging.getLogger("steam2immich.scanner")


def find_normal_screenshots(steam_root: Path, steam_user_id: str) -> list[Path]:
    screenshots_root = steam_root / "userdata" / steam_user_id / "760" / "remote"

    if not screenshots_root.exists():
        logger.warning("Steam screenshot directory does not exist: %s", screenshots_root)
        return []

    screenshots: list[Path] = []
    for path in screenshots_root.glob("*/screenshots/*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            screenshots.append(path)

    return sorted(screenshots)


def extract_app_id_from_path(path: Path) -> str | None:
    parts = path.parts

    for index, part in enumerate(parts):
        if part == "760" and _matches_remote_screenshot_pattern(parts, index):
            return parts[index + 2]

    return None


def _matches_remote_screenshot_pattern(parts: tuple[str, ...], index: int) -> bool:
    return (
        len(parts) > index + 4
        and parts[index + 1] == "remote"
        and parts[index + 3] == "screenshots"
    )
