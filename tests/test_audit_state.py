from steam2immich.audit_state import audit_upload_state
from steam2immich.upload_state import UploadState


class FakeAuditImmichClient:
    def __init__(
        self,
        *,
        asset: dict | None = None,
        album_contains: bool = True,
    ) -> None:
        self.asset = asset
        self.album_contains = album_contains

    def get_asset(self, asset_id: str) -> dict | None:
        return self.asset

    def album_contains_asset(self, album_name: str, asset_id: str) -> bool:
        return self.album_contains

    def asset_has_tags(self, asset: dict, tag_names: list[str]) -> bool:
        actual_names = {tag["path"] for tag in asset.get("tags", [])}
        return set(tag_names).issubset(actual_names)


def test_audit_marks_pending_followups_complete_when_immich_has_them(
    tmp_path, candidate_factory
) -> None:
    state = UploadState(tmp_path / "upload_state.sqlite")
    state.record(
        "device-asset-id",
        "asset-id",
        candidate_factory(),
        "Steam Screenshots",
        ["Steam", "Steam/App"],
    )
    immich_client = FakeAuditImmichClient(
        asset={"id": "asset-id", "tags": [{"path": "Steam"}, {"path": "Steam/App"}]},
        album_contains=True,
    )

    summary = audit_upload_state(state, immich_client)

    record = state.records["device-asset-id"]
    assert record["album_added"] is True
    assert record["tags_added"] is True
    assert summary.albums_marked_complete == 1
    assert summary.tags_marked_complete == 1


def test_audit_marks_missing_followups_pending(tmp_path, candidate_factory) -> None:
    state = UploadState(tmp_path / "upload_state.sqlite")
    state.record(
        "device-asset-id",
        "asset-id",
        candidate_factory(),
        "Steam Screenshots",
        ["Steam", "Steam/App"],
    )
    state.mark_album_added("device-asset-id")
    state.mark_tags_added("device-asset-id")
    immich_client = FakeAuditImmichClient(
        asset={"id": "asset-id", "tags": [{"path": "Steam"}]},
        album_contains=False,
    )

    summary = audit_upload_state(state, immich_client)

    record = state.records["device-asset-id"]
    assert record["album_added"] is False
    assert record["tags_added"] is False
    assert record["last_error"] == "audit: missing one or more tags"
    assert summary.albums_marked_pending == 1
    assert summary.tags_marked_pending == 1


def test_audit_forgets_record_when_immich_asset_is_missing(
    tmp_path, candidate_factory
) -> None:
    state = UploadState(tmp_path / "upload_state.sqlite")
    state.record("device-asset-id", "asset-id", candidate_factory())
    immich_client = FakeAuditImmichClient(asset=None)

    summary = audit_upload_state(state, immich_client)

    assert state.records == {}
    assert summary.removed_missing_assets == 1
