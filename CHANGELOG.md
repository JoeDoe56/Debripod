# Changelog

All notable changes are documented here using Keep a Changelog categories.
Commits use Conventional Commits.

## [Unreleased]

### Added
- Lyrics over Now Playing artwork, with synchronized LRC highlighting, plain lyrics, instrumental and unavailable states, track-change cancellation, and seek-aware playback tracking.
- Same-origin LRCLIB lookup through the shared HTTP client, with cached exact recording lookup and conservative search matching.
- Shared standard rows, normalized rounded rings, glyph-cutout activation circles, and adaptive metadata panels across browsing and settings.
- Explicit wheel gesture states for contextual panels, lyrics, and reversible hold-and-drag media actions.
- Local Host Grotesk fonts and a unified SF Symbols-style SVG registry, including the specified playback and heart variants.
- Tests for gestures, collection actions, metadata, numeric normalization, and iPhone 15 Pro Max browser dimensions.

### Changed
- Standard rows use one 55 px architecture with meaningful left indicators and primary/secondary text hierarchy.
- Panels reclaim approximately 30% of the screen width with shared safe-zone spacing and fading row text.
- Advanced Settings exposes Text Opacity; foreground emphasis derives from that value.
- Numeric settings share their range state with persistent rings and temporary exact-value feedback, including keyboard entry.
- Album actions resolve collection members; Like preserves existing likes until the whole collection is liked, and queue insertion preserves order.
- Lyrics use a fixed, feathered blur behind the text, smooth native scrolling, and opacity/transform transitions with reduced-motion support.
- Shared settings-row construction replaces duplicate builders, and offline shell caching includes the new fonts, symbols, and styles.

### Removed
- Persistent metadata/status pills on standard rows, double-height standard rows, the dedicated View Lyrics action, and the separate center-hold action screen.

### Fixed
- Lyrics browsing now preserves offscreen reading positions, recenters small scrolls, and supports seeking by click or keyboard. Full-height blur feathers toward the cover's midpoint, leaving right-side artwork taps available to pin playback pills.
- Short inward pulls from the Next Track region open the information panel without conflicting wheel scrolling.
- Selected row labels, secondary text, and indicators move together; default and migrated foreground opacity uses 40% normal and 80% emphasis.
- Neighboring row text retains glass refraction with synchronous native cutouts and cached text textures, avoiding repeatedly decoded SVG masks and clipped glyph edges.
- Replaced approximate symbol SVGs with the requested upstream SF Symbol glyphs, restored MENU text, and included imported assets in offline shell caching.
- Pointer capture handoffs, center-origin panel dismissal, action cancellation, and restoration of normal wheel icons.
- Numeric keyboard input and complete album submission through the playlist picker after the row redesign.
- Metadata units, zero-value counts, audio quality normalization, and video watch-progress rings.
- Info navigation no longer waits indefinitely for a service worker that has not been installed.
