from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class SteamScreenshot:
    app_id: str
    game_name: str | None
    normal_path: Path | None
    thumbnail_path: Path | None
    timestamp: datetime | None
    caption: str | None
    raw_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScreenshotCandidate:
    app_id: str
    game_name: str
    normal_path: Path
    uncompressed_path: Path | None
    chosen_path: Path
    timestamp: datetime | None
    caption: str | None


@dataclass
class SyncSummary:
    found: int = 0
    using_uncompressed: int = 0
    using_normal: int = 0
    uploaded: int = 0
    skipped: int = 0
    failed: int = 0
