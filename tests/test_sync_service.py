from pathlib import Path

from steam2immich import sync_service
from steam2immich.config import Config
from steam2immich.immich_client import build_device_asset_id
from steam2immich.models import PreparedAsset, SyncSummary
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
        self.records: list[tuple[str, str, PreparedAsset]] = []
        self.album_added: list[str] = []
        self.tags_added: list[str] = []
        self.save_count = 0

    def has(self, device_asset_id: str) -> bool:
        return device_asset_id in self.local_ids

    def record(
        self, device_asset_id: str, asset_id: str, prepared_asset: PreparedAsset
    ) -> None:
        self.records.append((device_asset_id, asset_id, prepared_asset))

    def save(self) -> None:
        self.save_count += 1

    def mark_album_added(self, device_asset_id: str) -> None:
        self.album_added.append(device_asset_id)

    def mark_tags_added(self, device_asset_id: str) -> None:
        self.tags_added.append(device_asset_id)


class FakeImmichClient:
    def __init__(self, existing_ids: set[str] | None = None) -> None:
        self.existing_ids = existing_ids or set()
        self.checked_ids: list[str] = []
        self.uploaded_assets: list[PreparedAsset] = []

    def check_existing_assets(self, device_asset_ids: list[str]) -> set[str]:
        self.checked_ids = device_asset_ids
        return self.existing_ids

    def upload_asset(self, prepared_asset: PreparedAsset, device_asset_id: str) -> str:
        self.uploaded_assets.append(prepared_asset)
        return f"asset-{len(self.uploaded_assets)}"

    def get_or_create_album(self, name: str) -> str:
        return "album-id"

    def add_asset_to_album(self, album_id: str, asset_id: str) -> None:
        return None

    def get_or_create_tag(self, name: str) -> str:
        return f"tag-{name}"

    def tag_asset(self, tag_id: str, asset_id: str) -> None:
        return None


def test_upload_candidate_skips_server_existing_asset(
    tmp_path, steam_root, candidate_factory, monkeypatch
) -> None:
    # Server-existing assets should be skipped without preparing or uploading the file.
    candidate = candidate_factory()
    device_asset_id = build_device_asset_id(candidate)
    summary = SyncSummary()
    upload_state = FakeUploadState()
    immich_client = FakeImmichClient()
    monkeypatch.setattr(
        sync_service,
        "prepare_upload_copy",
        lambda *_args: (_ for _ in ()).throw(AssertionError("should not prepare")),
    )

    _upload_candidate(
        candidate,
        device_asset_id,
        {device_asset_id},
        _config(tmp_path, steam_root),
        summary,
        immich_client,
        upload_state,
    )

    assert summary.skipped == 1
    assert immich_client.uploaded_assets == []


def test_upload_candidate_prefers_local_skip_before_server_skip(
    tmp_path, steam_root, candidate_factory, monkeypatch
) -> None:
    # Locally-recorded assets should skip before server-existing state can trigger work.
    candidate = candidate_factory()
    device_asset_id = build_device_asset_id(candidate)
    summary = SyncSummary()
    upload_state = FakeUploadState({device_asset_id})
    immich_client = FakeImmichClient()
    monkeypatch.setattr(
        sync_service,
        "prepare_upload_copy",
        lambda *_args: (_ for _ in ()).throw(AssertionError("should not prepare")),
    )

    _upload_candidate(
        candidate,
        device_asset_id,
        {device_asset_id},
        _config(tmp_path, steam_root),
        summary,
        immich_client,
        upload_state,
    )

    assert summary.skipped == 1
    assert immich_client.uploaded_assets == []


def test_upload_candidate_uploads_when_not_known_locally_or_server_side(
    tmp_path, steam_root, candidate_factory, monkeypatch
) -> None:
    # New assets should still be prepared, uploaded, recorded, albumed, and tagged.
    candidate = candidate_factory()
    device_asset_id = build_device_asset_id(candidate)
    prepared_asset = PreparedAsset(candidate, tmp_path / "prepared.png", True)
    summary = SyncSummary()
    upload_state = FakeUploadState()
    immich_client = FakeImmichClient()
    monkeypatch.setattr(sync_service, "prepare_upload_copy", lambda *_args: prepared_asset)

    _upload_candidate(
        candidate,
        device_asset_id,
        set(),
        _config(tmp_path, steam_root),
        summary,
        immich_client,
        upload_state,
    )

    assert summary.uploaded == 1
    assert immich_client.uploaded_assets == [prepared_asset]
    assert upload_state.records[0][0] == device_asset_id
    assert upload_state.album_added == [device_asset_id]
    assert upload_state.tags_added == [device_asset_id]


def test_run_uploads_checks_server_before_uploading(
    tmp_path, steam_root, candidate_factory, monkeypatch
) -> None:
    # Upload orchestration should batch-check Immich for existing device asset IDs first.
    candidate = candidate_factory()
    fake_client = FakeImmichClient()
    monkeypatch.setattr(sync_service, "ImmichClient", lambda *_args: fake_client)
    monkeypatch.setattr(sync_service, "UploadState", lambda *_args: FakeUploadState())
    monkeypatch.setattr(
        sync_service,
        "prepare_upload_copy",
        lambda candidate, _output_dir: PreparedAsset(candidate, tmp_path / "prepared.png", True),
    )

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
    )

    assert exit_code == 0
    assert fake_client.checked_ids == [build_device_asset_id(candidate)]
