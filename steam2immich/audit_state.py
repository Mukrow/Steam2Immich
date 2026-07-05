"""Audit local upload state against Immich reality."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .immich_client import ImmichClient, ImmichClientError
from .upload_state import UploadState


logger = logging.getLogger("steam2immich.audit_state")


@dataclass
class AuditStateSummary:
    checked: int = 0
    removed_missing_assets: int = 0
    albums_marked_pending: int = 0
    albums_marked_complete: int = 0
    tags_marked_pending: int = 0
    tags_marked_complete: int = 0
    failed: int = 0


def audit_upload_state(
    upload_state: UploadState, immich_client: ImmichClient
) -> AuditStateSummary:
    """Reconcile local upload state with visible Immich asset state."""

    summary = AuditStateSummary()
    records = upload_state.records
    if not records:
        logger.info("Upload state audit skipped; no local records exist.")
        return summary

    logger.info("Auditing %d local upload state record(s) against Immich.", len(records))
    for device_asset_id, record in records.items():
        summary.checked += 1
        asset_id = record.get("asset_id")
        if not asset_id:
            upload_state.record_error(device_asset_id, "audit: missing local Immich asset_id")
            summary.failed += 1
            logger.warning(
                "Upload state audit found record without asset_id device_asset_id=%s",
                device_asset_id,
            )
            continue

        try:
            asset = immich_client.get_asset(str(asset_id))
            if asset is None:
                upload_state.forget(device_asset_id)
                summary.removed_missing_assets += 1
                logger.warning(
                    "Upload state audit forgot missing Immich asset device_asset_id=%s asset_id=%s",
                    device_asset_id,
                    asset_id,
                )
                continue

            _audit_album(
                upload_state,
                immich_client,
                summary,
                device_asset_id,
                str(asset_id),
                record,
            )
            _audit_tags(upload_state, immich_client, summary, device_asset_id, asset, record)
        except ImmichClientError as error:
            upload_state.record_error(device_asset_id, f"audit: {error}")
            summary.failed += 1
            logger.warning(
                "Upload state audit failed for device_asset_id=%s asset_id=%s: %s",
                device_asset_id,
                asset_id,
                error,
            )

    logger.info(
        "Upload state audit complete: checked=%d removed_missing_assets=%d "
        "albums_pending=%d albums_complete=%d tags_pending=%d tags_complete=%d failed=%d",
        summary.checked,
        summary.removed_missing_assets,
        summary.albums_marked_pending,
        summary.albums_marked_complete,
        summary.tags_marked_pending,
        summary.tags_marked_complete,
        summary.failed,
    )
    return summary


def _audit_album(
    upload_state: UploadState,
    immich_client: ImmichClient,
    summary: AuditStateSummary,
    device_asset_id: str,
    asset_id: str,
    record: dict,
) -> None:
    album_name = record.get("album_name")
    if not album_name:
        return

    has_album = immich_client.album_contains_asset(str(album_name), asset_id)
    if has_album and record.get("album_added") is not True:
        upload_state.mark_album_added(device_asset_id)
        summary.albums_marked_complete += 1
        return

    if not has_album and record.get("album_added") is True:
        upload_state.mark_album_pending(device_asset_id)
        upload_state.record_error(device_asset_id, f"audit: missing album {album_name}")
        summary.albums_marked_pending += 1


def _audit_tags(
    upload_state: UploadState,
    immich_client: ImmichClient,
    summary: AuditStateSummary,
    device_asset_id: str,
    asset: dict,
    record: dict,
) -> None:
    tag_names = record.get("tag_names") or []
    if not tag_names:
        return

    has_tags = immich_client.asset_has_tags(asset, [str(tag_name) for tag_name in tag_names])
    if has_tags and record.get("tags_added") is not True:
        upload_state.mark_tags_added(device_asset_id)
        summary.tags_marked_complete += 1
        return

    if not has_tags and record.get("tags_added") is True:
        upload_state.mark_tags_pending(device_asset_id)
        upload_state.record_error(device_asset_id, "audit: missing one or more tags")
        summary.tags_marked_pending += 1
