# Playback and collection regression checks

Cold audio starts do not wait for the next track to decode. If decoding the
current track takes more than 350 ms, playback uses the native streaming
element while the preload cache warms. On iOS, cold starts use native playback
immediately to preserve the initiating touch gesture. Prepared decoded tracks still use one
AudioContext clock for contiguous boundaries. Native streaming fallback cannot
promise a sample-accurate handoff before decoded playback takes over.

On iOS, decoded output is routed through a dedicated native audio sink using a
MediaStream destination, with a single audible output. Media Session actions
and position state use the application's playback clock. If the browser rejects
the native sink, output falls back to the AudioContext destination. Real-device
iOS lock-screen/PWA behavior still requires device verification.

The visualizer art cache version is 3. A smaller blur kernel retains local
brightness differences in mostly monochromatic covers; luma bounds are sampled
from that same cached image.

yt-dlp collections separate item selection from quality targets. Every selected
item retains its own source URL and download control ID; numbered output names
avoid collisions between duplicate titles. Missing requested resolutions use
available lower resolutions, with a progressive fallback for extractors that
omit dimensions. Audio-only items stay audio-only. Regular and smart library
playlists accept audio and video.

Debrid download failures refresh the provider link once when appropriate.
Invalid TLS certificates remain errors, with a clear explanation, rather than
disabling certificate verification. TorBox's download-presence flag determines
readiness, and a missing torrent cannot silently use another torrent's files.

Verification:

- `node --test tests/js/*.test.mjs`
- `python -m pytest -q` (set `FFMPEG_PATH` and `FFPROBE_PATH` for media integration)
- `node tests/browser/glass-ui.cjs`
- `node tests/browser/playlist-editor.cjs`
- `node tests/browser/playback-integration.cjs`
- `node tests/browser/playback-timeline.cjs`

Browser checks accept `PLAYWRIGHT_MODULE` and `BROWSER_CHANNEL` overrides.
