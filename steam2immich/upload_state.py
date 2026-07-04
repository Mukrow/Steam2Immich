"""Local idempotency state for uploaded Immich assets."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import ScreenshotCandidate


logger = logging.getLogger("steam2immich.upload_state")


class UploadState:
    """Read and write local upload records keyed by Immich device asset ID."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.records = self._load()

    def has(self, device_asset_id: str) -> bool:
        """Return whether a device asset ID has already been uploaded."""

        return device_asset_id in self.records

    def get_record(self, device_asset_id: str) -> dict[str, Any] | None:
        """Return one local upload record, if present."""

        return self.records.get(device_asset_id)

    def get_asset_id(self, device_asset_id: str) -> str | None:
        """Return the Immich asset ID for an uploaded asset, if available."""

        record = self.get_record(device_asset_id)
        if record is None:
            return None

        asset_id = record.get("asset_id")
        if not asset_id:
            return None
        return str(asset_id)

    def record(
        self,
        device_asset_id: str,
        asset_id: str,
        candidate: ScreenshotCandidate,
        album_name: str | None = None,
        tag_names: list[str] | None = None,
    ) -> None:
        """Store one successful upload in local state."""

        self.records[device_asset_id] = {
            "asset_id": asset_id,
            "chosen_path": str(candidate.chosen_path),
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "album_name": album_name,
            "album_added": False,
            "tag_names": tag_names or [],
            "tags_added": False,
        }

    def prepare_followups(
        self, device_asset_id: str, album_name: str, tag_names: list[str]
    ) -> None:
        """Update desired follow-up targets and reset stale completion flags."""

        record = self.get_record(device_asset_id)
        if record is None:
            return

        if record.get("album_name") != album_name:
            record["album_name"] = album_name
            record["album_added"] = False

        if record.get("tag_names") != tag_names:
            record["tag_names"] = tag_names
            record["tags_added"] = False

    def is_complete(
        self, device_asset_id: str, album_name: str, tag_names: list[str]
    ) -> bool:
        """Return whether all current Immich follow-ups are complete."""

        record = self.get_record(device_asset_id)
        if record is None:
            return False

        return (
            record.get("asset_id") is not None
            and record.get("album_name") == album_name
            and record.get("tag_names") == tag_names
            and record.get("album_added") is True
            and record.get("tags_added") is True
        )

    def needs_album(self, device_asset_id: str) -> bool:
        """Return whether album assignment still needs to be attempted."""

        record = self.get_record(device_asset_id)
        return record is not None and record.get("album_added") is not True

    def needs_tags(self, device_asset_id: str) -> bool:
        """Return whether tag assignment still needs to be attempted."""

        record = self.get_record(device_asset_id)
        return record is not None and record.get("tags_added") is not True

    def mark_album_added(self, device_asset_id: str) -> None:
        """Mark album assignment as completed for an uploaded asset."""

        self._update_followup_status(device_asset_id, "album_added")

    def mark_tags_added(self, device_asset_id: str) -> None:
        """Mark tag assignment as completed for an uploaded asset."""

        self._update_followup_status(device_asset_id, "tags_added")

    def record_error(self, device_asset_id: str, message: str) -> None:
        """Store the latest non-fatal sync error for a local asset record."""

        record = self.records.setdefault(device_asset_id, {})
        record["last_error"] = message
        record["last_attempt_at"] = datetime.now(timezone.utc).isoformat()

    def save(self) -> None:
        """Persist local upload records to disk."""

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_name(f"{self.path.name}.tmp")
            temp_path.write_text(
                json.dumps(self.records, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            temp_path.replace(self.path)
        except OSError as error:
            logger.warning("Could not write upload state %s: %s", self.path, error)

    def _load(self) -> dict[str, dict[str, Any]]:
        """Load existing upload state, returning an empty state on errors."""

        if not self.path.exists():
            return {}

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            logger.warning("Could not read upload state %s: %s", self.path, error)
            return {}

        if not isinstance(data, dict):
            logger.warning("Upload state must be a JSON object: %s", self.path)
            return {}

        return {
            str(device_asset_id): record
            for device_asset_id, record in data.items()
            if isinstance(record, dict)
        }

    def _update_followup_status(self, device_asset_id: str, key: str) -> None:
        """Update a boolean follow-up status field on an existing record."""

        record = self.records.get(device_asset_id)
        if record is not None:
            record[key] = True
            if record.get("album_added") is True and record.get("tags_added") is True:
                record.pop("last_error", None)
