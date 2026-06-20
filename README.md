# DebriPod

DebriPod is a local Flask media app for browsing, streaming, downloading, organizing, and playing media from your own computer. It opens in your browser at a local address, usually `http://127.0.0.1:8083`.

DebriPod supports local libraries, metadata browsing, audio and video playback, playlists, YouTube, Soulseek, Knaben, Real Debrid, Last.fm, a task panel, local accounts, a setup wizard, cached client state, and optional MCP support.

## Quick install

The install scripts are also the update and launch scripts. Run the command from the folder where you want the `debripod` folder to be created.

### macOS

Open Terminal and run this command.

```sh
curl -fsSL https://raw.githubusercontent.com/JoeDoe56/Debripod/main/install/debripod.sh | sh
```

The script checks for Homebrew, Git, Python 3, ffmpeg, and ffprobe. If Homebrew is missing, it asks before installing it. If Git, Python, or ffmpeg are missing, it installs them through Homebrew. It then clones DebriPod into a case insensitive `debripod` folder, creates a virtual environment named `debripod`, installs Python dependencies, and starts the app on port `8083`.

### Windows

Open PowerShell and run this command.

```powershell
irm https://raw.githubusercontent.com/JoeDoe56/Debripod/main/install/debripod.ps1 | iex
```

If you prefer an explicit curl download, run this instead.

```powershell
curl.exe -fsSL https://raw.githubusercontent.com/JoeDoe56/Debripod/main/install/debripod.ps1 -o debripod.ps1; powershell -ExecutionPolicy Bypass -File .\debripod.ps1
```

The script checks for winget, Git, Python 3, ffmpeg, and ffprobe. If winget is missing, install App Installer from Microsoft Store, close PowerShell, open it again, and rerun the command. If Git, Python, or ffmpeg are missing, the script installs them through winget. It then clones DebriPod into a case insensitive `debripod` folder, creates a virtual environment named `debripod`, installs Python dependencies, and starts the app on port `8083`.

## Running again and updating

Run the same install command again from the same parent folder.

If a `debripod` folder already exists, the script reuses it. The folder check is case insensitive, so `DebriPod`, `Debripod`, and `debripod` are treated as the same app folder.

On later runs, the script activates the existing virtual environment, checks GitHub for updates from `main`, and asks before pulling. Answer `y`, `yes`, `n`, or `no`. If you update, it pulls with `git pull --ff-only`, rechecks system dependencies, and reinstalls Python dependencies from `requirements.txt`. If there are no updates, it starts immediately.

The scripts do not delete or overwrite user data. Existing config files are left unchanged. Runtime data, users, logins, API keys, setup state, media folders, caches, indexes, playlists, downloads, task state, and local settings are preserved.

If the repo has local tracked code changes, the scripts skip Git updates so custom edits are not overwritten.

## First run and setup wizard

After the app starts, open this address.

```text
http://127.0.0.1:8083
```

On first run, DebriPod shows the setup wizard. Use it to create the first local admin user and configure optional services. You can skip optional services and add them later from the app settings.

The installer creates `config/debripod.local.json` only when no startup config exists. The generated file only sets the default port.

```json
{
  "PORT": 8083
}
```

DebriPod creates startup security values when needed, including the app secret key. The setup wizard is considered complete only after at least one user exists.

## Manual install

Use the quick install unless you need a manual development setup.

### Windows manual setup

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.12 -e
winget install --id Gyan.FFmpeg -e
```

Close PowerShell, open it again, then run:

```powershell
git clone https://github.com/JoeDoe56/Debripod.git debripod
cd debripod
py -3 -m venv --prompt debripod .debripod-venv
.\.debripod-venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -e .
python -m debripod.app
```

If PowerShell blocks activation, run this once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### macOS manual setup

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install git python ffmpeg
git clone https://github.com/JoeDoe56/Debripod.git debripod
cd debripod
python3 -m venv --prompt debripod .debripod-venv
. .debripod-venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -e .
python -m debripod.app
```

### Linux manual setup

DebriPod is developed primarily for Windows and macOS, but it can run on Linux with Python, Git, ffmpeg, and ffprobe installed.

Ubuntu, Debian, or Linux Mint:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip git ffmpeg
git clone https://github.com/JoeDoe56/Debripod.git debripod
cd debripod
python3 -m venv --prompt debripod .debripod-venv
. .debripod-venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -e .
python -m debripod.app
```

## Features

### Local library

DebriPod supports folder browsing and metadata browsing.

Folder browsing shows your real directory tree. It is best for mixed downloads, video folders, unsorted files, and folders where you want DebriPod to behave like a file browser.

Metadata browsing builds music views from tags such as artist, album, album artist, genre, track number, duration, codec, bitrate, bit depth, and sample rate.

Supported audio formats include MP3, M4A, AAC, WAV, FLAC, OGG, OPUS, WMA, AIFF, and ALAC.

Supported video formats include MP4, MKV, WEBM, MOV, M4V, AVI, TS, and M2TS.

Supported playlist formats include M3U, M3U8, and PLS.

### Playback

DebriPod streams media through Flask with range request support, so the browser can seek through audio and video. It saves playback state, current item, resume position, and recent playback history.

ffmpeg and ffprobe are used for metadata, artwork extraction, muxing, transcoding, HLS output, and browser compatible video output.

### Search and downloads

DebriPod combines YouTube, Soulseek, and Knaben results into one search flow. YouTube results can be streamed or downloaded. Soulseek results are grouped by user and folder. Knaben magnet results can be sent to Real Debrid.

Long running work appears in the task panel. Real Debrid downloads, Soulseek downloads, YouTube downloads, and video processing jobs can show queued, active, paused, failed, canceled, and completed states.

### Playlists

Normal playlists are stored in a `DebriPod-Playlists` folder under a library root. Smart playlists are stored in `DebriPod-SmartPlaylists` and use rules to filter by liked status, artist, album artist, album, genre, and folder.

### Visualizer and LiquidGL UI

The UI includes a WebGL visualizer, album art color extraction, LiquidGL glass surfaces, a wheel interface, selected row glass, list pills, a path pill, and a now playing pill. Visualizer and glass settings are managed in the UI and stored locally.

### Last.fm

Last.fm support can send now playing updates, scrobble tracks, read loved track status, and love or unlove tracks from the UI. Last.fm credentials are optional.

### Accounts and setup

DebriPod uses local app accounts. The first account is created in the setup wizard. Service credentials are stored locally for the current user and are redacted from exported settings unless you explicitly choose an export with secrets.

### MCP

DebriPod includes optional MCP support. When enabled in startup config, it exposes selected app operations through a structured tool interface in addition to the browser UI.

## Repository layout

```text
debripod/
  __main__.py             package runner for python -m debripod
  app.py                  Flask app entry point
  config.py               startup config loader and secret redaction helpers
  media_types.py          media extension and playlist constants
  paths.py                cache, art, and transcode path helpers
  runtime.py              app startup and runtime facade
  runtime_*.py            split runtime state, routes, and workers
  Library/                library index, SQLite cache, metadata, and search helpers
  MCP/                    optional MCP HTTP and SSE route helpers
  Routes/                 modular Flask route groups
  Services/               Real Debrid, Knaben, Soulseek, and Last.fm helpers
  Tasks/                  task model and task manager helpers
  playback/               streaming, range responses, ffprobe, and command helpers
  static/                 browser UI, modules, LiquidGL, visualizer, service worker, fonts
  templates/              Flask HTML templates
config/
  debripod.example.json   safe startup config example
  debripod.local.json     local startup config, ignored by Git
install/
  debripod.sh             macOS installer, updater, and launcher
  debripod.ps1            Windows installer, updater, and launcher
requirements.txt          pinned Python dependencies
pyproject.toml            package metadata and console entry point
README.md                 project documentation
```

## Startup config

DebriPod loads startup config from the first file it finds in this order.

1. The path in the `DEBRIPOD_CONFIG` environment variable.
2. `./config/debripod.local.json`.
3. `./config/debripod.json`.
4. `~/.config/debripod/config.json`.

Startup config is for early values needed before login, including `PORT`, local users, app secret key, setup state, MCP enablement, and MCP token.

Normal app settings and service credentials are managed after login through the app settings UI. This keeps user specific runtime state out of committed files.

DebriPod binds to `127.0.0.1`. That keeps the app local to your computer unless you deliberately add a tunnel, proxy, or remote access layer.

## Feature setup guide

Start DebriPod, open `http://127.0.0.1:8083`, finish the setup wizard, then open Settings or Info from the app.

### Local library

Add each folder that contains music, videos, downloads, or playlists.

Use `list` mode for folders where the real folder structure matters. Use `meta` mode for organized music folders where artist, album, genre, track number, and liked status should drive browsing.

### Playback tools

If the installer installed ffmpeg correctly, `ffmpeg` and `ffprobe` should be available automatically. If DebriPod does not find them, set `FFMPEG_PATH` and `FFPROBE_PATH` in Playback settings.

Keep automatic browser compatibility enabled if you want downloaded videos converted or remuxed when needed for browser playback.

### YouTube

YouTube support uses `yt-dlp`, installed from `requirements.txt`. Set `YOUTUBE_DOWNLOAD_DIR` to the folder where YouTube downloads should be saved.

### Soulseek

Soulseek support uses `aioslsk`. Set `SOULSEEK_USERNAME`, `SOULSEEK_PASSWORD`, and `SOULSEEK_DOWNLOAD_DIR`. Restart DebriPod after changing Soulseek credentials so the Soulseek client starts with the new settings.

### Real Debrid

Set `REAL_DEBRID_API_KEY` and `DOWNLOAD_DIR`. Use Knaben search to find torrent results, choose files, and send them to Real Debrid for downloading.

### Knaben

Knaben search can work without an API key when the public free tier is available. Leave `KNABEN_API_KEY` blank unless you have a Knaben key.

### Last.fm

Set `LASTFM_API_KEY` and `LASTFM_API_SECRET`, then use the Last.fm connect flow in the UI. After authentication, DebriPod can cache the session locally.

### MCP

Set `ENABLE_MCP` to `true` in startup config and restart DebriPod. If `MCP_TOKEN` is blank, DebriPod can generate one during startup.

## Smart playlist rules

A smart playlist contains this structure.

```text
rules.txt
playlist.m3u8
```

The rule format looks like this.

```text
[name]
[any|all]{
#liked=("true"|"false")
#artist(is|not)=("artist 1", "artist 2")
#albumartist(is|not)=("artist 1", "artist 2")
#album(is|not)=("album 1", "album 2")
#genre(is|not)=("genre 1", "genre 2")
#folder(is|not)=("/dir1", "/dir2")
}
```

Remove the `#` marker from rules you want to activate, then save the smart playlist from the UI.

## Runtime data

DebriPod writes runtime data to configured download folders and to local data and cache folders. Runtime files can include artwork cache, SQLite library indexes, visualizer analysis cache, transcoded files, HLS output, ffmpeg logs, playback state, search history, search cache, Last.fm session data, task state, user settings, user accounts, and downloaded media.

These files should stay out of Git. Local configs, virtual environments, cache folders, media folders, logs, and runtime output should not be committed.

## Troubleshooting

### The app starts but the browser cannot open it

Make sure the terminal still says DebriPod is running. Then open this exact address.

```text
http://127.0.0.1:8083
```

If you changed the port in `config/debripod.local.json`, use that port instead.

### The installer says a command is still missing

Close the terminal, open a new one, and run the same install command again. Some system installers update PATH only for new terminal sessions.

### ffmpeg or ffprobe is missing

Check that the commands work in a fresh terminal.

```bash
ffmpeg -version
ffprobe -version
```

If they do not work, rerun the installer, install ffmpeg manually, or set full executable paths in Playback settings.

### Python cannot import Flask or another dependency

Activate the DebriPod virtual environment and reinstall requirements.

Windows:

```powershell
.\.debripod-venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -e .
```

macOS or Linux:

```bash
. .debripod-venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e .
```

### Soulseek does not connect

Confirm the username and password are correct. Restart DebriPod after changing Soulseek settings. If your network blocks incoming connections, search may still work differently from downloads or browsing. Try a different listening port only if you know the current port is blocked or already in use.

### Real Debrid downloads do not start

Confirm `REAL_DEBRID_API_KEY` is set. Confirm your Real Debrid account is active. Try a different Knaben result because not every torrent will be cached or available.

### YouTube streaming or downloading fails

Update yt-dlp inside the virtual environment.

```bash
python -m pip install --upgrade yt-dlp
```

Then restart DebriPod.

## Security notes

DebriPod is designed as a local app and binds to `127.0.0.1`. Do not expose it directly to the public internet.

Keep `config/debripod.local.json`, `data/`, downloaded media folders, and logs out of Git because they may contain usernames, API keys, session data, paths, or personal media information.

Use a strong admin password. Keep API tokens private. Rotate tokens if they are ever pasted into an issue, screenshot, commit, or chat.

## Dependencies

Pinned Python dependencies are listed in `requirements.txt`.

```text
Flask==3.1.3
requests==2.34.2
Pillow==12.2.0
aioslsk==1.6.3
yt-dlp==2026.6.9
webauthn==2.8.0
watchdog==6.0.0
```

DebriPod also expects `ffmpeg` and `ffprobe` for the complete media experience.

## Licensing and attributions

This project should be treated as GPL compatible when distributed with the current Soulseek integration because `aioslsk` is licensed under GNU General Public License v3 or later.

Recommended project license for the current full build: `GPL-3.0-or-later`.

Do not add a noncommercial restriction to the normal GPL build. GPL licensed distributions must allow commercial use under the GPL terms. A separate private personal use policy can exist for your own unpublished copy, but public redistribution with `aioslsk` should follow GPL v3 or later.

Attributions for direct runtime dependencies:

| Component | Purpose in DebriPod | License |
| --- | --- | --- |
| Flask | Local web app framework | BSD 3 Clause |
| requests | HTTP requests for service APIs | Apache 2.0 |
| Pillow | Image and artwork handling | MIT CMU |
| aioslsk | Soulseek client integration | GPL 3.0 or later |
| yt-dlp | YouTube searching, streaming support, and downloads | Unlicense |
| webauthn | Passkey and WebAuthn support | BSD 3 Clause |
| watchdog | File watching support | Apache 2.0 |
| ffmpeg and ffprobe | Metadata, muxing, transcoding, and compatibility checks | License depends on the installed build |

DebriPod interacts with external services including YouTube, Soulseek, Real Debrid, Knaben, and Last.fm. Users are responsible for following the terms of the services they enable and for only downloading or streaming media they are allowed to access.

## Development notes

The app runs through this package entry point.

```bash
python -m debripod.app
```

The package also exposes the `debripod` console script when installed editable through `pyproject.toml`.

Keep startup settings in startup config. Keep normal app settings in the UI after login. This separation keeps secrets and user specific runtime state away from the committed example config.
