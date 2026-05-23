# steam2immich

Local Python tooling for discovering Steam screenshots and preparing a future
Immich upload flow.

Current status: dry-run discovery works. The script finds Steam screenshots,
parses Steam screenshot metadata, resolves game names, matches uncompressed
copies when available, logs progress to both console and a file, and prints a
summary. It does not upload to Immich yet.

## Requirements

- Python 3.12+

Install dependencies:

```bash
pip install -r requirements.txt
```

## Configuration

Configuration priority is:

1. CLI arguments
2. Environment variables
3. Defaults

Copy `.env.example` to `.env` and fill in values as needed.

Important environment variables:

```env
STEAM2IMMICH_STEAM_ROOT=C:\Program Files (x86)\Steam
STEAM2IMMICH_STEAM_USER_ID=
STEAM2IMMICH_UNCOMPRESSED_DIR=
STEAM2IMMICH_OUTPUT_DIR=workdir
STEAM2IMMICH_DRY_RUN=true
STEAM2IMMICH_LOG_LEVEL=INFO
```

`STEAM2IMMICH_STEAM_USER_ID` is required. The app exits with code `2` if it is
missing.

## Usage

Dry run with `.env` configuration:

```bash
python -m steam2immich.main --dry-run --log-level DEBUG
```

Dry run with explicit paths:

```bash
python -m steam2immich.main --dry-run --log-level DEBUG --steam-user-id <steam_user_id> --steam-root "<steam_root>" --uncompressed-dir "<screenshots_dir>"
```

Supported CLI arguments:

- `--dry-run`
- `--log-level <level>`
- `--album-mode single|per-game`
- `--steam-root <path>`
- `--steam-user-id <id>`
- `--uncompressed-dir <path>`
- `--output-dir <path>`

## What It Does Today

The scanner finds normal Steam screenshots on disk under:

```text
<steam-root>/userdata/<steam-user-id>/760/remote/*/screenshots/*
```

Supported extensions are `.jpg`, `.jpeg`, `.png`, and `.webp`.

The disk scan is the source of truth for which files currently exist. Steam's
`screenshots.vdf` is parsed as metadata only, from:

```text
<steam-root>/userdata/<steam-user-id>/760/screenshots.vdf
```

When available, VDF metadata enriches candidates with:

- Steam app id
- normal screenshot path
- thumbnail path
- creation timestamp
- caption or description fields if present
- raw Steam metadata for future use

Game names are resolved in this order:

1. local Steam shortcut names from `screenshots.vdf`
2. local `appmanifest_<appid>.acf` files from all Steam library folders
3. cached remote Steam Store lookups in `workdir/app_names_cache.json`
4. read-only remote Steam Store lookup
5. fallback name: `Steam App <appid>`

The matcher then builds screenshot candidates and prefers uncompressed copies
when configured. For example:

```text
normal:       20250306223527_1.jpg
uncompressed: 1086940_20250306223527_1.png
```

The uncompressed file is selected because its filename stem ends with the normal
file stem. If multiple uncompressed matches exist, the largest file is selected.

Dry run performs no uploads, no metadata writes, and no file copies.

Dry run also writes a CSV report under:

```text
workdir/reports/
```

The report lists each candidate's app id, game name, normal path,
uncompressed path, chosen path, timestamp, and caption. It is useful for
auditing what would be processed before the app starts copying files or
uploading to Immich.

## Logging

Logs are written to the console and to timestamped files under:

```text
workdir/logs/
```

Example:

```text
workdir/logs/steam2immich-20260523-162205.log
```

Run with `--log-level DEBUG` to see each candidate and chosen path.

## Progress So Far

Implemented:

- configuration loading from CLI, `.env`, and defaults
- standard logging plus file logs
- Steam normal screenshot discovery
- Steam `screenshots.vdf` metadata parsing
- local Steam library/app manifest game-name resolution
- remote Steam Store game-name fallback with a local cache
- app id extraction from Steam screenshot paths
- uncompressed screenshot matching
- candidate summaries for dry runs
- `.gitignore` for local secrets, virtualenvs, caches, logs, and generated workdir output

Not implemented yet:

- copying chosen files into `workdir`
- metadata writing
- Immich API upload
- album creation and assignment
- duplicate/idempotency handling

## Project Structure

```text
steam2immich/
  __init__.py
  main.py       CLI entrypoint and dry-run orchestration
  config.py     config dataclass, CLI args, env loading, defaults
  models.py     shared dataclasses
  logger.py     console and file logging setup
  scanner.py    normal Steam screenshot discovery
  matcher.py    uncompressed screenshot matching and candidate building
  vdf_parser.py Steam screenshots.vdf metadata parsing
  steam_apps.py Steam app name resolution
  report_writer.py dry-run CSV report writing
workdir/        generated runtime output, ignored except .gitkeep
```
