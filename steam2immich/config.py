import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


ENV_PREFIX = "STEAM2IMMICH_"


@dataclass
class Config:
    immich_base_url: str
    immich_api_key: str
    steam_root: Path
    steam_user_id: str
    steam_uncompressed_dir: Path | None
    output_dir: Path
    dry_run: bool
    album_mode: str
    single_album_name: str
    album_prefix: str
    log_level: str


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Discover Steam screenshots for a future Immich upload flow."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level")
    parser.add_argument("--album-mode", choices=("single", "per-game"))
    parser.add_argument("--steam-root")
    parser.add_argument("--steam-user-id")
    parser.add_argument("--uncompressed-dir")
    parser.add_argument("--output-dir")
    return parser


def load_config(cli_args: argparse.Namespace | None = None) -> Config:
    if load_dotenv is not None:
        load_dotenv()

    if cli_args is None:
        cli_args = build_arg_parser().parse_args()

    return Config(
        immich_base_url=_get_value(cli_args, "immich_base_url", "IMMICH_BASE_URL", ""),
        immich_api_key=_get_value(cli_args, "immich_api_key", "IMMICH_API_KEY", ""),
        steam_root=Path(
            _get_value(cli_args, "steam_root", "STEAM_ROOT", str(_default_steam_root()))
        ).expanduser(),
        steam_user_id=_get_value(cli_args, "steam_user_id", "STEAM_USER_ID", ""),
        steam_uncompressed_dir=_get_optional_path(
            _get_value(cli_args, "uncompressed_dir", "UNCOMPRESSED_DIR", "")
        ),
        output_dir=Path(
            _get_value(cli_args, "output_dir", "OUTPUT_DIR", "workdir")
        ).expanduser(),
        dry_run=_get_bool(cli_args, "dry_run", "DRY_RUN", False),
        album_mode=_get_value(cli_args, "album_mode", "ALBUM_MODE", "single"),
        single_album_name=_get_value(
            cli_args, "single_album_name", "SINGLE_ALBUM_NAME", "Steam Screenshots"
        ),
        album_prefix=_get_value(cli_args, "album_prefix", "ALBUM_PREFIX", "Steam -"),
        log_level=_get_value(cli_args, "log_level", "LOG_LEVEL", "INFO"),
    )


def _get_value(
    cli_args: argparse.Namespace, cli_name: str, env_name: str, default: str
) -> str:
    cli_value = getattr(cli_args, cli_name, None)
    if cli_value not in (None, ""):
        return str(cli_value)

    env_value = os.getenv(f"{ENV_PREFIX}{env_name}")
    if env_value not in (None, ""):
        return env_value

    return default


def _get_bool(
    cli_args: argparse.Namespace, cli_name: str, env_name: str, default: bool
) -> bool:
    cli_value = getattr(cli_args, cli_name, None)
    if cli_value:
        return True

    env_value = os.getenv(f"{ENV_PREFIX}{env_name}")
    if env_value is None:
        return default

    return env_value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_optional_path(value: str) -> Path | None:
    if not value:
        return None
    return Path(value).expanduser()


def _default_steam_root() -> Path:
    if sys.platform.startswith("win"):
        return Path(r"C:\Program Files (x86)\Steam")
    return Path("~/.steam/steam").expanduser()
