from pathlib import Path

from steam2immich import sync_service
from steam2immich.config import Config
from steam2immich.immich_client import ImmichClientError, UploadResult, build_device_asset_id
from steam2immich.models import ScreenshotCandidate, SyncSummary
from steam2immich.sync_service import _discover_candidates, _run_uploads, _upload_candidate, run_sync


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
    def __init__(self, local_ids: set[str] | None = None) -> None:
        self.local_ids = local_ids or set()
        self.records: list[tuple[str, str, ScreenshotCandidate]] = []
        self.album_added: list[str] = []
        self.tags_added: list[str] = []
        self.save_count = 0

    def has(self, device_asset_id: str) -> bool:
        return device_asset_id in self.local_ids

    def record(
        self, device_asset_id: str, asset_id: str, candidate: ScreenshotCandidate
    ) -> None:
        self.records.append((device_asset_id, asset_id, candidate))

    def save(self) -> None:
        self.save_count += 1

    def mark_album_added(self, device_asset_id: str) -> None:
        self.album_added.append(device_asset_id)

    def mark_tags_added(self, device_asset_id: str) -> None:
        self.tags_added.append(device_asset_id)


class FakeImmichClient:
    def __init__(
        self,
        upload_results: list[UploadResult] | None = None,
        version_error: ImmichClientError | None = None,
    ) -> None:
        self.upload_results = upload_results or []
        self.version_error = version_error
        self.version_checked = False
        self.uploaded_candidates: list[ScreenshotCandidate] = []

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
        return None

    def get_or_create_tag(self, name: str) -> str:
        return f"tag-{name}"

    def tag_asset(self, tag_id: str, asset_id: str) -> None:
        return None


def test_upload_candidate_skips_locally_recorded_asset(
    tmp_path, steam_root, candidate_factory, monkeypatch
) -> None:
    # Locally-recorded assets should skip before uploading the file.
    candidate = candidate_factory()
    device_asset_id = build_device_asset_id(candidate)
    summary = SyncSummary()
    upload_state = FakeUploadState({device_asset_id})
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
    assert upload_state.records[0][0] == device_asset_id
    assert upload_state.records[0][2] == candidate
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
    assert upload_state.records == [(device_asset_id, "asset-duplicate", candidate)]
    assert upload_state.album_added == [device_asset_id]
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
