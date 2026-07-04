from pathlib import Path

from steam2immich import sync_service
from steam2immich.config import Config
from steam2immich.immich_client import ImmichClientError, UploadResult, build_device_asset_id
from steam2immich.immich_client import tag_names_for_candidate
from steam2immich.models import ScreenshotCandidate, SyncSummary
from steam2immich.sync_service import (
    _add_tags,
    _discover_candidates,
    _run_uploads,
    _upload_candidate,
    run_sync,
)


def _config(tmp_path, steam_root: Path, **overrides) -> Config:
    values = {
        "immich_base_url": "",
        "immich_api_key": "",
        "steam_root": steam_root,
        "steam_user_id": "test-user",
        "steam_uncompressed_dir": None,
        "output_dir": tmp_path,
        "app_names_overrides_path": tmp_path / "app_names_overrides.json",
        "dry_run": True,
        "album_mode": "single",
        "single_album_name": "Steam Screenshots",
        "album_prefix": "Steam -",
        "log_level": "INFO",
        "limit": None,
        "app_id_filter": None,
    }
    values.update(overrides)
    return Config(**values)


def test_run_sync_returns_error_when_steam_user_id_is_missing(tmp_path, steam_root) -> None:
    # The service should preserve the CLI error code for missing required Steam user IDs.
    config = _config(tmp_path, steam_root, steam_user_id="")

    assert run_sync(config) == 2


def test_run_sync_dry_run_writes_report(tmp_path, steam_root, capsys) -> None:
    # A dry run should complete without Immich credentials and write a CSV report.
    config = _config(tmp_path, steam_root, dry_run=True)

    assert run_sync(config) == 0

    reports = list((tmp_path / "reports").glob("steam2immich-report-*.csv"))
    assert len(reports) == 1
    assert "Summary" in capsys.readouterr().out


def test_run_sync_upload_requires_immich_config(tmp_path, steam_root) -> None:
    # Non-dry-run uploads should keep returning code 2 when Immich credentials are missing.
    config = _config(tmp_path, steam_root, dry_run=False)

    assert run_sync(config) == 2


def test_run_sync_validates_immich_before_discovery(tmp_path, steam_root, monkeypatch) -> None:
    # Non-dry-run sync should verify Immich v3 before doing Steam discovery work.
    fake_client = FakeImmichClient()
    monkeypatch.setattr(sync_service, "ImmichClient", lambda *_args: fake_client)
    monkeypatch.setattr(
        sync_service,
        "_discover_candidates",
        lambda *_args: ([], SyncSummary()),
    )

    def fake_run_uploads(*_args) -> int:
        assert fake_client.version_checked is True
        return 0

    monkeypatch.setattr(sync_service, "_run_uploads", fake_run_uploads)

    config = _config(
        tmp_path,
        steam_root,
        dry_run=False,
        immich_base_url="https://immich.example",
        immich_api_key="key",
    )

    assert run_sync(config) == 0
    assert fake_client.version_checked is True


def test_run_sync_returns_error_for_non_v3_immich(
    tmp_path, steam_root, monkeypatch
) -> None:
    # Unsupported Immich versions should fail closed before discovery.
    fake_client = FakeImmichClient(version_error=ImmichClientError("requires Immich v3"))
    monkeypatch.setattr(sync_service, "ImmichClient", lambda *_args: fake_client)
    monkeypatch.setattr(
        sync_service,
        "_discover_candidates",
        lambda *_args: (_ for _ in ()).throw(AssertionError("should not discover")),
    )

    config = _config(
        tmp_path,
        steam_root,
        dry_run=False,
        immich_base_url="https://immich.example",
        immich_api_key="key",
    )

    assert run_sync(config) == 2
    assert fake_client.version_checked is True


def test_discover_candidates_applies_app_id_and_limit_filters(tmp_path, steam_root) -> None:
    # Discovery should apply the configured app ID and limit filters before summarizing.
    config = _config(tmp_path, steam_root, app_id_filter="1086940", limit=1)

    candidates, summary = _discover_candidates(config)

    assert len(candidates) == 1
    assert candidates[0].app_id == "1086940"
    assert summary.found == 1


class FakeUploadState:
    def __init__(self, records: dict[str, dict] | None = None) -> None:
        self.records = records or {}
        self.record_calls: list[tuple[str, str, ScreenshotCandidate]] = []
        self.album_added: list[str] = []
        self.tags_added: list[str] = []
        self.errors: list[tuple[str, str]] = []
        self.save_count = 0

    def has(self, device_asset_id: str) -> bool:
        return device_asset_id in self.records

    def get_record(self, device_asset_id: str) -> dict | None:
        return self.records.get(device_asset_id)

    def get_asset_id(self, device_asset_id: str) -> str | None:
        record = self.get_record(device_asset_id)
        if record is None:
            return None
        asset_id = record.get("asset_id")
        return str(asset_id) if asset_id else None

    def record(
        self,
        device_asset_id: str,
        asset_id: str,
        candidate: ScreenshotCandidate,
        album_name: str | None = None,
        tag_names: list[str] | None = None,
    ) -> None:
        self.record_calls.append((device_asset_id, asset_id, candidate))
        self.records[device_asset_id] = {
            "asset_id": asset_id,
            "chosen_path": str(candidate.chosen_path),
            "album_name": album_name,
            "album_added": False,
            "tag_names": tag_names or [],
            "tags_added": False,
        }

    def prepare_followups(
        self, device_asset_id: str, album_name: str, tag_names: list[str]
    ) -> None:
        record = self.records.get(device_asset_id)
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
        record = self.records.get(device_asset_id)
        return (
            record is not None
            and record.get("asset_id") is not None
            and record.get("album_name") == album_name
            and record.get("tag_names") == tag_names
            and record.get("album_added") is True
            and record.get("tags_added") is True
        )

    def needs_album(self, device_asset_id: str) -> bool:
        record = self.records.get(device_asset_id)
        return record is not None and record.get("album_added") is not True

    def needs_tags(self, device_asset_id: str) -> bool:
        record = self.records.get(device_asset_id)
        return record is not None and record.get("tags_added") is not True

    def save(self) -> None:
        self.save_count += 1

    def mark_album_added(self, device_asset_id: str) -> None:
        self.album_added.append(device_asset_id)
        self.records[device_asset_id]["album_added"] = True

    def mark_tags_added(self, device_asset_id: str) -> None:
        self.tags_added.append(device_asset_id)
        self.records[device_asset_id]["tags_added"] = True

    def record_error(self, device_asset_id: str, message: str) -> None:
        self.errors.append((device_asset_id, message))
        self.records.setdefault(device_asset_id, {})["last_error"] = message


class FakeImmichClient:
    def __init__(
        self,
        upload_results: list[UploadResult] | None = None,
        version_error: ImmichClientError | None = None,
        album_error: ImmichClientError | None = None,
        tag_error: ImmichClientError | None = None,
    ) -> None:
        self.upload_results = upload_results or []
        self.version_error = version_error
        self.album_error = album_error
        self.tag_error = tag_error
        self.version_checked = False
        self.uploaded_candidates: list[ScreenshotCandidate] = []
        self.added_albums: list[tuple[str, str]] = []
        self.tags: dict[str, str] = {}
        self.created_tags: list[str] = []
        self.tagged_assets: list[tuple[str, str]] = []

    def require_v3(self) -> None:
        self.version_checked = True
        if self.version_error is not None:
            raise self.version_error

    def upload_asset(
        self, candidate: ScreenshotCandidate, device_asset_id: str
    ) -> UploadResult:
        self.uploaded_candidates.append(candidate)
        if self.upload_results:
            return self.upload_results.pop(0)
        return UploadResult(f"asset-{len(self.uploaded_candidates)}")

    def get_or_create_album(self, name: str) -> str:
        return "album-id"

    def add_asset_to_album(self, album_id: str, asset_id: str) -> None:
        if self.album_error is not None:
            raise self.album_error
        self.added_albums.append((album_id, asset_id))

    def get_tag(self, name: str) -> str | None:
        return self.tags.get(name)

    def create_tag(self, name: str) -> str:
        self.created_tags.append(name)
        self.tags[name] = f"tag-{name}"
        return f"tag-{name}"

    def tag_asset(self, tag_id: str, asset_id: str) -> None:
        if self.tag_error is not None:
            raise self.tag_error
        self.tagged_assets.append((tag_id, asset_id))


def test_upload_candidate_skips_completed_locally_recorded_asset(
    tmp_path, steam_root, candidate_factory, monkeypatch
) -> None:
    # Fully completed local records should skip upload and follow-ups.
    candidate = candidate_factory()
    device_asset_id = build_device_asset_id(candidate)
    summary = SyncSummary()
    upload_state = FakeUploadState(
        {
            device_asset_id: {
                "asset_id": "asset-existing",
                "album_name": "Steam Screenshots",
                "album_added": True,
                "tag_names": tag_names_for_candidate(candidate),
                "tags_added": True,
            }
        }
    )
    immich_client = FakeImmichClient()

    _upload_candidate(
        candidate,
        device_asset_id,
        _config(tmp_path, steam_root),
        summary,
        immich_client,
        upload_state,
    )

    assert summary.skipped == 1
    assert immich_client.uploaded_candidates == []
    assert immich_client.added_albums == []
    assert immich_client.tagged_assets == []


def test_upload_candidate_uploads_when_not_known_locally(
    tmp_path, steam_root, candidate_factory, monkeypatch
) -> None:
    # New assets should upload from the selected source, record, album, and tag.
    candidate = candidate_factory()
    device_asset_id = build_device_asset_id(candidate)
    summary = SyncSummary()
    upload_state = FakeUploadState()
    immich_client = FakeImmichClient()

    _upload_candidate(
        candidate,
        device_asset_id,
        _config(tmp_path, steam_root),
        summary,
        immich_client,
        upload_state,
    )

    assert summary.uploaded == 1
    assert immich_client.uploaded_candidates == [candidate]
    assert upload_state.record_calls[0][0] == device_asset_id
    assert upload_state.record_calls[0][2] == candidate
    assert upload_state.records[device_asset_id]["asset_id"] == "asset-1"
    assert upload_state.records[device_asset_id]["album_name"] == "Steam Screenshots"
    assert upload_state.records[device_asset_id]["tag_names"] == tag_names_for_candidate(candidate)
    assert upload_state.album_added == [device_asset_id]
    assert upload_state.tags_added == [device_asset_id]
    assert not (tmp_path / "prepared").exists()


def test_upload_candidate_records_duplicate_upload_as_skipped(
    tmp_path, steam_root, candidate_factory, monkeypatch
) -> None:
    # Immich v3 reports duplicates from the upload response after receiving the asset.
    candidate = candidate_factory()
    device_asset_id = build_device_asset_id(candidate)
    summary = SyncSummary()
    upload_state = FakeUploadState()
    immich_client = FakeImmichClient([UploadResult("asset-duplicate", duplicate=True)])

    _upload_candidate(
        candidate,
        device_asset_id,
        _config(tmp_path, steam_root),
        summary,
        immich_client,
        upload_state,
    )

    assert summary.uploaded == 0
    assert summary.skipped == 1
    assert summary.failed == 0
    assert upload_state.record_calls == [(device_asset_id, "asset-duplicate", candidate)]
    assert upload_state.records[device_asset_id]["asset_id"] == "asset-duplicate"
    assert upload_state.album_added == [device_asset_id]
    assert upload_state.tags_added == [device_asset_id]


def test_upload_candidate_retries_missing_album_only(
    tmp_path, steam_root, candidate_factory
) -> None:
    # Existing uploads with incomplete album assignment should retry only album work.
    candidate = candidate_factory()
    device_asset_id = build_device_asset_id(candidate)
    upload_state = FakeUploadState(
        {
            device_asset_id: {
                "asset_id": "asset-existing",
                "album_name": "Steam Screenshots",
                "album_added": False,
                "tag_names": tag_names_for_candidate(candidate),
                "tags_added": True,
            }
        }
    )
    immich_client = FakeImmichClient()
    summary = SyncSummary()

    _upload_candidate(
        candidate,
        device_asset_id,
        _config(tmp_path, steam_root),
        summary,
        immich_client,
        upload_state,
    )

    assert summary.skipped == 1
    assert immich_client.uploaded_candidates == []
    assert immich_client.added_albums == [("album-id", "asset-existing")]
    assert immich_client.tagged_assets == []
    assert upload_state.records[device_asset_id]["album_added"] is True


def test_upload_candidate_retries_missing_tags_only(
    tmp_path, steam_root, candidate_factory
) -> None:
    # Existing uploads with incomplete tags should retry only tag work.
    candidate = candidate_factory()
    device_asset_id = build_device_asset_id(candidate)
    upload_state = FakeUploadState(
        {
            device_asset_id: {
                "asset_id": "asset-existing",
                "album_name": "Steam Screenshots",
                "album_added": True,
                "tag_names": tag_names_for_candidate(candidate),
                "tags_added": False,
            }
        }
    )
    immich_client = FakeImmichClient()
    summary = SyncSummary()

    _upload_candidate(
        candidate,
        device_asset_id,
        _config(tmp_path, steam_root),
        summary,
        immich_client,
        upload_state,
    )

    assert summary.skipped == 1
    assert immich_client.uploaded_candidates == []
    assert immich_client.added_albums == []
    assert len(immich_client.tagged_assets) == 3
    assert upload_state.records[device_asset_id]["tags_added"] is True


def test_upload_candidate_retries_when_album_name_changes(
    tmp_path, steam_root, candidate_factory
) -> None:
    # A target album change should reset and retry album assignment.
    candidate = candidate_factory()
    device_asset_id = build_device_asset_id(candidate)
    upload_state = FakeUploadState(
        {
            device_asset_id: {
                "asset_id": "asset-existing",
                "album_name": "Old Album",
                "album_added": True,
                "tag_names": tag_names_for_candidate(candidate),
                "tags_added": True,
            }
        }
    )
    immich_client = FakeImmichClient()
    summary = SyncSummary()

    _upload_candidate(
        candidate,
        device_asset_id,
        _config(tmp_path, steam_root),
        summary,
        immich_client,
        upload_state,
    )

    assert summary.skipped == 1
    assert upload_state.records[device_asset_id]["album_name"] == "Steam Screenshots"
    assert immich_client.added_albums == [("album-id", "asset-existing")]
    assert immich_client.tagged_assets == []


def test_upload_candidate_retries_when_tag_names_change(
    tmp_path, steam_root, candidate_factory
) -> None:
    # A desired tag change should reset and retry tag assignment.
    candidate = candidate_factory()
    device_asset_id = build_device_asset_id(candidate)
    upload_state = FakeUploadState(
        {
            device_asset_id: {
                "asset_id": "asset-existing",
                "album_name": "Steam Screenshots",
                "album_added": True,
                "tag_names": ["Steam"],
                "tags_added": True,
            }
        }
    )
    immich_client = FakeImmichClient()
    summary = SyncSummary()

    _upload_candidate(
        candidate,
        device_asset_id,
        _config(tmp_path, steam_root),
        summary,
        immich_client,
        upload_state,
    )

    assert summary.skipped == 1
    assert upload_state.records[device_asset_id]["tag_names"] == tag_names_for_candidate(candidate)
    assert immich_client.added_albums == []
    assert len(immich_client.tagged_assets) == 3


def test_upload_candidate_keeps_failed_followup_pending(
    tmp_path, steam_root, candidate_factory
) -> None:
    # Failed follow-ups should remain pending and record the error for next-run retry.
    candidate = candidate_factory()
    device_asset_id = build_device_asset_id(candidate)
    upload_state = FakeUploadState()
    immich_client = FakeImmichClient(album_error=ImmichClientError("album boom"))
    summary = SyncSummary()

    _upload_candidate(
        candidate,
        device_asset_id,
        _config(tmp_path, steam_root),
        summary,
        immich_client,
        upload_state,
    )

    assert summary.uploaded == 1
    assert upload_state.records[device_asset_id]["album_added"] is False
    assert upload_state.records[device_asset_id]["tags_added"] is True
    assert upload_state.records[device_asset_id]["last_error"] == "album: album boom"


def test_upload_candidate_does_not_reupload_malformed_local_record(
    tmp_path, steam_root, candidate_factory
) -> None:
    # Malformed local records should fail closed instead of risking a duplicate upload.
    candidate = candidate_factory()
    device_asset_id = build_device_asset_id(candidate)
    upload_state = FakeUploadState({device_asset_id: {"chosen_path": str(candidate.chosen_path)}})
    immich_client = FakeImmichClient()
    summary = SyncSummary()

    _upload_candidate(
        candidate,
        device_asset_id,
        _config(tmp_path, steam_root),
        summary,
        immich_client,
        upload_state,
    )

    assert summary.failed == 1
    assert immich_client.uploaded_candidates == []
    assert "missing Immich asset_id" in upload_state.records[device_asset_id]["last_error"]


def test_add_tags_reuses_existing_tags_without_creating(candidate_factory) -> None:
    # Existing Immich tags should be applied without duplicate create attempts.
    candidate = candidate_factory()
    device_asset_id = build_device_asset_id(candidate)
    upload_state = FakeUploadState(
        {
            device_asset_id: {
                "asset_id": "asset-id",
                "album_name": "Steam Screenshots",
                "album_added": True,
                "tag_names": tag_names_for_candidate(candidate),
                "tags_added": False,
            }
        }
    )
    immich_client = FakeImmichClient()
    immich_client.tags = {
        "Steam": "tag-steam",
        "Steam/Baldur's Gate 3": "tag-game",
        "Steam App/1086940": "tag-app",
    }

    _add_tags(
        immich_client,
        upload_state,
        device_asset_id,
        "asset-id",
        candidate,
    )

    assert immich_client.created_tags == []
    assert immich_client.tagged_assets == [
        ("tag-steam", "asset-id"),
        ("tag-game", "asset-id"),
        ("tag-app", "asset-id"),
    ]
    assert upload_state.tags_added == [device_asset_id]


def test_run_uploads_does_not_check_server_existing_assets(
    tmp_path, steam_root, candidate_factory, monkeypatch
) -> None:
    # Upload orchestration should rely on local state and v3 upload responses only.
    candidate = candidate_factory()
    fake_client = FakeImmichClient()
    monkeypatch.setattr(sync_service, "UploadState", lambda *_args: FakeUploadState())

    exit_code = _run_uploads(
        [candidate],
        _config(
            tmp_path,
            steam_root,
            dry_run=False,
            immich_base_url="https://immich.example",
            immich_api_key="key",
        ),
        SyncSummary(),
        fake_client,
    )

    assert exit_code == 0
    assert fake_client.uploaded_candidates == [candidate]
