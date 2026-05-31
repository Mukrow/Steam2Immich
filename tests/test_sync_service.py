from pathlib import Path

from steam2immich.config import Config
from steam2immich.sync_service import _discover_candidates, run_sync


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
