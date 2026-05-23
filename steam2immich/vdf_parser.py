"""Parse Steam VDF metadata files used by the screenshot pipeline.

The disk scanner remains the source of truth for files that currently exist.
This module reads Steam's metadata files so discovered screenshots can be
enriched with timestamps, thumbnails, captions, shortcut names, and raw Steam
fields where available.
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import SteamScreenshot


logger = logging.getLogger("steam2immich.vdf_parser")


def parse_screenshots_vdf(steam_root: Path, steam_user_id: str) -> list[SteamScreenshot]:
    """Parse ``screenshots.vdf`` into screenshot metadata records.

    Missing or malformed files are treated as non-fatal and return an empty
    list, allowing the app to continue with disk-only discovery.
    """

    path = steam_root / "userdata" / steam_user_id / "760" / "screenshots.vdf"
    if not path.exists():
        logger.warning("Steam screenshots.vdf does not exist: %s", path)
        return []

    try:
        data = load_vdf(path)
    except Exception as error:
        logger.warning("Could not parse screenshots.vdf %s: %s", path, error)
        return []

    screenshots_root = data.get("screenshots")
    if not isinstance(screenshots_root, dict):
        logger.warning("screenshots.vdf did not contain a screenshots object: %s", path)
        return []

    screenshots: list[SteamScreenshot] = []
    for app_id, app_entries in screenshots_root.items():
        if app_id == "shortcutnames" or not isinstance(app_entries, dict):
            continue

        for raw_entry in app_entries.values():
            if not isinstance(raw_entry, dict):
                continue

            screenshot = _parse_screenshot_entry(
                app_id=str(app_id),
                entry=raw_entry,
                steam_root=steam_root,
                steam_user_id=steam_user_id,
            )
            if screenshot is not None:
                screenshots.append(screenshot)

    return screenshots


def parse_shortcut_names(steam_root: Path, steam_user_id: str) -> dict[str, str]:
    """Return non-Steam shortcut IDs and names from ``screenshots.vdf``."""

    path = steam_root / "userdata" / steam_user_id / "760" / "screenshots.vdf"
    if not path.exists():
        return {}

    try:
        data = load_vdf(path)
    except Exception:
        return {}

    shortcuts = data.get("screenshots", {}).get("shortcutnames", {})
    if not isinstance(shortcuts, dict):
        return {}

    return {str(app_id): str(name) for app_id, name in shortcuts.items() if name}


def load_vdf(path: Path) -> dict[str, Any]:
    """Load a VDF/ACF file with the dependency parser or the local fallback."""

    try:
        import vdf
    except ImportError:
        return _load_simple_vdf(path)

    with path.open("r", encoding="utf-8", errors="replace") as file:
        return vdf.load(file)


def _parse_screenshot_entry(
    app_id: str, entry: dict[str, Any], steam_root: Path, steam_user_id: str
) -> SteamScreenshot | None:
    """Convert one VDF screenshot entry into a ``SteamScreenshot``."""

    filename = _get_string(entry, "filename")
    if not filename:
        return None

    thumbnail = _get_string(entry, "thumbnail")
    game_id = _get_string(entry, "gameid") or app_id

    return SteamScreenshot(
        app_id=game_id,
        game_name=None,
        normal_path=_resolve_remote_path(steam_root, steam_user_id, filename),
        thumbnail_path=_resolve_remote_path(steam_root, steam_user_id, thumbnail)
        if thumbnail
        else None,
        timestamp=_parse_timestamp(_get_string(entry, "creation")),
        caption=_get_string(entry, "caption") or _get_string(entry, "description"),
        raw_metadata=entry,
    )


def _resolve_remote_path(steam_root: Path, steam_user_id: str, relative_path: str) -> Path:
    """Convert a VDF relative path into Steam's normal screenshot path."""

    normalized = Path(*relative_path.replace("\\", "/").split("/"))
    return steam_root / "userdata" / steam_user_id / "760" / "remote" / normalized


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromtimestamp(int(value))
    except (OSError, ValueError):
        return None


def _get_string(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    return str(value)


def _load_simple_vdf(path: Path) -> dict[str, Any]:
    """Small VDF parser fallback for the simple quoted key/value files Steam uses."""

    tokens = re.findall(
        r'"((?:\\.|[^"\\])*)"|([{}])',
        path.read_text(encoding="utf-8", errors="replace"),
    )
    parsed_tokens = [_unescape(value) if value else brace for value, brace in tokens]
    index = 0

    def parse_object() -> dict[str, Any]:
        nonlocal index
        result: dict[str, Any] = {}

        while index < len(parsed_tokens):
            token = parsed_tokens[index]
            index += 1

            if token == "}":
                return result
            if token == "{":
                raise ValueError("Unexpected object start")

            if index >= len(parsed_tokens):
                raise ValueError("Missing value for key")

            next_token = parsed_tokens[index]
            index += 1
            if next_token == "{":
                result[token] = parse_object()
            elif next_token == "}":
                raise ValueError("Unexpected object end")
            else:
                result[token] = next_token

        return result

    return parse_object()


def _unescape(value: str) -> str:
    return value.replace(r"\"", '"').replace(r"\\", "\\")
