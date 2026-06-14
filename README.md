# DebriPod

DebriPod is a local Flask media app for browsing, streaming, downloading, organizing, and playing media from a personal library and external sources. It runs on your own computer and opens in a browser at a local address, usually `http://127.0.0.1:8083`.

DebriPod can scan local media folders, browse music by metadata, play audio and video, manage playlists, search YouTube, search Soulseek, search Knaben, download through Real Debrid, track long running jobs, and connect to Last.fm for scrobbling and loved tracks.

## What it does

### Local media library

DebriPod supports folder browsing and metadata browsing. Folder browsing shows your real directory tree. Metadata browsing builds music views from tags such as artist, album, album artist, genre, track number, duration, codec, bitrate, bit depth, and sample rate.

Supported audio formats include MP3, M4A, AAC, WAV, FLAC, OGG, OPUS, WMA, AIFF, and ALAC.

Supported video formats include MP4, MKV, WEBM, MOV, M4V, AVI, TS, and M2TS.

Supported playlist formats include M3U, M3U8, and PLS.

### Browser playback

DebriPod streams media through Flask with range request support, so the browser can seek through audio and video. It saves playback state locally, including the current item, resume position, and recent playback history.

The app can stream originals, use direct HTTP playback, and use ffmpeg or ffprobe for metadata, artwork extraction, muxing, transcoding, and browser compatible video output.

### Search and downloads

DebriPod combines YouTube, Soulseek, and Knaben results into one normalized search flow. The UI can stream or download YouTube results, group Soulseek results by user and folder, and send Knaben magnet results to Real Debrid.

Long running work appears in the task panel. Real Debrid downloads, Soulseek downloads, YouTube downloads, and video processing jobs can show queued, active, paused, failed, canceled, and completed states.

### Playlists

Normal playlists are stored in a `DebriPod-Playlists` folder under a library root. Smart playlists are stored in `DebriPod-SmartPlaylists` and use rules to filter by liked status, artist, album artist, album, genre, and folder.

### Last.fm

Last.fm support can send now playing updates, scrobble tracks, read loved track status, and love or unlove tracks from the UI. Last.fm credentials are optional.

### MCP

DebriPod includes optional MCP support. When enabled, it exposes selected app operations through a structured tool interface in addition to the browser UI.

## Repository layout

```text
debripod/
  __main__.py             package runner for python -m debripod
  app.py                  Flask app entry point
  config.py               startup config loader and secret redaction helpers
  media_types.py          media extensions and playlist constants
  paths.py                cache, art, and transcode path helpers
  runtime.py              app startup and runtime facade
  runtime_*.py            split runtime state, routes, and workers
  Library/                library root and search cache helpers
  MCP/                    MCP HTTP and SSE route helpers
  Routes/                 modular Flask route groups
  Services/               Real Debrid, Knaben, and Last.fm helpers
  Tasks/                  task model and task manager helpers
  playback/               streaming, range responses, ffprobe, and command helpers
config/
  debripod.example.json   safe startup config example
  debripod.local.json     local startup config, ignored by Git
data/
  settings.json           app settings created at runtime
requirements.txt          pinned Python dependencies
README.md                 project documentation
```

## Installation

These instructions assume you are starting from a fresh terminal and do not already have Python, Git, or ffmpeg installed.

### Windows

Open PowerShell.

Install Python, Git, and ffmpeg with winget.

```powershell
winget install Python.Python.3.14
```

```powershell
winget install Git.Git
```

```powershell
winget install Gyan.FFmpeg
```

Close PowerShell, then open PowerShell again so the new commands are available.

Choose a folder for the repo.

```powershell
cd $HOME
```

Clone the repo.

```powershell
git clone https://github.com/JoeDoe56/Debripod.git
```

Enter the repo.

```powershell
cd Debripod
```

Switch to the current working branch.

```powershell
git switch codex/testing1
```

Create the Python virtual environment.

```powershell
py -m venv .venv
```

Activate the virtual environment.

```powershell
.\.venv\Scripts\Activate.ps1
```

Upgrade pip.

```powershell
python -m pip install --upgrade pip
```

Install DebriPod dependencies.

```powershell
pip install -r requirements.txt
```

Create a local startup config.

```powershell
Copy-Item config\debripod.example.json config\debripod.local.json
```

Run DebriPod.

```powershell
python -m debripod
```

Open this address in your browser.

```text
http://127.0.0.1:8083
```

If PowerShell blocks activation, run this command once, then activate the virtual environment again.

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### macOS

Open Terminal.

Install the Xcode command line tools.

```zsh
xcode-select --install
```

Install Homebrew.

```zsh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Follow any Homebrew instructions printed at the end of the install. Then close Terminal and open it again.

Install Python, Git, and ffmpeg.

```zsh
brew install python
```

```zsh
brew install git
```

```zsh
brew install ffmpeg
```

Choose a folder for the repo.

```zsh
cd ~
```

Clone the repo.

```zsh
git clone https://github.com/JoeDoe56/Debripod.git
```

Enter the repo.

```zsh
cd Debripod
```

Switch to the current working branch.

```zsh
git switch codex/testing1
```

Create the Python virtual environment.

```zsh
python3 -m venv .venv
```

Activate the virtual environment.

```zsh
source .venv/bin/activate
```

Upgrade pip.

```zsh
python -m pip install --upgrade pip
```

Install DebriPod dependencies.

```zsh
pip install -r requirements.txt
```

Create a local startup config.

```zsh
cp config/debripod.example.json config/debripod.local.json
```

Run DebriPod.

```zsh
python -m debripod
```

Open this address in your browser.

```text
http://127.0.0.1:8083
```

### Linux

Open Terminal.

These commands are for Ubuntu, Debian, and Linux Mint. For Fedora, use `sudo dnf install python3 python3-pip git ffmpeg` instead of the apt install command.

Update the package list.

```bash
sudo apt update
```

Install Python, virtual environment support, Git, and ffmpeg.

```bash
sudo apt install python3 python3-venv python3-pip git ffmpeg
```

Choose a folder for the repo.

```bash
cd ~
```

Clone the repo.

```bash
git clone https://github.com/JoeDoe56/Debripod.git
```

Enter the repo.

```bash
cd Debripod
```

Switch to the current working branch.

```bash
git switch codex/testing1
```

Create the Python virtual environment.

```bash
python3 -m venv .venv
```

Activate the virtual environment.

```bash
source .venv/bin/activate
```

Upgrade pip.

```bash
python -m pip install --upgrade pip
```

Install DebriPod dependencies.

```bash
pip install -r requirements.txt
```

Create a local startup config.

```bash
cp config/debripod.example.json config/debripod.local.json
```

Run DebriPod.

```bash
python -m debripod
```

Open this address in your browser.

```text
http://127.0.0.1:8083
```

## Updating later

Open a terminal in the repo folder.

Activate the virtual environment.

Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS or Linux:

```bash
source .venv/bin/activate
```

Pull the latest branch changes.

```bash
git pull
```

Update dependencies.

```bash
pip install -r requirements.txt
```

Run the app again.

```bash
python -m debripod
```

## Startup config

DebriPod loads startup config from the first file it finds in this order.

1. The path in the `DEBRIPOD_CONFIG` environment variable.
2. `./config/debripod.local.json`
3. `./config/debripod.json`
4. `~/.config/debripod/config.json`

The example startup config is intentionally small.

```json
{
  "_HOST_NOTE": "DebriPod always binds to 127.0.0.1; only PORT is configurable.",
  "PORT": 8083,
  "USERS": [],
  "APP_SECRET_KEY": "",
  "ENABLE_MCP": false,
  "MCP_TOKEN": "",
  "SETUP_COMPLETE": false
}
```

On first run, DebriPod creates a secret key when needed and shows the local setup screen for the first admin user. Normal app settings and service credentials are managed after login from the Info panel and stored under `data/`.

DebriPod always binds to `127.0.0.1`. That keeps the app local to your computer unless you deliberately add a separate tunnel, proxy, or remote access layer.

## Feature setup guide

Start DebriPod, open `http://127.0.0.1:8083`, finish the first admin setup, then open the Info panel. Most features are configured from there.

### Local library

Open Info, then Library.

Add each folder that contains music, videos, downloads, or playlists.

Use `list` mode for folders where the real folder structure matters. This is the best choice for mixed downloads, video folders, unsorted files, and folders where you want DebriPod to behave like a file browser.

Use `meta` mode for organized music folders where artist, album, genre, track number, and liked status should drive browsing.

Save the library settings, then refresh or rescan from the UI if the library view does not update immediately.

### Playback tools

Open Info, then Playback.

For Windows, set `FFMPEG_PATH` and `FFPROBE_PATH` to the full paths for `ffmpeg.exe` and `ffprobe.exe` if DebriPod does not find them automatically. If winget installed ffmpeg correctly, the command names `ffmpeg` and `ffprobe` should usually work.

For macOS and Linux, leave the values as `ffmpeg` and `ffprobe` when those commands are installed on PATH.

Keep `AUTO_TRANSCODE_FOR_BROWSER_COMPATIBILITY` enabled if you want downloaded videos converted or remuxed when needed for browser playback.

Keep `REPLACE_ORIGINAL` enabled only if you want successful browser compatible output to replace the original download.

### YouTube

YouTube support uses yt-dlp, which is installed from `requirements.txt`.

Open Info, then Services or Playback.

Leave `YTDLP_CMD` as `yt-dlp` when the virtual environment is active and yt-dlp is installed normally.

Set `YOUTUBE_DOWNLOAD_DIR` to the folder where YouTube downloads should be saved.

Use the search UI to search YouTube, browse a channel when available, choose a format, stream the result, or start a download.

### Soulseek

Soulseek support uses `aioslsk`.

Open Info, then Services.

Set `SOULSEEK_USERNAME`.

Set `SOULSEEK_PASSWORD`.

Set `SOULSEEK_DOWNLOAD_DIR` to the folder where Soulseek downloads should be saved.

Keep `SOULSEEK_LISTENING_PORT` at the default unless you know you need a different port.

Restart DebriPod after adding or changing Soulseek credentials so the Soulseek client starts with the new settings.

After restart, use the search UI and choose Soulseek results. Downloads appear in the task panel.

### Real Debrid

Open your Real Debrid account page and create or copy an API token.

Open Info, then Services.

Set `REAL_DEBRID_API_KEY`.

Set `DOWNLOAD_DIR` to the folder where Real Debrid downloads should be saved.

Use Knaben search in DebriPod, open a torrent result, choose the files you want, and start the Real Debrid download. Real Debrid tasks track file progress, speed, output path, and failure state.

### Knaben

Knaben search can work without an API key when the public free tier is available.

Open Info, then Services.

Leave `KNABEN_API_KEY` blank unless you have a Knaben key.

Leave `KNABEN_API_BASE` as `https://api.knaben.org/v1` unless the API changes.

Use the search UI and choose Knaben as a source. Knaben results are mainly useful with Real Debrid enabled because torrent magnets can be sent to Real Debrid for caching and downloading.

### Last.fm

Create a Last.fm API account and get an API key plus API secret.

Open Info, then Services.

Set `LASTFM_API_KEY`.

Set `LASTFM_API_SECRET`.

Leave `LASTFM_SESSION_KEY` blank the first time unless you already have a valid session key.

Use the Last.fm connect flow in the UI. After authentication, DebriPod can cache the session locally.

When enabled, DebriPod can update now playing, scrobble tracks, check loved track status, and love or unlove tracks. Liked song views and liked smart playlist rules depend on this integration.

### MCP

Open `config/debripod.local.json`.

Set `ENABLE_MCP` to `true`.

If `MCP_TOKEN` is blank, DebriPod can generate one during startup.

Restart DebriPod.

Use MCP only on a local trusted machine unless you fully understand how the client will connect. The browser app still binds to `127.0.0.1`.

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

DebriPod writes runtime data to configured download folders and to local data and cache folders. Runtime files can include artwork cache, transcoded files, HLS output, ffmpeg logs, playback state, search history, search cache, Last.fm session data, task state, user settings, and downloaded media.

These files should stay out of Git. Local configs, virtual environments, cache folders, media folders, logs, and runtime output should not be committed.

## Troubleshooting

### The app starts but the browser cannot open it

Make sure the terminal still says DebriPod is running. Then open this exact address.

```text
http://127.0.0.1:8083
```

If you changed the port in `config/debripod.local.json`, use that port instead.

### ffmpeg or ffprobe is missing

Check that the commands work in a fresh terminal.

```bash
ffmpeg -version
```

```bash
ffprobe -version
```

If they do not work, install ffmpeg again or set the full executable paths in Info, then Playback.

### Python cannot import Flask or another dependency

Activate the virtual environment again and reinstall requirements.

Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS or Linux:

```bash
source .venv/bin/activate
```

Then run:

```bash
pip install -r requirements.txt
```

### Soulseek does not connect

Confirm the username and password are correct. Restart DebriPod after changing Soulseek settings. If your network blocks incoming connections, search may still work differently from downloads or browsing. Try a different listening port only if you know the current port is blocked or already in use.

### Real Debrid downloads do not start

Confirm `REAL_DEBRID_API_KEY` is set. Confirm your Real Debrid account is active. Try a different Knaben result because not every torrent will be cached or available.

### YouTube streaming or downloading fails

Update yt-dlp inside the virtual environment.

```bash
pip install --upgrade yt-dlp
```

Then restart DebriPod.

## Security notes

DebriPod is designed as a local app and binds to `127.0.0.1`. Do not expose it directly to the public internet.

Keep `config/debripod.local.json`, `data/`, downloaded media folders, and logs out of Git because they may contain usernames, API keys, session data, paths, or personal media information.

Use a strong admin password. Keep API tokens private. Rotate tokens if they are ever pasted into an issue, screenshot, commit, or chat.

## Dependencies

The pinned Python dependencies are listed in `requirements.txt`.

```text
Flask==3.1.3
requests==2.34.2
Pillow==12.2.0
aioslsk==1.6.3
yt-dlp==2026.6.9
```

DebriPod also expects `ffmpeg` and `ffprobe` to be installed for the complete media experience.

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
| ffmpeg and ffprobe | Metadata, muxing, transcoding, and compatibility checks | License depends on the installed build |

DebriPod interacts with external services including YouTube, Soulseek, Real Debrid, Knaben, and Last.fm. Users are responsible for following the terms of the services they enable and for only downloading or streaming media they are allowed to access.

## Development notes

The app runs through this package entry point.

```bash
python -m debripod
```

The package runner calls `debripod.app`, which imports the runtime app factory and main startup function. The runtime starts Flask on `127.0.0.1` with the configured port.

Keep startup settings in the startup config. Keep normal app settings in the UI after login. This separation keeps secrets and user specific runtime state away from the committed example config.
