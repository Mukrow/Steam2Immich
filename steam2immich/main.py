import logging
import sys

from .config import build_arg_parser, load_config
from .immich_client import (
    ImmichClient,
    ImmichClientError,
    album_name_for_candidate,
    build_device_asset_id,
    tag_names_for_candidate,
)
from .logger import setup_logging
from .matcher import build_screenshot_candidates
from .metadata_writer import prepare_upload_copy
from .models import ScreenshotCandidate, SyncSummary
from .report_writer import write_dry_run_report
from .scanner import extract_app_id_from_path, find_normal_screenshots
from .steam_apps import resolve_app_names
from .upload_state import UploadState
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
    candidates = _filter_candidates(candidates, config.app_id_filter, config.limit)
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
        if not config.immich_base_url or not config.immich_api_key:
            logger.error(
                "Immich base URL and API key are required for non-dry-run uploads. "
                "Set STEAM2IMMICH_IMMICH_BASE_URL and STEAM2IMMICH_IMMICH_API_KEY."
            )
            return 2

        try:
            immich_client = ImmichClient(config.immich_base_url, config.immich_api_key)
        except ImmichClientError as error:
            logger.error("Could not initialize Immich client: %s", error)
            return 2

        upload_state = UploadState(config.output_dir / "upload_state.json")

        logger.info("Preparing upload copies under %s", config.output_dir / "prepared")
        for candidate in candidates:
            device_asset_id = build_device_asset_id(candidate)
            if upload_state.has(device_asset_id):
                summary.skipped += 1
                logger.debug(
                    "Skipping already-uploaded asset device_asset_id=%s path=%s",
                    device_asset_id,
                    candidate.chosen_path,
                )
                continue

            try:
                prepared_asset = prepare_upload_copy(candidate, config.output_dir)
                logger.debug(
                    "Prepared asset app_id=%s metadata_written=%s path=%s",
                    candidate.app_id,
                    prepared_asset.metadata_written,
                    prepared_asset.prepared_path,
                )

                asset_id = immich_client.upload_asset(prepared_asset, device_asset_id)
                upload_state.record(device_asset_id, asset_id, prepared_asset)
                upload_state.save()

                album_name = album_name_for_candidate(
                    candidate,
                    config.album_mode,
                    config.single_album_name,
                    config.album_prefix,
                )
                try:
                    album_id = immich_client.get_or_create_album(album_name)
                    immich_client.add_asset_to_album(album_id, asset_id)
                    upload_state.mark_album_added(device_asset_id)
                    upload_state.save()
                except ImmichClientError as error:
                    logger.warning(
                        "Uploaded asset %s, but could not add it to album %s: %s",
                        asset_id,
                        album_name,
                        error,
                    )

                try:
                    for tag_name in tag_names_for_candidate(candidate):
                        tag_id = immich_client.get_or_create_tag(tag_name)
                        immich_client.tag_asset(tag_id, asset_id)
                    upload_state.mark_tags_added(device_asset_id)
                    upload_state.save()
                except ImmichClientError as error:
                    logger.warning("Uploaded asset %s, but could not tag it: %s", asset_id, error)

                summary.uploaded += 1
                logger.info(
                    "Uploaded asset app_id=%s album=%s asset_id=%s",
                    candidate.app_id,
                    album_name,
                    asset_id,
                )
            except (OSError, ImmichClientError) as error:
                summary.failed += 1
                logger.warning("Could not upload %s: %s", candidate.chosen_path, error)

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


def _filter_candidates(
    candidates: list[ScreenshotCandidate], app_id: str | None, limit: int | None
) -> list[ScreenshotCandidate]:
    before = len(candidates)
    filtered = candidates

    if app_id:
        filtered = [candidate for candidate in filtered if candidate.app_id == app_id]

    if limit is not None:
        filtered = filtered[:limit]

    if app_id or limit is not None:
        logger.info(
            "Filtered candidates: before=%d after=%d app_id=%s limit=%s",
            before,
            len(filtered),
            app_id or "",
            limit or "",
        )

    return filtered


def _redacted_config(config: object) -> dict[str, object]:
    values = vars(config).copy()
    if values.get("immich_api_key"):
        values["immich_api_key"] = "***"
    return values


if __name__ == "__main__":
    sys.exit(main())
