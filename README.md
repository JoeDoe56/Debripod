# DebriPod

DebriPod is a local Flask media app for browsing, streaming, downloading, organizing, and playing media from a personal library and several external sources. It is built around a single web UI that acts like a desktop media center in the browser. The app can scan local folders, browse music by metadata, play audio and video, manage playlists, search YouTube, Soulseek, and Knaben, download through Real Debrid, track long running tasks, and connect to Last.fm for scrobbling and liked tracks.

DebriPod is meant to run locally on your own computer. It stores runtime files in local data and cache folders, keeps private credentials out of Git when configured correctly, and exposes a browser interface at the configured host and port.

## Main features

### Local media library

DebriPod can browse local folders as normal directories or as metadata indexed music libraries. Folder mode shows the actual folder tree and playable files. Metadata mode builds artist, album, genre, song, liked song, and video views from media tags.

Supported audio formats include MP3, M4A, AAC, WAV, FLAC, OGG, OPUS, WMA, AIFF, and ALAC. Supported video formats include MP4, MKV, WEBM, MOV, M4V, AVI, TS, and M2TS. Playlist support includes M3U, M3U8, and PLS.

Library roots are configured in `config/debripod.json` or `config/debripod.local.json`. Each root can use `list` mode for folder browsing or `meta` mode for metadata browsing.

### Browser playback

DebriPod streams media through Flask using range requests, so audio and video can seek in the browser. The player keeps server side playback state in the cache folder, including the current item, resume position, and recent playback history.

The app supports direct HTTP streaming and HLS style playback for compatible video paths. Audio files can be streamed as originals or transcoded during playback if configured. Video files can be checked with ffprobe and passed through ffmpeg when they need browser compatible output.

### Playlists and smart playlists

DebriPod creates normal playlists inside a `Debripod-Playlists` folder under a library root. These playlists are stored as M3U8 files and can be renamed, deleted, and updated from the UI.

Smart playlists live in `Debripod-SmartPlaylists`. Each smart playlist has a `rules.txt` file and a generated `playlist.m3u8` file. Rules can filter by liked status, artist, album artist, album, genre, and folder. Smart playlist rule groups can use any or all matching behavior.

### Search across online sources

The combined search API pulls together YouTube, Soulseek, and Knaben results into one normalized result list. Results are sorted and exposed to the UI with shared fields like title, source, size, quality, file count, stream availability, and browse availability.

Search history and search result cache are stored on disk. The UI can load previous searches and clear the search cache.

### YouTube support

DebriPod can search YouTube, browse channel uploads when a channel is available, list yt-dlp formats for a selected video, stream a selected format, and download selected formats into the configured YouTube download folder.

YouTube download and stream operations use yt-dlp. ffmpeg can be passed to yt-dlp through the configured ffmpeg path, which helps with muxing video and audio formats.

### Soulseek support

DebriPod can connect to Soulseek through aioslsk when a username and password are configured. It can search Soulseek, group results by user and directory, display file level metadata when available, browse a user’s shared files, and enqueue selected files for download.

Soulseek downloads use a task entry with per file state. The task view can show queued, downloading, paused, failed, incomplete, canceled, and complete states. Individual files can be paused, resumed, canceled, or retried.

### Real Debrid and Knaben support

DebriPod can search Knaben, load torrent file lists, send magnets to Real Debrid, select specific files from a torrent, wait for Real Debrid caching, and download the selected files locally.

Real Debrid tasks track each selected file separately. The app records file progress, speed, output path, and error state. Failed files can be retried without restarting the entire task.

### Task manager

Downloads and post processing jobs run as tracked tasks. The task manager exposes active and completed tasks through the UI and API. Tasks can be paused, resumed, canceled, cleared one at a time, or cleared all at once.

The task model supports Real Debrid, Soulseek, and YouTube tasks. It also tracks video post processing, including browser compatibility checks, transmuxing, transcoding, current file progress, and final completion state.

### Last.fm integration

DebriPod can connect to Last.fm for now playing updates, scrobbling, loved track status, and love or unlove actions. Last.fm credentials are optional. When enabled, the UI can show liked tracks and smart playlists can filter by liked status.

After authentication, the Last.fm session can be cached locally so the user does not have to paste a session key every time.

### Artwork and metadata

DebriPod reads media metadata with ffprobe. For audio, it can extract title, artist, album artist, album, genre, track number, duration, codec, bitrate, bit depth, and sample rate.

Artwork is selected from folder image files when available. Preferred filenames include cover, folder, front, and album. If no folder artwork exists, DebriPod can extract embedded artwork from audio files and cache it.

### Browser compatible video processing

DebriPod can check downloaded video files for browser compatibility. If a file is already compatible, it is left alone. If the container or codecs need adjustment, DebriPod can transmux or transcode to a browser friendly MP4 output.

When `AUTO_TRANSCODE_FOR_BROWSER_COMPATIBILITY` is enabled, video post processing runs after downloads. When `REPLACE_ORIGINAL` is enabled, successful browser compatible output can replace the original file.

### MCP support

DebriPod includes MCP session handling and tool style operations for searching and starting downloads. This allows the app logic to be exposed through a structured tool interface in addition to the browser UI.

## UI overview

DebriPod’s UI is a browser based media console designed around a persistent player and a library centered workflow.

The main library area lets you move through configured roots, switch between folder browsing and metadata browsing, and open music or video collections. In folder mode, the UI feels like a file browser with directories and playable media files. In metadata mode, it behaves more like a music app, with artist, album, song, genre, liked song, and video views.

The player area is built to stay useful while you browse. It can show the current track or video, playback state, artwork when available, metadata, technical quality details, and navigation context. Playback state is saved server side, so the app can restore the current item and recent history after a restart.

The search interface combines external sources into one view. YouTube results can be streamed or downloaded. Soulseek results appear grouped by user and shared directory, with file details like size, format, bitrate, bit depth, and sample rate when available. Knaben results can lead into Real Debrid file selection and downloading.

The task panel shows long running work without hiding the rest of the app. It is used for Real Debrid downloads, Soulseek downloads, YouTube downloads, and video processing. Tasks show overall status plus file level status, so you can see what is queued, active, paused, failed, completed, or canceled.

The visual design is meant to feel like a modern iPod style web app. The current configuration includes Liquid GL settings for the glass effect, a clear mode option, and a playback streaming mode option. The app also ships an embedded icon route so the UI can use a bundled app icon without depending on external assets.

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
  debripod.example.json   Full example config
  debripod.json           Safe default config when present
scripts/
  run.ps1                 Windows helper script
requirements.txt          Python dependencies
README.md                 Project documentation
```

## Requirements

DebriPod requires Python 3, Flask, requests, Pillow, aioslsk, and yt-dlp. ffmpeg and ffprobe are also required for metadata reading, artwork extraction, transcoding, muxing, and browser compatible video processing.

Install ffmpeg and make sure ffmpeg, ffprobe, and yt-dlp are available on PATH, or set their full paths in the config file.

## Setup on Windows

Create and activate a virtual environment:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Copy the example config if you want a fresh local config:

```powershell
Copy-Item config\debripod.example.json config\debripod.local.json
```

Edit `config/debripod.local.json` with your local folders, download paths, ffmpeg paths, and optional service credentials.

Run the app:

```powershell
python -m debripod
```

Then open the local address shown in the terminal. By default, the app uses:

```text
http://127.0.0.1:8083
```

## Configuration

DebriPod loads config from the first available source in this order:

1. The path set in `DEBRIPOD_CONFIG`
2. `./config/debripod.local.json`
3. `./config/debripod.json`
4. `~/.config/debripod/config.json`

The config file is JSON. See `config/debripod.example.json` for the full set of common settings.

Common settings include:

```json
{
  "HOST": "127.0.0.1",
  "PORT": 8083,
  "APP_NAME": "DebriPod",
  "LIQUID_GL_PRESET": "default",
  "LIQUID_GL_MODE": "clear",
  "PLAYBACK_STREAMING_MODE": "http",
  "DOWNLOAD_DIR": "./data/debrid",
  "SOULSEEK_DOWNLOAD_DIR": "./data/soulseek",
  "YOUTUBE_DOWNLOAD_DIR": "./data/youtube",
  "CACHE_DIR_NAME": "_debripod_cache",
  "FFMPEG_PATH": "ffmpeg",
  "FFPROBE_PATH": "ffprobe",
  "YTDLP_CMD": "yt-dlp",
  "REAL_DEBRID_API_KEY": "",
  "SOULSEEK_USERNAME": "",
  "SOULSEEK_PASSWORD": "",
  "LASTFM_API_KEY": "",
  "LASTFM_API_SECRET": "",
  "KNABEN_API_KEY": "",
  "LIBRARY_FOLDERS": [
    { "path": "./data/debrid", "mode": "list" },
    { "path": "./data/soulseek", "mode": "meta" },
    { "path": "./data/music", "mode": "meta" }
  ]
}
```

Keep real credentials in `config/debripod.local.json` or another ignored local config file. Do not commit personal tokens, account credentials, or private paths.

## Library folders

`LIBRARY_FOLDERS` controls what DebriPod shows in the library.

Use `list` mode when you want the UI to behave like a folder browser. This is useful for downloads, mixed media folders, and folders where the structure matters.

Use `meta` mode when you want DebriPod to build music views from metadata tags. This is useful for organized music folders where artist, album, genre, track number, and liked status should drive browsing.

## Playlists

Normal playlists are stored under `Debripod-Playlists` in a library root. Smart playlists are stored under `Debripod-SmartPlaylists`.

A smart playlist contains:

```text
rules.txt
playlist.m3u8
```

The default smart playlist rule format looks like this:

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

Remove the comment marker from rules you want to activate, then save the smart playlist rules from the UI.

## External services

### Real Debrid

Set `REAL_DEBRID_API_KEY` to enable Real Debrid downloading. DebriPod uses Real Debrid for magnet based downloads from Knaben results. The app can preview torrent files, select files, enqueue downloads, and save them into `DOWNLOAD_DIR`.

### Soulseek

Set `SOULSEEK_USERNAME` and `SOULSEEK_PASSWORD` to enable Soulseek. DebriPod starts the Soulseek client at app startup and keeps it connected. Search and download behavior can be tuned with the Soulseek timeout, max results, idle stop, hard max, and listening port settings.

### YouTube

YouTube support uses yt-dlp. DebriPod can search YouTube, browse channel videos, list formats, stream selected formats, and download selected formats. Set `YTDLP_CMD` if yt-dlp is not on PATH.

### Last.fm

Set `LASTFM_API_KEY` and `LASTFM_API_SECRET` to enable Last.fm authentication. After connecting, DebriPod can send now playing updates, scrobble tracks, and love or unlove tracks. Liked song views and liked smart playlist rules depend on this integration.

### Knaben

Knaben search works with the configured Knaben API settings. `KNABEN_API_KEY` is optional and can be left blank for free tier use when supported.

## Runtime data and cache

DebriPod writes runtime data to the configured download folders and cache folder. The cache can include artwork, transcoded files, HLS output, ffmpeg logs, playback state, search cache, Last.fm session data, and task state.

These files should usually stay out of Git. The repository `.gitignore` is set up to ignore virtual environments, cache folders, local media folders, local config variants, logs, and runtime output.

## Development notes

The app is currently in the middle of a refactor. `debripod/legacy.py` still contains most of the running application logic. New package directories and route or service modules exist so code can be moved out gradually without breaking imports all at once.

The current package entry point is:

```powershell
python -m debripod
```

`debripod/app.py` exposes `create_app()` for Flask style app loading, and `debripod/__main__.py` calls the same main function used by the direct package runner.

The original script had machine specific paths and credentials near the top. This packaged version removes those defaults from `debripod/runtime.py` and moves user specific values into JSON config. Keep `config/debripod.json` private when it contains real credentials.

DebriPod is intended to run as a local app. Keep `HOST` set to `127.0.0.1` unless you understand the security implications of exposing it to other devices.

Never commit real API keys, Real Debrid tokens, Soulseek credentials, Last.fm secrets, private paths, downloaded media, cache files, or local runtime files.

The remaining app runtime is in `debripod/runtime.py` so the app can keep running while route and worker code continue moving into modules.
