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
8. Replace `legacy.py` with a small app factory once all route registration has moved.

The facade modules already expose some common functions from `legacy.py`. That lets new code import from stable module names while the internal migration continues.
