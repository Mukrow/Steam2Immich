import argparse
from pathlib import Path

from steam2immich.config import load_config


# Build parser-like CLI args with no user-supplied values so defaults are exercised.
def _empty_args() -> argparse.Namespace:
    return argparse.Namespace(
        immich_base_url=None,
        immich_api_key=None,
        steam_root=None,
        steam_user_id=None,
        uncompressed_dir=None,
        output_dir=None,
        app_names_overrides=None,
        dry_run=False,
        album_mode=None,
        log_level=None,
        limit=None,
        app_id=None,
        audit_state=False,
        upload_workers=None,
    )


def test_default_app_names_overrides_path(monkeypatch) -> None:
    # Blank env values are ignored, so this verifies the project default path is used.
    monkeypatch.setenv("STEAM2IMMICH_APP_NAMES_OVERRIDES", "")

    config = load_config(_empty_args())

    assert config.app_names_overrides_path == Path("app_names_overrides.json")


def test_env_app_names_overrides_path_beats_default(monkeypatch) -> None:
    # A non-empty env value should override the built-in app-name override path.
    monkeypatch.setenv("STEAM2IMMICH_APP_NAMES_OVERRIDES", "custom-overrides.json")

    config = load_config(_empty_args())

    assert config.app_names_overrides_path == Path("custom-overrides.json")


def test_cli_app_names_overrides_path_beats_env(monkeypatch) -> None:
    # A CLI value should win over the environment for the app-name override path.
    monkeypatch.setenv("STEAM2IMMICH_APP_NAMES_OVERRIDES", "env-overrides.json")
    args = _empty_args()
    args.app_names_overrides = "cli-overrides.json"

    config = load_config(args)

    assert config.app_names_overrides_path == Path("cli-overrides.json")


def test_unset_limit_is_none(monkeypatch) -> None:
    # A blank limit should be treated as unset rather than parsed as an integer.
    monkeypatch.setenv("STEAM2IMMICH_LIMIT", "")

    config = load_config(_empty_args())

    assert config.limit is None


def test_audit_state_can_be_enabled_from_env(monkeypatch) -> None:
    monkeypatch.setenv("STEAM2IMMICH_AUDIT_STATE", "true")

    config = load_config(_empty_args())

    assert config.audit_state is True


def test_cli_audit_state_beats_false_env(monkeypatch) -> None:
    monkeypatch.setenv("STEAM2IMMICH_AUDIT_STATE", "false")
    args = _empty_args()
    args.audit_state = True

    config = load_config(args)

    assert config.audit_state is True


def test_upload_workers_can_be_enabled_from_env(monkeypatch) -> None:
    monkeypatch.setenv("STEAM2IMMICH_UPLOAD_WORKERS", "4")

    config = load_config(_empty_args())

    assert config.upload_workers == 4


def test_cli_upload_workers_beats_env(monkeypatch) -> None:
    monkeypatch.setenv("STEAM2IMMICH_UPLOAD_WORKERS", "2")
    args = _empty_args()
    args.upload_workers = 6

    config = load_config(args)

    assert config.upload_workers == 6
