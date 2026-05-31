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
    )


def test_default_app_names_overrides_path(monkeypatch) -> None:
    # Blank env values are ignored, so this verifies the project default path is used.
    monkeypatch.setenv("STEAM2IMMICH_APP_NAMES_OVERRIDES", "")

    config = load_config(_empty_args())

    assert config.app_names_overrides_path == Path("app_names_overrides.json")
