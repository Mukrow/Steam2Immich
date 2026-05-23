import logging
import sys

from .config import build_arg_parser, load_config
from .logger import setup_logging
from .matcher import build_screenshot_candidates
from .metadata_writer import prepare_upload_copy
from .models import SyncSummary
from .report_writer import write_dry_run_report
from .scanner import extract_app_id_from_path, find_normal_screenshots
from .steam_apps import resolve_app_names
from .vdf_parser import parse_screenshots_vdf, parse_shortcut_names


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

    logger.info("Parsing Steam screenshots.vdf metadata.")
    vdf_screenshots = parse_screenshots_vdf(config.steam_root, config.steam_user_id)
    logger.info("Parsed %d screenshot metadata entries from VDF.", len(vdf_screenshots))

    logger.info("Discovering normal Steam screenshots under %s", config.steam_root)
    screenshots = find_normal_screenshots(config.steam_root, config.steam_user_id)
    logger.info("Found %d normal Steam screenshot file(s).", len(screenshots))

    app_ids = {screenshot.app_id for screenshot in vdf_screenshots if screenshot.app_id}
    for screenshot in screenshots:
        app_id = extract_app_id_from_path(screenshot)
        if app_id:
            app_ids.add(app_id)

    logger.info("Resolving game names for %d Steam app id(s).", len(app_ids))
    app_name_resolution = resolve_app_names(
        app_ids=app_ids,
        steam_root=config.steam_root,
        cache_path=config.output_dir / "app_names_cache.json",
        overrides_path=config.app_names_overrides_path,
        shortcut_names=parse_shortcut_names(config.steam_root, config.steam_user_id),
    )
    logger.info(
        "Resolved game names: overrides=%d local=%d cache=%d remote=%d fallback=%d",
        app_name_resolution.override_hits,
        app_name_resolution.local_hits,
        app_name_resolution.cache_hits,
        app_name_resolution.remote_hits,
        app_name_resolution.fallbacks,
    )
    if app_name_resolution.unknown_app_ids:
        logger.warning(
            "Unknown Steam app ids: %s",
            ", ".join(app_name_resolution.unknown_app_ids),
        )

    logger.info("Building screenshot candidates.")
    candidates = build_screenshot_candidates(
        screenshots,
        uncompressed_dir=config.steam_uncompressed_dir,
        vdf_screenshots=vdf_screenshots,
        app_names=app_name_resolution.names,
    )
    using_uncompressed = sum(1 for candidate in candidates if candidate.uncompressed_path)
    summary = SyncSummary(
        found=len(candidates),
        using_uncompressed=using_uncompressed,
        using_normal=len(candidates) - using_uncompressed,
        app_ids_total=len(app_ids),
        app_ids_identified=len(app_ids) - app_name_resolution.fallbacks,
        app_ids_unknown=app_name_resolution.fallbacks,
    )

    for candidate in candidates:
        logger.debug(
            "Screenshot candidate app_id=%s game_name=%s timestamp=%s normal_path=%s uncompressed_path=%s chosen_path=%s",
            candidate.app_id,
            candidate.game_name,
            candidate.timestamp,
            candidate.normal_path,
            candidate.uncompressed_path,
            candidate.chosen_path,
        )

    if config.dry_run:
        logger.info("Dry run enabled. No uploads or file changes will be performed.")
        report_path = write_dry_run_report(candidates, config.output_dir / "reports")
        if report_path is not None:
            logger.info("Wrote dry-run report to %s", report_path)
    else:
        logger.info("Preparing upload copies under %s", config.output_dir / "prepared")
        logger.info("Immich upload is not implemented yet; no API calls will be made.")
        for candidate in candidates:
            try:
                prepared_asset = prepare_upload_copy(candidate, config.output_dir)
                logger.debug(
                    "Prepared asset app_id=%s metadata_written=%s path=%s",
                    candidate.app_id,
                    prepared_asset.metadata_written,
                    prepared_asset.prepared_path,
                )
            except OSError as error:
                summary.failed += 1
                logger.warning("Could not prepare upload copy for %s: %s", candidate.chosen_path, error)

    logger.info("Discovered %d Steam screenshot(s).", summary.found)
    print_summary(summary)
    return 0


def print_summary(summary: SyncSummary) -> None:
    print("Summary")
    print(f"  Found: {summary.found}")
    print(f"  Using uncompressed: {summary.using_uncompressed}")
    print(f"  Using normal: {summary.using_normal}")
    print(f"  App IDs total: {summary.app_ids_total}")
    print(f"  App IDs identified: {summary.app_ids_identified}")
    print(f"  App IDs unknown: {summary.app_ids_unknown}")
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
