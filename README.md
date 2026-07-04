# steam2immich

Local Python tool for importing Steam screenshots into Immich.

steam2immich discovers Steam screenshots, prefers uncompressed copies when
available, uploads the selected original files to Immich, adds them to albums,
and applies searchable Immich tags. Originals are opened read-only and never
modified.

## Features

- discovers normal Steam screenshots from disk
- prefers matching uncompressed screenshots when configured
- parses Steam `screenshots.vdf` for timestamps and metadata
- resolves game names from Steam manifests, cache, remote lookup, and manual overrides
- supports single-album and per-game album modes
- uploads selected original files directly to Immich
- applies Immich tags: `Steam`, `Steam/<game name>`, `Steam App/<app_id>`
- keeps local upload history in `workdir/upload_state.sqlite` to skip completed reruns
  and retry incomplete album/tag follow-ups
- writes dry-run CSV reports under `workdir/reports/`

## Requirements

- Python 3.12+
- Immich v3
- An Immich API key

Install for local CLI usage:

```bash
pip install -e .
```

For development and testing:

```bash
pip install -r requirements-dev.txt
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
STEAM2IMMICH_IMMICH_BASE_URL=
STEAM2IMMICH_IMMICH_API_KEY=
STEAM2IMMICH_OUTPUT_DIR=workdir
STEAM2IMMICH_APP_NAMES_OVERRIDES=app_names_overrides.json
STEAM2IMMICH_DRY_RUN=true
STEAM2IMMICH_AUDIT_STATE=false
STEAM2IMMICH_UPLOAD_WORKERS=1
STEAM2IMMICH_ALBUM_MODE=single
STEAM2IMMICH_SINGLE_ALBUM_NAME=Steam Screenshots
STEAM2IMMICH_ALBUM_PREFIX=Steam -
STEAM2IMMICH_LOG_LEVEL=INFO
```

`STEAM2IMMICH_STEAM_USER_ID` is required. Non-dry-run uploads also require
`STEAM2IMMICH_IMMICH_BASE_URL` and `STEAM2IMMICH_IMMICH_API_KEY`.
Non-dry-run uploads verify the Immich server version before discovery and stop
early unless the server reports Immich v3.

Required Immich API key permissions:

- `asset.upload`
- `album.read`
- `album.create`
- `albumAsset.create`
- `asset.read`
- `tag.read`
- `tag.create`
- `tag.asset`

## Usage

Dry-run the full library:

```bash
steam2immich --dry-run --log-level INFO
```

Preview one game and one screenshot:

```bash
steam2immich --dry-run --log-level INFO --app-id 1086940 --limit 1
```

Upload one screenshot as a first real test:

```bash
steam2immich --log-level INFO --app-id 1086940 --limit 1
```

Upload everything:

```bash
steam2immich --log-level INFO
```

Upload with parallel workers:

```bash
steam2immich --upload-workers 4 --log-level INFO
```

Audit local state before uploading:

```bash
steam2immich --audit-state --log-level INFO
```

The module entrypoint also remains available:

```bash
python -m steam2immich.main --dry-run --log-level INFO
```

Supported CLI arguments:

- `--dry-run`
- `--log-level <level>`
- `--album-mode single|per-game`
- `--steam-root <path>`
- `--steam-user-id <id>`
- `--uncompressed-dir <path>`
- `--output-dir <path>`
- `--app-names-overrides <path>`
- `--app-id <app_id>`
- `--limit <number>`
- `--audit-state`
- `--upload-workers <number>`

## How It Works

The scanner finds normal Steam screenshots on disk under:

```text
<steam-root>/userdata/<steam-user-id>/760/remote/*/screenshots/*
```

Supported extensions are `.jpg`, `.jpeg`, `.png`, and `.webp`.

The disk scan is the source of truth for files that currently exist. Steam's
`screenshots.vdf` is parsed as metadata only:

```text
<steam-root>/userdata/<steam-user-id>/760/screenshots.vdf
```

Game names are resolved in this order:

1. manual overrides from `app_names_overrides.json`
2. local Steam shortcut names from `screenshots.vdf`
3. local `appmanifest_<appid>.acf` files from all Steam library folders
4. cached remote Steam Store lookups in `workdir/app_names_cache.json`
5. read-only remote Steam Store lookup
6. fallback name: `Steam App <appid>`

Manual override format:

```json
{
  "17413424158355750912": "League of Legends",
  "14220631438574747648": "Yuzu"
}
```

Uncompressed screenshot matching handles Steam's app-id prefix:

```text
normal:       20250306223527_1.jpg
uncompressed: 1086940_20250306223527_1.png
```

If multiple uncompressed matches exist, the largest file is selected.

## Safety

Dry run performs no uploads and no file copies. It writes a CSV report under:

```text
workdir/reports/
```

Non-dry-run mode uploads the selected original file directly to Immich. Files are
opened read-only and are not copied or modified.

Local upload history is stored in:

```text
workdir/upload_state.sqlite
```

If a generated device asset ID already exists in that file, the app checks
whether upload, album assignment, and tag assignment are complete for the
current target album and tag set. Completed assets are skipped. Incomplete
album/tag follow-ups are retried on later runs without uploading the image
again.

Set `STEAM2IMMICH_AUDIT_STATE=true` or pass `--audit-state` to verify local
state against Immich before scanning Steam files. The audit removes records for
assets that no longer exist in Immich, marks missing album/tag follow-ups as
pending, and marks pending follow-ups complete when Immich already has them.

Set `STEAM2IMMICH_UPLOAD_WORKERS` or pass `--upload-workers` to upload multiple
new assets concurrently. The default is `1`. Start with a small value such as
`4`; very high values can overload Immich or the storage backing it.

## Logging

Logs are written to the console and timestamped files under:

```text
workdir/logs/
```

Use `--log-level DEBUG` to see each candidate and chosen path.

## Limitations

- duplicate checks are local-state only; server-side duplicate search is not implemented

## Project Structure

```text
steam2immich/
  __init__.py
  main.py       CLI entrypoint and orchestration
  config.py     config dataclass, CLI args, env loading, defaults
  models.py     shared dataclasses
  logger.py     console and file logging setup
  scanner.py    normal Steam screenshot discovery
  matcher.py    uncompressed screenshot matching and candidate building
  vdf_parser.py Steam screenshots.vdf metadata parsing
  steam_apps.py Steam app name resolution
  report_writer.py dry-run CSV report writing
  immich_client.py Immich upload, album, and tag API client
  upload_state.py local upload idempotency state
workdir/        generated runtime output, ignored except .gitkeep
app_names_overrides.json
                repo-owned app name overrides
```
