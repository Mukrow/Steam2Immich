"""Small isolated Immich API client for uploads and album assignment."""

from __future__ import annotations

import hashlib
import logging
import requests
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import ScreenshotCandidate


logger = logging.getLogger("steam2immich.immich_client")

DEVICE_ID = "steam2immich"
REQUEST_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class UploadResult:
    """Result returned by Immich after an asset upload."""

    asset_id: str
    duplicate: bool = False


class ImmichClient:
    """Wrapper around the Immich API calls used by steam2immich."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: int = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = _normalize_base_url(base_url)
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "x-api-key": api_key,
            }
        )
        self._album_cache: dict[str, str] = {}
        self._tag_cache: dict[str, str] = {}

    def require_v3(self) -> None:
        """Verify the connected Immich server is running v3."""

        try:
            response = self.session.get(self._url("/server/version"), timeout=self.timeout)
        except requests.RequestException as error:
            raise ImmichClientError(f"Immich server version request failed: {error}") from error

        payload = self._json_response(response, "server version")
        if not isinstance(payload, dict):
            raise ImmichClientError(f"Server version response was not an object: {payload}")

        major = _major_version(payload)
        if major != 3:
            raise ImmichClientError(
                f"Unsupported Immich server version {payload}; steam2immich requires Immich v3"
            )

    def upload_asset(self, candidate: ScreenshotCandidate, device_asset_id: str) -> UploadResult:
        """Upload one source asset read-only and return the Immich upload result."""

        path = candidate.chosen_path
        data = {
            "fileCreatedAt": _file_created_at(path, candidate),
            "fileModifiedAt": _file_modified_at(path),
            "filename": path.name,
        }

        try:
            with path.open("rb") as file:
                response = self.session.post(
                    self._url("/assets"),
                    data=data,
                    files={"assetData": (path.name, file)},
                    timeout=self.timeout,
                )
        except requests.RequestException as error:
            raise ImmichClientError(f"Immich upload asset request failed: {error}") from error

        payload = self._json_response(response, "upload asset")
        asset_id = payload.get("id")
        if not asset_id:
            raise ImmichClientError(f"Upload response did not include an asset id: {payload}")

        return UploadResult(
            asset_id=str(asset_id),
            duplicate=payload.get("status") == "duplicate",
        )

    def get_or_create_album(self, name: str) -> str:
        """Return an existing album ID by name, or create the album."""

        if name in self._album_cache:
            return self._album_cache[name]

        for album in self._list_albums():
            album_name = album.get("albumName") or album.get("title")
            album_id = album.get("id")
            if album_name == name and album_id:
                self._album_cache[name] = str(album_id)
                return str(album_id)

        try:
            response = self.session.post(
                self._url("/albums"),
                json={"albumName": name},
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise ImmichClientError(f"Immich create album request failed: {error}") from error

        payload = self._json_response(response, "create album")
        album_id = payload.get("id")
        if not album_id:
            raise ImmichClientError(f"Create album response did not include an id: {payload}")

        self._album_cache[name] = str(album_id)
        return str(album_id)

    def add_asset_to_album(self, album_id: str, asset_id: str) -> None:
        """Add one uploaded asset to an Immich album."""

        try:
            response = self.session.put(
                self._url(f"/albums/{album_id}/assets"),
                json={"ids": [asset_id]},
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise ImmichClientError(f"Immich add asset to album request failed: {error}") from error

        self._raise_for_status(response, "add asset to album")

    def get_tag(self, name: str) -> str | None:
        """Return an existing tag ID by name, if Immich already has it."""

        if name in self._tag_cache:
            return self._tag_cache[name]

        for tag in self._list_tags():
            tag_name = tag.get("name") or tag.get("value")
            tag_id = tag.get("id")
            if tag_name == name and tag_id:
                self._tag_cache[name] = str(tag_id)
                return str(tag_id)

        return None

    def create_tag(self, name: str) -> str:
        """Create a new Immich tag and return its ID."""

        try:
            response = self.session.post(
                self._url("/tags"),
                json={"name": name},
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise ImmichClientError(f"Immich create tag request failed: {error}") from error

        payload = self._json_response(response, "create tag")
        tag_id = payload.get("id")
        if not tag_id:
            raise ImmichClientError(f"Create tag response did not include an id: {payload}")

        self._tag_cache[name] = str(tag_id)
        return str(tag_id)

    def get_or_create_tag(self, name: str) -> str:
        """Return an existing tag ID by name, or create the tag."""

        tag_id = self.get_tag(name)
        if tag_id is not None:
            return tag_id
        return self.create_tag(name)

    def tag_asset(self, tag_id: str, asset_id: str) -> None:
        """Apply one tag to one uploaded asset."""

        try:
            response = self.session.put(
                self._url(f"/tags/{tag_id}/assets"),
                json={"ids": [asset_id]},
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise ImmichClientError(f"Immich tag asset request failed: {error}") from error

        self._raise_for_status(response, "tag asset")

    def _list_albums(self) -> list[dict[str, Any]]:
        """Fetch albums visible to the API key owner."""

        try:
            response = self.session.get(self._url("/albums"), timeout=self.timeout)
        except requests.RequestException as error:
            raise ImmichClientError(f"Immich list albums request failed: {error}") from error

        payload = self._json_response(response, "list albums")
        if not isinstance(payload, list):
            raise ImmichClientError(f"List albums response was not a list: {payload}")
        return [album for album in payload if isinstance(album, dict)]

    def _list_tags(self) -> list[dict[str, Any]]:
        """Fetch tags visible to the API key owner."""

        try:
            response = self.session.get(self._url("/tags"), timeout=self.timeout)
        except requests.RequestException as error:
            raise ImmichClientError(f"Immich list tags request failed: {error}") from error

        payload = self._json_response(response, "list tags")
        if not isinstance(payload, list):
            raise ImmichClientError(f"List tags response was not a list: {payload}")
        return [tag for tag in payload if isinstance(tag, dict)]

    def _url(self, path: str) -> str:
        """Build a full Immich API URL for an endpoint path."""

        return f"{self.base_url}{path}"

    def _json_response(self, response: requests.Response, action: str) -> Any:
        """Validate a response and decode JSON."""

        self._raise_for_status(response, action)
        try:
            return response.json()
        except ValueError as error:
            raise ImmichClientError(f"Could not decode Immich {action} response") from error

    def _raise_for_status(self, response: requests.Response, action: str) -> None:
        """Raise a readable client error for non-success responses."""

        if 200 <= response.status_code < 300:
            return

        raise ImmichClientError(
            f"Immich {action} failed with HTTP {response.status_code}: {response.text}"
        )


class ImmichClientError(RuntimeError):
    """Raised when an Immich API request fails."""


def build_device_asset_id(candidate: ScreenshotCandidate) -> str:
    """Build the stable local identity used for upload idempotency."""

    identity = f"{candidate.app_id}:{candidate.chosen_path.resolve()}"
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()
    return f"{DEVICE_ID}:{digest}"


def album_name_for_candidate(candidate: ScreenshotCandidate, album_mode: str, single_name: str, prefix: str) -> str:
    """Resolve the target Immich album name for a screenshot candidate."""

    if album_mode == "per-game":
        return f"{prefix} {candidate.game_name}".strip()
    return single_name


def tag_names_for_candidate(candidate: ScreenshotCandidate) -> list[str]:
    """Return the fixed Steam tag set for a screenshot candidate."""

    return [
        "Steam",
        f"Steam/{candidate.game_name}",
        f"Steam App/{candidate.app_id}",
    ]


def _normalize_base_url(base_url: str) -> str:
    """Normalize user-configured Immich URLs to the API root."""

    normalized = base_url.strip().rstrip("/")
    if normalized.endswith("/api"):
        return normalized
    return f"{normalized}/api"


def _major_version(payload: dict[str, Any]) -> int | None:
    """Extract Immich's major version from known version response shapes."""

    major = payload.get("major")
    if isinstance(major, int):
        return major
    if isinstance(major, str) and major.isdigit():
        return int(major)

    version = payload.get("version")
    if isinstance(version, str):
        normalized = version.lstrip("v")
        first_part = normalized.split(".", 1)[0]
        if first_part.isdigit():
            return int(first_part)

    return None


def _file_created_at(path: Path, candidate: ScreenshotCandidate) -> str:
    """Return the upload creation timestamp for Immich."""

    if candidate.timestamp is not None:
        timestamp = candidate.timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.astimezone()
        return timestamp.isoformat()

    return _file_modified_at(path)


def _file_modified_at(path: Path) -> str:
    """Return the source file modification time as an ISO timestamp."""

    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
