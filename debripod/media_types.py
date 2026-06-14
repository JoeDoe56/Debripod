from __future__ import annotations

AUDIO_EXTS = {
    ".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".wma", ".aiff", ".alac",
}
VIDEO_EXTS = {
    ".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".ts", ".m2ts",
}
PLAYLIST_EXTS = {
    ".m3u", ".m3u8", ".pls",
}

PLAYLISTS_FOLDER_NAME = "DebriPod-Playlists"
SMART_PLAYLISTS_FOLDER_NAME = "DebriPod-SmartPlaylists"
SMART_PLAYLIST_RULES_FILENAME = "rules.txt"
SMART_PLAYLIST_MEDIA_FILENAME = "playlist.m3u8"

SMART_PLAYLIST_RULES_TEMPLATE = """[name]
[any|all]{
#liked=(\"true\"|\"false\")
#artist(is|not)=(\"artist 1\", \"artist 2\")
#albumartist(is|not)=(\"artist 1\", \"artist 2\")
#album(is|not)=(\"album 1\", \"album 2\")
#genre(is|not)=(\"genre 1\", \"genre 2\")
#folder(is|not)=(\"/dir1\", \"/dir2\")
}"""
