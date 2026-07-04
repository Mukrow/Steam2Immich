"""SQLite idempotency state for uploaded Immich assets."""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import ScreenshotCandidate


logger = logging.getLogger("steam2immich.upload_state")

SCHEMA_VERSION = "1"


class UploadState:
    """Read and write local upload records keyed by Immich device asset ID."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self._initialize_schema()

    @property
    def records(self) -> dict[str, dict[str, Any]]:
        """Return a snapshot of all local upload records."""

        rows = self._connection.execute(
            """
            SELECT device_asset_id, asset_id, chosen_path, uploaded_at, album_name,
                   album_added, tag_names_json, tags_added, last_error, last_attempt_at
            FROM uploads
            ORDER BY device_asset_id
            """
        ).fetchall()
        return {str(row["device_asset_id"]): _row_to_record(row) for row in rows}

    def has(self, device_asset_id: str) -> bool:
        """Return whether a device asset ID has already been uploaded."""

        row = self._connection.execute(
            "SELECT 1 FROM uploads WHERE device_asset_id = ?",
            (device_asset_id,),
        ).fetchone()
        return row is not None

    def get_record(self, device_asset_id: str) -> dict[str, Any] | None:
        """Return one local upload record, if present."""

        row = self._connection.execute(
            """
            SELECT asset_id, chosen_path, uploaded_at, album_name, album_added,
                   tag_names_json, tags_added, last_error, last_attempt_at
            FROM uploads
            WHERE device_asset_id = ?
            """,
            (device_asset_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_record(row)

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

        self._connection.execute(
            """
            INSERT INTO uploads (
                device_asset_id, asset_id, chosen_path, uploaded_at, album_name,
                album_added, tag_names_json, tags_added, last_error, last_attempt_at
            )
            VALUES (?, ?, ?, ?, ?, 0, ?, 0, NULL, NULL)
            ON CONFLICT(device_asset_id) DO UPDATE SET
                asset_id = excluded.asset_id,
                chosen_path = excluded.chosen_path,
                uploaded_at = excluded.uploaded_at,
                album_name = excluded.album_name,
                album_added = 0,
                tag_names_json = excluded.tag_names_json,
                tags_added = 0,
                last_error = NULL,
                last_attempt_at = NULL
            """,
            (
                device_asset_id,
                asset_id,
                str(candidate.chosen_path),
                _now_iso(),
                album_name,
                json.dumps(tag_names or []),
            ),
        )
        self._connection.commit()

    def prepare_followups(
        self, device_asset_id: str, album_name: str, tag_names: list[str]
    ) -> None:
        """Update desired follow-up targets and reset stale completion flags."""

        record = self.get_record(device_asset_id)
        if record is None:
            return

        album_added = bool(record.get("album_added"))
        tags_added = bool(record.get("tags_added"))
        if record.get("album_name") != album_name:
            album_added = False

        if record.get("tag_names") != tag_names:
            tags_added = False

        self._connection.execute(
            """
            UPDATE uploads
            SET album_name = ?,
                album_added = ?,
                tag_names_json = ?,
                tags_added = ?
            WHERE device_asset_id = ?
            """,
            (
                album_name,
                int(album_added),
                json.dumps(tag_names),
                int(tags_added),
                device_asset_id,
            ),
        )
        self._connection.commit()

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

        self._connection.execute(
            """
            INSERT INTO uploads (device_asset_id, last_error, last_attempt_at)
            VALUES (?, ?, ?)
            ON CONFLICT(device_asset_id) DO UPDATE SET
                last_error = excluded.last_error,
                last_attempt_at = excluded.last_attempt_at
            """,
            (device_asset_id, message, _now_iso()),
        )
        self._connection.commit()

    def save(self) -> None:
        """Compatibility no-op; SQLite writes are committed per mutation."""

    def _initialize_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS state_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS uploads (
                device_asset_id TEXT PRIMARY KEY,
                asset_id TEXT,
                chosen_path TEXT,
                uploaded_at TEXT,
                album_name TEXT,
                album_added INTEGER NOT NULL DEFAULT 0,
                tag_names_json TEXT NOT NULL DEFAULT '[]',
                tags_added INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                last_attempt_at TEXT
            );
            """
        )
        self._connection.execute(
            """
            INSERT INTO state_metadata (key, value)
            VALUES ('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (SCHEMA_VERSION,),
        )
        self._connection.commit()

    def _update_followup_status(self, device_asset_id: str, key: str) -> None:
        """Update a boolean follow-up status field on an existing record."""

        if key not in {"album_added", "tags_added"}:
            raise ValueError(f"Unsupported follow-up status key: {key}")

        self._connection.execute(
            f"UPDATE uploads SET {key} = 1 WHERE device_asset_id = ?",
            (device_asset_id,),
        )
        record = self.get_record(device_asset_id)
        if (
            record is not None
            and record.get("album_added") is True
            and record.get("tags_added") is True
        ):
            self._connection.execute(
                """
                UPDATE uploads
                SET last_error = NULL,
                    last_attempt_at = NULL
                WHERE device_asset_id = ?
                """,
                (device_asset_id,),
            )
        self._connection.commit()


def _row_to_record(row: sqlite3.Row) -> dict[str, Any]:
    tag_names_json = row["tag_names_json"] or "[]"
    try:
        tag_names = json.loads(tag_names_json)
    except json.JSONDecodeError:
        logger.warning("Invalid tag_names_json in upload state: %s", tag_names_json)
        tag_names = []

    if not isinstance(tag_names, list):
        tag_names = []

    return {
        "asset_id": row["asset_id"],
        "chosen_path": row["chosen_path"],
        "uploaded_at": row["uploaded_at"],
        "album_name": row["album_name"],
        "album_added": bool(row["album_added"]),
        "tag_names": [str(tag_name) for tag_name in tag_names],
        "tags_added": bool(row["tags_added"]),
        "last_error": row["last_error"],
        "last_attempt_at": row["last_attempt_at"],
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
