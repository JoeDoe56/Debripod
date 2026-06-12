# Refactoring map

The app is packaged so it can run while the monolithic file is gradually split into modules.

Suggested extraction order:

1. Move config constants into `debripod/config.py` completely.
2. Move generic helpers into `debripod/utils.py`.
3. Move ffmpeg and range streaming helpers into `debripod/playback/`.
4. Move Real Debrid, Knaben, YouTube, Last.fm, and Soulseek code into `debripod/services/`.
5. Move task state and download workers into `debripod/tasks/`.
6. Move library indexing, playlists, smart playlists, and metadata into `debripod/library/`.
7. Move Flask routes into blueprints under `debripod/routes/`.
8. Split the remaining `runtime.py` routes/workers into focused modules, then reduce it to a small app factory.

The former `legacy.py` facades have been moved into modules. New code should import from the focused package modules instead of the app runtime.
