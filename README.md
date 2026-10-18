# DebriPod

DebriPod is a local async media app for browsing, streaming, downloading, organizing, and playing media from your own computer. It opens in your browser at a local address, usually `http://127.0.0.1:8083`.

DebriPod supports local audio and video libraries, unified metadata and folder browsing, playlists, YouTube and YouTube Music, Soulseek, torrent discovery, multiple debrid providers, Last.fm, local accounts, passkeys, a first run setup wizard, task tracking, per user settings, SQLite backed library caches, cached client state, a PWA service worker, a liquid-glass UI built on [sfgl](https://github.com/JoeDoe56/sfgl), a WebGL visualizer, and optional MCP access.

## Quick install

The install scripts are also the update and launch scripts. Run the command from the folder where you want the `debripod` folder to be created.

### macOS and Linux

Open Terminal and run this command.

```sh
curl -fsSL https://raw.githubusercontent.com/JoeDoe56/Debripod/main/install/debripod.sh | sh
```

The script detects macOS or Linux. On macOS it uses Homebrew for Git, Python 3, ffmpeg, and ffprobe. On Linux it can install or refresh the required system tools through apt, dnf, yum, pacman, zypper, apk, xbps, Portage, Nix, or Linuxbrew. It then clones DebriPod into a case insensitive `debripod` folder, creates a virtual environment named `debripod`, installs Python dependencies, and starts the app on port `8083`.

### Windows

Open PowerShell and run this command.

```powershell
irm https://raw.githubusercontent.com/JoeDoe56/Debripod/main/install/debripod.ps1 | iex
```

If you prefer an explicit curl download, run this instead.

```powershell
curl.exe -fsSL https://raw.githubusercontent.com/JoeDoe56/Debripod/main/install/debripod.ps1 -o debripod.ps1; powershell -ExecutionPolicy Bypass -File .\debripod.ps1
```

The Windows script checks for winget, Git, Python 3, ffmpeg, and ffprobe. If winget is missing, install App Installer from Microsoft Store, close PowerShell, open it again, and rerun the command. If Git, Python, or ffmpeg are missing, the script installs them through winget. It then clones DebriPod into a case insensitive `debripod` folder, creates a virtual environment named `debripod`, installs Python dependencies, and starts the app on port `8083`.

Manual setup is documented in [manual_install.md](install/manual_install.MD).

## Running again and updating

Run the same install command again from the same parent folder.

If a `debripod` folder already exists, the script reuses it. The folder check is case insensitive, so `DebriPod`, `Debripod`, and `debripod` are treated as the same app folder.

On later runs, the script activates the existing virtual environment, checks GitHub for updates from `main`, and asks before pulling. Answer `y`, `yes`, `n`, or `no`. If you update, it pulls with `git pull --ff-only`, rechecks system dependencies, and reinstalls Python dependencies from `requirements.txt`. If there are no updates, it starts immediately.

The scripts do not delete or overwrite user data. Existing config files are left unchanged. Runtime data, users, logins, API keys, setup state, media folders, caches, indexes, playlists, downloads, task state, and local settings are preserved. If the repo has local tracked code changes, the scripts skip Git updates so custom edits are not overwritten.

## First run, setup wizard, and remote access

After the app starts, open this address.

```text
http://127.0.0.1:8083
```

On first run, DebriPod asks you to create the first local admin account. After login, the setup wizard guides the current user through a required library folder step, optional playback and YouTube tools, Soulseek and Last.fm, and Debrid. The required step is adding at least one library folder. Optional services can be skipped and configured later from Settings.

The optional tools page checks ffmpeg, ffprobe, and yt-dlp and lets you set the YouTube download folder. The Soulseek and Last.fm page covers Soulseek username, password, download folder, Last.fm API key, Last.fm API secret, and Last.fm authorization. The Debrid page supports Real Debrid, AllDebrid, Premiumize, and TorBox, with one active provider per user and one neutral Debrid download folder.

DebriPod binds to `127.0.0.1` by default. For access from phones, tablets, laptops, or devices outside the host computer, use a private tunnel or service layer instead of exposing the local server directly. Tailscale setup is documented in [remote_access.md](install/remote_access.md).

## Features and setup

### Local library

Every configured library folder is indexed and also available through its real directory tree. Unified Library views organize audio by tags such as artist, album, album artist, genre, track number, duration, codec, bitrate, bit depth, and sample rate, and organize videos into Movies, Shows, and Videos.

Add each folder that contains music, videos, downloads, or playlists during setup or later in Settings. Folder additions save immediately and are always indexed.

Supported audio formats include MP3, M4A, AAC, WAV, FLAC, OGG, OPUS, WMA, AIFF, and ALAC. Supported video formats include MP4, MKV, WEBM, MOV, M4V, AVI, TS, and M2TS. Supported playlist formats include M3U, M3U8, and PLS.

### Playback and browser compatibility

DebriPod streams media through aiohttp with range request support, so the browser can seek through audio and video. It saves playback state, current item, resume position, recent playback history, and queue context.

Enable **Preload next** in Playback settings to prepare the current and following audio track as decoded buffers. **Enable gapless playback**, immediately below it, schedules their boundaries on the same audio clock with no added silence or overlap. With gapless disabled, prepared transitions add 120 ms of silence. Turning preload off cancels preparation of the next track and disables the gapless setting. Initial preparation can take longer and uses memory proportional to the decoded current and next tracks; live streams and media the browser cannot decode use the regular streaming path. Silence already present in a source recording is preserved.

Playback history restores the last track, position, and queue edits for each listening session. Holding Menu to return to the library restores the original metadata or folder browsing path. Rapidly tap the performance-button area three times to reveal or hide it.

ffmpeg and ffprobe are used for metadata, artwork extraction, muxing, transcoding, HLS output, and browser compatible video output. If the installer configured them correctly, DebriPod should find them automatically. If not, set `FFMPEG_PATH` and `FFPROBE_PATH` in Playback settings. Keep automatic browser compatibility enabled if you want downloaded videos converted or remuxed when needed for browser playback.

### Search, downloads, and tasks

DebriPod searches the indexed Library, Local Index, remote torrent sources, Soulseek, and YouTube concurrently, then presents one globally ranked feed. Standard rows show identity and a smaller secondary line; source, quality, and other metadata remain available in the contextual information panel. The text filter row accepts ordinary terms plus `source:`, `type:`, `indexer:`, and `media:` filters; quote values containing spaces.

YouTube Music searches Songs, Music Videos, Albums, Artists, Music Playlists, Podcasts, and Episodes. Ordinary YouTube adds Videos, Playlists, and Channels. YouTube Music wins duplicate YouTube identities.

Local Index searches `data/torrent_index.sqlite`, a persistent WAL/FTS5 database merging Debrid Media Manager hashlists and top-level Torrents CSV rows by validated 20-byte infohash. Its automatic updater uses exact source commits and transactional add/modify/delete reconciliation. Expect approximately 0.5–1.0 GB for a low-single-digit-million corpus; Settings reports the actual database size, counts, source SHAs, and update status. Searches always use the last successful database state and never wait for an update.

Remote Torrent search uses exactly seven structured-data APIs: Knaben, BitSearch, Magnetz, TorLock, BT4G, TorrentClaw, and TorAPI. Their requests begin concurrently with Local Index, but remote rows merge only after Local Index seeds the shared infohash accumulator. A duplicate updates the existing row with current swarm, verification, magnet, URL, category, and provenance data instead of creating another result. Torrents CSV is an ingestion source only and is never queried interactively.

Long running work appears in the task panel. Debrid, Soulseek, YouTube, and video processing jobs can show queued, active, paused, failed, canceled, and completed states. Search history and completed combined search payloads are cached locally.

YouTube discovery and generic pasted-URL inspection use the `yt-dlp` CLI. Any HTTP(S) URL supported by yt-dlp, including a pasted `soundcloud.com` URL, can still be inspected directly. Set `YOUTUBE_DOWNLOAD_DIR` for generic yt-dlp downloads. Soulseek uses `aioslsk`; set `SOULSEEK_USERNAME`, `SOULSEEK_PASSWORD`, and `SOULSEEK_DOWNLOAD_DIR`. Saving changed credentials restarts the long-lived Soulseek client on the application event loop. Configure one supported debrid provider token, select it with `DEBRID_PROVIDER`, and set `DOWNLOAD_DIR` for torrent previews and downloads.

For every yt-dlp source, media selection shows available resolution choices and one Audio Only choice. These are quality targets: the server chooses streams, prefers compatible codecs at the selected resolution, and lets ffmpeg combine or extract streams without unnecessary re-encoding. Playback and downloads use the completed output path and validate stream presence, duration, and audio/video timing before accepting a file. Failed selections can retry an alternative within the requested resolution. Sources with incomplete quality metadata show a Best choice.

The normal tests are offline. To opt into live yt-dlp smoke tests, run with `DEBRIPOD_RUN_NETWORK_TESTS=1`. The loopback media integration test also runs without external network access when ffmpeg, ffprobe, and yt-dlp are installed; set `FFMPEG_PATH` and `FFPROBE_PATH` if the media tools are outside PATH.

### Playlists and smart playlists

Normal playlists are stored in a `DebriPod-Playlists` folder under a library root. Smart playlists are stored in `DebriPod-SmartPlaylists` and use rules to filter by liked status, artist, album artist, album, genre, and folder.

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

### Visualizer, glass, and client cache

The UI includes a WebGL visualizer, album art color extraction, liquid-glass surfaces drawn by the vendored sfgl engine (`static/vendor/sfgl`, refreshed with `Scripts/sync-sfgl.sh`), a wheel interface, selected row glass, a path pill, and a now playing control pill. Host Grotesk typography, shared circular indicators, and locally bundled SF Symbol glyphs give browsing and settings one visual system. Advanced Settings → Text controls base foreground opacity. Numeric adjustments temporarily reuse the control pill for the exact value and progress bar. Visualizer and glass settings are managed in the UI and stored locally.

The frontend is split into smaller modules for API access, client sync, library browsing, list rendering, the sfgl glass adapter, playback, media session handling, now playing UI, path pill behavior, passkeys, search tasks, settings, visualizer behavior, wheel controls, and performance overlay. DebriPod also includes a service worker and cached client mirror so common app state and library views can survive refreshes more cleanly.

### Last.fm

Last.fm support can send now playing updates, scrobble tracks, read loved track status, and love or unlove tracks from the UI. Set `LASTFM_API_KEY` and `LASTFM_API_SECRET`, then use the Last.fm connect flow in the UI. After authentication, DebriPod can cache the session locally.

### Accounts, passkeys, settings, and MCP

DebriPod uses local app accounts. The first account is created before the main app opens. User settings, service credentials, download paths, setup state, passkeys, playback state, search history, task ownership, and library folders are stored per user where practical.

Real secrets are stored in the operating-system keyring under the `DebriPod` service name. SQLite keeps only saved status, a stable keyring reference, update time, and nonsecret provider identity; settings responses and exports never return saved secret values. DebriPod fails closed if no secure keyring backend is available. Password login remains available. Passkeys use WebAuthn when the optional server package and the browser origin support it.

DebriPod includes optional MCP support. Enable it in Settings and restart DebriPod. Its token is stored in the operating-system keyring.

### Controls

| Input | Number | Lists | Now Playing | Seek Mode | Hold |
|---|---:|---|---|---|---|
| S or Enter | 1 | Interact with item | Enter Seek Mode | Commit seek, or exit Seek Mode when no seek occurred | Numeric keyboard entry while adjusting; wheel actions use the continuous pointer gesture below |
| W or Backspace | 2 | Back to previous screen | Back to the preceding special page or originating ordinary page | Toggle like status | Jump to the library list location of the current item |
| D | 3 | Next track | Next track | Skip forward | Open Queue |
| Space | 4 | Pause or play | Pause or play | Toggle shuffle | Open Now Playing |
| A | 5 | Previous track | Previous track | Skip back | Open History |
| Q or wheel backward | 6 | Scroll backward on list | Decrease volume | Seek backward | No hold action |
| E or wheel forward | 7 | Scroll forward on list | Increase volume | Seek forward | No hold action |

Outside Now Playing, pull from the right side of the wheel toward its center to reveal the information panel. Push from the center toward the right to dismiss it. Desktop right click on a row also opens its information panel. The panel reclaims list width and supports navigation, settings, search, and media rows.

Inside full Now Playing, pull from the left side toward the center to reveal LRCLIB lyrics over the artwork; reverse the gesture to dismiss them. Synchronized lyrics follow playback and seeking. Plain, instrumental, missing, and failed lookups have dedicated treatments.

Hold the wheel center for 320 ms, keep holding, and drag toward an action: top Like, bottom Add to Playlist, right Play Next, left Play After. Releasing commits the highlighted action; returning to the center before releasing cancels. Individual playable items and bounded collections support this mode; artists and navigation shortcuts do not. Collections apply to their members. Existing playlists are scoped to one library folder, so Add to Playlist is disabled for albums known to span multiple folders.

See [UI system notes](docs/ui-system.md) for shared primitives, quality normalization, and browser validation.

Special pages restore the exact ordinary view, selected row, and scroll position when closed.

### Task notifications

Choose **Enable task notifications** from Info. Permission is requested only from that action. Notifications are device scoped: a completed task notifies only the browser installation that created it. Choose **Disable task notifications** to revoke the current device subscription. Notification clicks open the exact task.

### Link intake and iOS Shortcut

Search accepts ordinary text, BitTorrent magnet links, and any HTTP(S) URL supported by yt-dlp. Install the [Send to DebriPod iOS Shortcut](https://www.icloud.com/shortcuts/9b20434f0f454145be37f680275f1a44) to send shared links or text directly to DebriPod. After installing it, edit the Shortcut's **Text** action and replace the example DebriPod address with the exact URL you normally use (including its protocol and port). Using the same address preserves the browser sign-in session.

## Repository layout

```text
debripod/
  __main__.py             package runner for python -m debripod
  app.py                  compatibility entry point
  config.py               startup state migration and runtime configuration helpers
  media_types.py          media extension and playlist constants
  paths.py                cache, art, and transcode path helpers
  runtime.py              app startup and runtime facade
  runtime_*.py            split runtime state, routes, and workers
  Library/                library index, metadata, and search helpers
  storage/                primary SQLite database, migrations, codecs, and repositories
  MCP/                    optional MCP HTTP and SSE route helpers
  Routes/                 modular aiohttp route groups
  Services/               unified search, Local Index, torrent API, Debrid, Soulseek, yt-dlp, and Last.fm helpers
  Tasks/                  task model and task manager helpers
  playback/               streaming, range responses, ffprobe, and command helpers
  static/                 static shell/auth pages, JS modules, vendored sfgl, visualizer, service worker, fonts
install/
  debripod.sh             macOS and Linux installer, updater, and launcher
  debripod.ps1            Windows installer, updater, and launcher
  manual_install.MD       manual setup guide
  remote_access.md        Tailscale remote access guide
requirements.txt          pinned Python dependencies
pyproject.toml            package metadata and console entry point
LICENSE                   project license summary
README.md                 project documentation
```

## Startup and port selection

DebriPod binds to `127.0.0.1`. Choose a port with `--port`, then `DEBRIPOD_PORT`; otherwise it uses `8083`.

```bash
python -m debripod --port 8083
```

Port selection does not create a JSON configuration file. Accounts, opaque server-side sessions, setup state, MCP saved status, and application settings are stored in the primary database. The MCP token is stored in the operating-system keyring. Older startup JSON is read once during migration, renamed with `.migrated.local`, and never recreated.

## Runtime data

DebriPod uses one primary database at `data/debripod.sqlite3` for nonsecret structured state: accounts and passkeys, settings and setup, playback, tasks, Last.fm loved tracks, Library indexes and metadata, search history/cache, packed palettes, and visualizer analysis. Normal operation uses SQLite WAL mode. Real secrets stay in the OS keyring.

Local torrent discovery uses a separate WAL database at `data/torrent_index.sqlite` plus temporary update state under `data/torrent_index_update/`. DMM archives and full CSV streams are temporary; the SQLite index is the permanent searchable representation. See [the search architecture](docs/search-architecture.md) for bootstrap, incremental update, recovery, transaction, and disk-budget details.

Static palettes store exactly three packed RGB bytes per color. Video palette timelines are sampled at 2 Hz, omit adjacent repeats, and store no contrast/UI roles. The browser shares one memoized palette utility for music and video contrast, roles, wheel text, and selected-pill colors, and interpolates neighboring video samples.

Large eligible BLOBs use a self-describing versioned `raw` or `zlib` envelope. Compression begins above 1 KiB and is retained only when it saves at least four percent. This is application-level value compression, not automatic SQLite table/page compression.

After a successful explicit full reindex, DebriPod removes stale media/cache rows, pauses enrichment writes, truncates the WAL, runs `PRAGMA optimize`, and runs `VACUUM` outside a transaction. The reindex status reports database bytes before and after maintenance; a maintenance failure does not discard the completed index.

These files should stay out of Git. Local configs, virtual environments, cache folders, media folders, logs, and runtime output should not be committed.

## Troubleshooting

### The app starts but the browser cannot open it

Make sure the terminal still says DebriPod is running. Then open this exact address.

```text
http://127.0.0.1:8083
```

If you selected another port with `--port` or `DEBRIPOD_PORT`, use that port instead.

### The installer says a command is still missing

Close the terminal, open a new one, and run the same install command again. Some system installers update PATH only for new terminal sessions.

### ffmpeg or ffprobe is missing

Check that the commands work in a fresh terminal.

```bash
ffmpeg -version
ffprobe -version
```

If they do not work, rerun the installer, install ffmpeg manually, or set full executable paths in Playback settings. Some Linux distributions require an extra multimedia repository before ffmpeg can be installed through the default package manager.

### Python cannot import aiohttp or another dependency

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

### Debrid downloads do not start

Confirm one supported provider token is set, that `DEBRID_PROVIDER` names that provider, and that the provider account is active. Try another torrent because not every release is cached or available through every debrid provider.

### YouTube streaming or downloading fails

Update yt-dlp inside the virtual environment.

```bash
python -m pip install --upgrade yt-dlp
```

Then restart DebriPod.

### Remote access does not work

Confirm DebriPod opens locally first. Then check Tailscale status, Tailscale Serve status, the Services page in the Tailscale admin console, and the access policy grants. Follow [remote_access.md](install/remote_access.md) for the complete setup.

## Security notes

DebriPod is designed as a local app and binds to `127.0.0.1`. Do not expose it directly to the public internet.

Keep `data/`, downloaded media folders, migration backups, and logs out of Git because they may contain usernames, paths, or personal media information. Back up `data/debripod.sqlite3` only after stopping DebriPod or after a successful WAL checkpoint. Back up keyring entries separately using operating-system tooling. Restore both the database and matching keyring entries while DebriPod is stopped.

Use a strong admin password. Keep API tokens private. Rotate tokens if they are ever pasted into an issue, screenshot, commit, or chat.

## Dependencies

Pinned Python dependencies are listed in `requirements.txt`.

```text
aiohttp==3.14.1
aioslsk==1.6.3
yt-dlp==2026.8.19
webauthn==2.8.0
keyring==25.7.0
pywebpush==2.3.0
```

DebriPod also expects `ffmpeg` and `ffprobe` for the complete media experience.

## Licensing and attributions

DebriPod is licensed as `GPL-3.0-or-later`. See [LICENSE](LICENSE).

This project should be treated as GPL compatible when distributed with the current Soulseek integration because `aioslsk` is licensed under GNU General Public License v3 or later. Do not add a noncommercial restriction to the normal GPL build. GPL licensed distributions must allow commercial use under the GPL terms.

Attributions for direct runtime dependencies:

| Component | Purpose in DebriPod | License |
| --- | --- | --- |
| aiohttp | Async local web server and shared HTTP client | Apache 2.0 |
| aioslsk | Soulseek client integration | GPL 3.0 or later |
| yt-dlp | YouTube searching, streaming support, and downloads | Unlicense |
| webauthn | Passkey and WebAuthn support | BSD 3 Clause |
| keyring | Operating-system secret storage | MIT |
| pywebpush | Device-scoped Web Push notifications | MIT |
| ffmpeg and ffprobe | Metadata, muxing, transcoding, and compatibility checks | License depends on the installed build |

DebriPod interacts with external services including YouTube, user-pasted yt-dlp sites, Soulseek, configured public torrent sources, Real Debrid, AllDebrid, Premiumize, TorBox, and Last.fm. Users are responsible for following the terms of the services they enable and for only downloading or streaming media they are allowed to access.
