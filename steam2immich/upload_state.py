"""Local idempotency state for uploaded Immich assets."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import PreparedAsset


logger = logging.getLogger("steam2immich.upload_state")


class UploadState:
    """Read and write local upload records keyed by Immich device asset ID."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.records = self._load()

    def has(self, device_asset_id: str) -> bool:
        """Return whether a device asset ID has already been uploaded."""

        return device_asset_id in self.records

    def record(
        self, device_asset_id: str, asset_id: str, prepared_asset: PreparedAsset
    ) -> None:
        """Store one successful upload in local state."""

        self.records[device_asset_id] = {
            "asset_id": asset_id,
            "chosen_path": str(prepared_asset.candidate.chosen_path),
            "prepared_path": str(prepared_asset.prepared_path),
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "album_added": False,
            "tags_added": False,
        }

    def mark_album_added(self, device_asset_id: str) -> None:
        """Mark album assignment as completed for an uploaded asset."""

        self._update_followup_status(device_asset_id, "album_added")

    def mark_tags_added(self, device_asset_id: str) -> None:
        """Mark tag assignment as completed for an uploaded asset."""

        self._update_followup_status(device_asset_id, "tags_added")

    def save(self) -> None:
        """Persist local upload records to disk."""

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self.records, indent=2, sort_keys=True),
                encoding="utf-8",
            )
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
