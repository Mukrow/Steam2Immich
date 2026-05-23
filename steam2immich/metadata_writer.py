"""Prepare upload copies and write best-effort image metadata.

This module is deliberately copy-first: Steam originals and uncompressed
originals are never modified. Metadata is written only to files under the
configured work directory.
"""

import hashlib
import logging
import shutil
from pathlib import Path

from .models import PreparedAsset, ScreenshotCandidate


try:
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
except ImportError:
    Image = None
    PngInfo = None


logger = logging.getLogger("steam2immich.metadata_writer")

# EXIF tag IDs used for the small set of JPEG metadata currently written.
# XP* tags are Windows Explorer-compatible UTF-16LE fields.
EXIF_IMAGE_DESCRIPTION = 270
EXIF_DATETIME = 306
EXIF_DATETIME_ORIGINAL = 36867
EXIF_DATETIME_DIGITIZED = 36868
EXIF_XP_TITLE = 40091
EXIF_XP_COMMENT = 40092
EXIF_XP_KEYWORDS = 40094


def prepare_upload_copy(candidate: ScreenshotCandidate, output_dir: Path) -> PreparedAsset:
    """Copy a candidate's chosen file into workdir and metadata-enrich the copy."""

    prepared_path = _prepared_path(candidate, output_dir)
    prepared_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate.chosen_path, prepared_path)

    metadata_written = write_metadata(prepared_path, candidate)
    return PreparedAsset(
        candidate=candidate,
        prepared_path=prepared_path,
        metadata_written=metadata_written,
    )


def write_metadata(path: Path, candidate: ScreenshotCandidate) -> bool:
    """Write supported metadata to a prepared copy, returning whether it succeeded."""

    if Image is None:
        logger.warning("Pillow is not installed; metadata was not written to %s", path)
        return False

    try:
        suffix = path.suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            return _write_jpeg_metadata(path, candidate)
        if suffix == ".png":
            return _write_png_metadata(path, candidate)

        logger.warning("Metadata writing is not supported for %s files: %s", suffix, path)
        return False
    except Exception as error:
        logger.warning("Could not write metadata to %s: %s", path, error)
        return False


def _prepared_path(candidate: ScreenshotCandidate, output_dir: Path) -> Path:
    """Build a destination path and avoid collisions with a stable source suffix."""

    base_path = output_dir / "prepared" / candidate.app_id / candidate.chosen_path.name
    if not base_path.exists():
        return base_path

    suffix = _source_suffix(candidate.chosen_path)
    return base_path.with_name(f"{base_path.stem}-{suffix}{base_path.suffix}")


def _write_jpeg_metadata(path: Path, candidate: ScreenshotCandidate) -> bool:
    """Write basic EXIF metadata into a JPEG prepared copy."""

    with Image.open(path) as image:
        exif = image.getexif()
        description = _description(candidate)

        if description:
            exif[EXIF_IMAGE_DESCRIPTION] = description
            exif[EXIF_XP_TITLE] = _xp_string(candidate.game_name)
            exif[EXIF_XP_COMMENT] = _xp_string(description)
            exif[EXIF_XP_KEYWORDS] = _xp_string(f"Steam;Steam App {candidate.app_id}")

        if candidate.timestamp:
            timestamp = candidate.timestamp.strftime("%Y:%m:%d %H:%M:%S")
            exif[EXIF_DATETIME] = timestamp
            exif[EXIF_DATETIME_ORIGINAL] = timestamp
            exif[EXIF_DATETIME_DIGITIZED] = timestamp

        image.save(path, exif=exif)

    return True


def _write_png_metadata(path: Path, candidate: ScreenshotCandidate) -> bool:
    """Write simple text metadata into a PNG prepared copy."""

    png_info = PngInfo()
    png_info.add_text("SteamAppID", candidate.app_id)
    png_info.add_text("GameName", candidate.game_name)

    if candidate.caption:
        png_info.add_text("Caption", candidate.caption)

    if candidate.timestamp:
        png_info.add_text("DateTimeOriginal", candidate.timestamp.isoformat())

    with Image.open(path) as image:
        image.save(path, pnginfo=png_info)

    return True


def _description(candidate: ScreenshotCandidate) -> str:
    """Build a human-readable description from game name and optional caption."""

    if candidate.caption:
        return f"{candidate.game_name}: {candidate.caption}"
    return candidate.game_name


def _xp_string(value: str) -> bytes:
    """Encode text for Windows XP* EXIF fields."""

    return value.encode("utf-16le") + b"\x00\x00"


def _source_suffix(path: Path) -> str:
    """Return a short stable hash suffix for collision-resistant filenames."""

    return hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:8]
