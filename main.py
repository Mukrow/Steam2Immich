import logging
import sys

from config import build_arg_parser, load_config
from logger import setup_logging
from matcher import build_screenshot_candidates
from models import SyncSummary
from scanner import find_normal_screenshots


logger = logging.getLogger("steam2immich")


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    config = load_config(args)
    log_path = setup_logging(config.log_level, config.output_dir / "logs")

    logger.debug("Loaded config: %s", _redacted_config(config))
    if log_path is not None:
        logger.info("Writing log file to %s", log_path)

    if not config.steam_user_id:
        logger.error(
            "Steam user ID is required. Set STEAM2IMMICH_STEAM_USER_ID or pass --steam-user-id."
        )
        return 2

    logger.info("Discovering normal Steam screenshots under %s", config.steam_root)
    screenshots = find_normal_screenshots(config.steam_root, config.steam_user_id)
    logger.info("Found %d normal Steam screenshot file(s).", len(screenshots))

    logger.info("Building screenshot candidates.")
    candidates = build_screenshot_candidates(
        screenshots, uncompressed_dir=config.steam_uncompressed_dir
    )
    using_uncompressed = sum(1 for candidate in candidates if candidate.uncompressed_path)
    summary = SyncSummary(
        found=len(candidates),
        using_uncompressed=using_uncompressed,
        using_normal=len(candidates) - using_uncompressed,
    )

    for candidate in candidates:
        logger.debug(
            "Screenshot candidate app_id=%s normal_path=%s uncompressed_path=%s chosen_path=%s",
            candidate.app_id,
            candidate.normal_path,
            candidate.uncompressed_path,
            candidate.chosen_path,
        )

    if config.dry_run:
        logger.info("Dry run enabled. No uploads or file changes will be performed.")

    logger.info("Discovered %d Steam screenshot(s).", summary.found)
    print_summary(summary)
    return 0


def print_summary(summary: SyncSummary) -> None:
    print("Summary")
    print(f"  Found: {summary.found}")
    print(f"  Using uncompressed: {summary.using_uncompressed}")
    print(f"  Using normal: {summary.using_normal}")
    print(f"  Uploaded: {summary.uploaded}")
    print(f"  Skipped: {summary.skipped}")
    print(f"  Failed: {summary.failed}")


def _redacted_config(config: object) -> dict[str, object]:
    values = vars(config).copy()
    if values.get("immich_api_key"):
        values["immich_api_key"] = "***"
    return values


if __name__ == "__main__":
    sys.exit(main())
