# Debripod

Debripod is a local Flask media app for browsing a local library, searching external sources, downloading media, streaming files, managing playlists, and using integrations such as Real Debrid, Soulseek, YouTube via yt-dlp, and Last.fm.

This repository layout is designed so the app can be pushed to GitHub without committing a Python virtual environment or personal credentials.

## Repository layout

```text
debripod/
  app.py                 Application entry point
  config.py              Runtime JSON config loader
  runtime.py             Current working Debripod app runtime
  services/              Service import facades for gradual refactoring
  library/               Library and playlist import facades
  playback/              Playback and transcoding import facades
  tasks/                 Task manager import facades
config/
  debripod.json          Safe local default config with empty secrets
  debripod.example.json  Full example config for GitHub
scripts/
  run.ps1                Windows helper script
```

## Setup on Windows

Create and activate a virtual environment:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Install ffmpeg and make sure `ffmpeg`, `ffprobe`, and `yt-dlp` are available on PATH, or set their full paths in `config/debripod.json`.

Copy the example config if you want a fresh private config:

```powershell
Copy-Item config\debripod.example.json config\debripod.json
```

For private credentials, copy `config/debripod.example.json` to `config/debripod.local.json`, then edit that local file. The local config is ignored by Git. The committed `config/debripod.json` contains safe empty defaults.

Run the app:

```powershell
python -m debripod
```

Then open the address shown in the terminal, usually `http://127.0.0.1:8083`.

## Configuration

Debripod loads config in this order:

1. The path in `DEBRIPOD_CONFIG`
2. `./config/debripod.local.json`
3. `./config/debripod.json`
4. `~/.config/debripod/config.json`

The config file is JSON. See `config/debripod.example.json` for all common settings.

## GitHub safety notes

The original script had machine specific paths and credentials near the top. This packaged version removes those defaults from `debripod/runtime.py` and moves user specific values into JSON config. Keep `config/debripod.json` private when it contains real credentials.

The `.gitignore` file excludes virtual environments, caches, local media folders, logs, and common private config variants.

## Refactoring note

The remaining app runtime is in `debripod/runtime.py` so the app can keep running while route and worker code continue moving into modules.
