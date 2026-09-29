# Changelog

All notable changes are documented here using Keep a Changelog categories.
Commits use Conventional Commits.

## [Unreleased]

### Added
- Lyrics over Now Playing artwork, with synchronized LRC highlighting, plain lyrics, instrumental and unavailable states, track-change cancellation, and seek-aware playback tracking.
- Same-origin LRCLIB lookup through the shared HTTP client, with cached exact recording lookup and conservative search matching.

### Tested
- Lyrics parsing, seeks, track changes, stale responses, plain/missing/instrumental states, error recovery, and API validation using offline JavaScript and Python tests.
