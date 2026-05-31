import logging
import sys

from .config import build_arg_parser, load_config
from .logger import setup_logging
from .sync_service import run_sync


logger = logging.getLogger("steam2immich")


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    config = load_config(args)
    log_path = setup_logging(config.log_level, config.output_dir / "logs")

    logger.debug("Loaded config: %s", _redacted_config(config))
    if log_path is not None:
        logger.info("Writing log file to %s", log_path)

    return run_sync(config)


def _redacted_config(config: object) -> dict[str, object]:
    values = vars(config).copy()
    if values.get("immich_api_key"):
        values["immich_api_key"] = "***"
    return values


if __name__ == "__main__":
    sys.exit(main())
