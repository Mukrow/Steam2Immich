"""Resolve Steam app IDs to human-readable game names.

Steam screenshot metadata usually gives us an app ID, but not a useful title.
This module prefers local Steam data because it is fast and private, then uses a
small remote Steam Store lookup only for app IDs that are missing locally.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    requests = None

from .vdf_parser import load_vdf


logger = logging.getLogger("steam2immich.steam_apps")


@dataclass
class AppNameResolution:
    """Resolved app names plus counters explaining where the names came from."""

    names: dict[str, str]
    unknown_app_ids: list[str]
    override_hits: int = 0
    local_hits: int = 0
    remote_hits: int = 0
    cache_hits: int = 0
    fallbacks: int = 0


def resolve_app_names(
    app_ids: set[str],
    steam_root: Path,
    cache_path: Path,
    overrides_path: Path,
    shortcut_names: dict[str, str] | None = None,
) -> AppNameResolution:
    """Resolve each app ID using local data, cache, remote lookup, then fallback.

    The lookup order is intentionally conservative:
    shortcut names from screenshots.vdf, installed app manifests, cache, Steam
    Store request, and finally ``Steam App <appid>``.
    """

    overrides = load_name_overrides(overrides_path)
    shortcut_names = shortcut_names or {}
    cache = _load_name_cache(cache_path)
    library_paths = find_steam_library_paths(steam_root)

    result = AppNameResolution(names={}, unknown_app_ids=[])
    for app_id in sorted(app_ids):
        if app_id in overrides:
            result.names[app_id] = overrides[app_id]
            result.override_hits += 1
            continue

        if app_id in shortcut_names:
            result.names[app_id] = shortcut_names[app_id]
            result.local_hits += 1
            continue

        local_name = find_local_app_name(app_id, library_paths)
        if local_name:
            result.names[app_id] = local_name
            result.local_hits += 1
            continue

        cached_name = cache.get(app_id)
        if cached_name:
            result.names[app_id] = cached_name
            result.cache_hits += 1
            continue

        remote_name = fetch_remote_app_name(app_id)
        if remote_name:
            result.names[app_id] = remote_name
            cache[app_id] = remote_name
            result.remote_hits += 1
            continue

        result.names[app_id] = f"Steam App {app_id}"
        result.unknown_app_ids.append(app_id)
        result.fallbacks += 1
        logger.warning(
            "Unknown Steam app id %s. Add it to %s to name it manually.",
            app_id,
            overrides_path,
        )

    if result.remote_hits:
        _save_name_cache(cache_path, cache)

    return result


def load_name_overrides(overrides_path: Path) -> dict[str, str]:
    """Load user-maintained app ID name overrides from JSON."""

    if not overrides_path.exists():
        return {}

    try:
        data = json.loads(overrides_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("Could not read app name overrides %s: %s", overrides_path, error)
        return {}

    if not isinstance(data, dict):
        logger.warning("App name overrides must be a JSON object: %s", overrides_path)
        return {}

    return {str(app_id): str(name) for app_id, name in data.items() if name}


def find_steam_library_paths(steam_root: Path) -> list[Path]:
    """Return all known Steam library roots, including secondary libraries."""

    library_paths = [steam_root]
    libraryfolders_path = steam_root / "steamapps" / "libraryfolders.vdf"

    if not libraryfolders_path.exists():
        return library_paths

    try:
        data = load_vdf(libraryfolders_path)
    except Exception as error:
        logger.warning("Could not parse Steam library folders %s: %s", libraryfolders_path, error)
        return library_paths

    libraryfolders = data.get("libraryfolders", {})
    if not isinstance(libraryfolders, dict):
        return library_paths

    for entry in libraryfolders.values():
        if not isinstance(entry, dict):
            continue

        path_value = entry.get("path")
        if path_value:
            library_paths.append(Path(str(path_value)))

    return _dedupe_paths(library_paths)


def find_local_app_name(app_id: str, library_paths: list[Path]) -> str | None:
    """Look for an app's display name in local ``appmanifest_<appid>.acf`` files."""

    for library_path in library_paths:
        manifest_path = library_path / "steamapps" / f"appmanifest_{app_id}.acf"
        if not manifest_path.exists():
            continue

        try:
            data = load_vdf(manifest_path)
        except Exception as error:
            logger.warning("Could not parse app manifest %s: %s", manifest_path, error)
            continue

        app_state = data.get("AppState", {})
        if isinstance(app_state, dict) and app_state.get("name"):
            return str(app_state["name"])

    return None


def fetch_remote_app_name(app_id: str) -> str | None:
    """Fetch an app name from the public Steam Store appdetails endpoint."""

    if requests is None:
        logger.warning("requests is not installed; skipping remote Steam lookup for %s", app_id)
        return None

    url = "https://store.steampowered.com/api/appdetails"
    try:
        response = requests.get(url, params={"appids": app_id, "filters": "basic"}, timeout=5)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as error:
        logger.warning("Could not fetch Steam app name for %s: %s", app_id, error)
        return None
    except ValueError as error:
        logger.warning("Could not decode Steam app name response for %s: %s", app_id, error)
        return None

    app_payload = payload.get(app_id, {})
    if not isinstance(app_payload, dict) or not app_payload.get("success"):
        return None

    data = app_payload.get("data", {})
    if isinstance(data, dict) and data.get("name"):
        return str(data["name"])

    return None


def _load_name_cache(cache_path: Path) -> dict[str, str]:
    if not cache_path.exists():
        return {}

    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("Could not read app name cache %s: %s", cache_path, error)
        return {}

    if not isinstance(data, dict):
        return {}

    return {str(app_id): str(name) for app_id, name in data.items() if name}


def _save_name_cache(cache_path: Path, cache: dict[str, str]) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(cache, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError as error:
        logger.warning("Could not write app name cache %s: %s", cache_path, error)


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    unique_paths: list[Path] = []

    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue

        seen.add(resolved)
        unique_paths.append(path)

    return unique_paths
