import csv
import logging
from datetime import datetime
from pathlib import Path

from .models import ScreenshotCandidate


logger = logging.getLogger("steam2immich.report_writer")


def write_dry_run_report(
    candidates: list[ScreenshotCandidate], reports_dir: Path
) -> Path | None:
    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = reports_dir / f"steam2immich-report-{datetime.now():%Y%m%d-%H%M%S}.csv"

        with report_path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=_fieldnames())
            writer.writeheader()
            for candidate in candidates:
                writer.writerow(_candidate_row(candidate))

        return report_path
    except OSError as error:
        logger.warning("Could not write dry-run report: %s", error)
        return None


def _fieldnames() -> list[str]:
    return [
        "app_id",
        "game_name",
        "normal_path",
        "uncompressed_path",
        "chosen_path",
        "using_uncompressed",
        "timestamp",
        "caption",
    ]


def _candidate_row(candidate: ScreenshotCandidate) -> dict[str, str | bool]:
    return {
        "app_id": candidate.app_id,
        "game_name": candidate.game_name,
        "normal_path": str(candidate.normal_path),
        "uncompressed_path": str(candidate.uncompressed_path or ""),
        "chosen_path": str(candidate.chosen_path),
        "using_uncompressed": candidate.uncompressed_path is not None,
        "timestamp": candidate.timestamp.isoformat() if candidate.timestamp else "",
        "caption": candidate.caption or "",
    }
