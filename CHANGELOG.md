# Changelog

All notable changes are documented here using Keep a Changelog categories.
Commits use Conventional Commits.

## [Unreleased]

### Added
- Glass quality setting (Auto, Superfluid, Glass, Lite, Frost, Solid). Auto adapts render scale and tier to the device. Frost and Solid draw with CSS only, and a lost WebGL context falls back to Frost.
- Glass performance harness (`tests/perf/glass-perf.cjs`) and deterministic snapshot tool (`tests/perf/glass-snapshot.cjs`).
- Inward top/bottom wheel pulls enter fullscreen or choose a random eligible item, with gesture cancellation and stable directional controls.
- Lyrics over Now Playing artwork, with synchronized LRC highlighting, plain lyrics, instrumental and unavailable states, track-change cancellation, and seek-aware playback tracking.
- Same-origin LRCLIB lookup through the shared HTTP client, with cached exact recording lookup and conservative search matching.
- Shared standard rows, normalized rounded rings, glyph-cutout activation circles, and adaptive metadata panels across browsing and settings.
- Explicit wheel gesture states for contextual panels, lyrics, and reversible hold-and-drag media actions.
- Local Host Grotesk fonts and a unified SF Symbols-style SVG registry, including the specified playback and heart variants.
- Tests for gestures, collection actions, metadata, numeric normalization, and iPhone 15 Pro Max browser dimensions.

### Changed
- The glass engine moved to the sfgl repository, with its history, and is vendored in `static/vendor/sfgl`. One surface now draws every lens. The wheel's tilt is projected in the shader instead of on a second canvas. The backdrop is prepared at most once per frame and only when it changes. Idle, still-tilt and playback frames do far less GPU and main-thread work.
- Mouse movement moves the glass light on devices without tilt sensors.
- Native list scrolling owns touch and momentum, hides the selected glass until settling, and selects the row beneath its previous screen position.
- Wheel detents are batched per animation frame; virtual rows stay attached and share a measured height instead of rebuilding library-wide measurements during scrolling.
- Library root rows use a centered single line. Other sparse rows center automatically, and secondary lines omit repeated identities and fields.
- Wheel glyphs are 12% smaller; MENU retains matching optical height at Host Grotesk weight 800.
- Standard rows use one 55 px architecture with meaningful left indicators and primary/secondary text hierarchy.
- Panels reclaim approximately 30% of the screen width with shared safe-zone spacing and fading row text.
- Advanced Settings exposes Text Opacity; foreground emphasis derives from that value.
- Numeric settings share their range state with persistent rings and temporary exact-value feedback, including keyboard entry.
- Album actions resolve collection members; Like preserves existing likes until the whole collection is liked, and queue insertion preserves order.
- Lyrics use a fixed, feathered blur behind the text, smooth native scrolling, and opacity/transform transitions with reduced-motion support.
- Shared settings-row construction replaces duplicate builders, and offline shell caching includes the new fonts, symbols, and styles.

### Removed
- `static/liquidGL.js`, the separate glass-motion, glass-overlays, glass-lighting, frame-scheduler and row-refraction scripts, and about 1,700 lines of unused renderer code paths. All of them are now part of sfgl.
- Full Screen settings and Random list rows; their actions now use the wheel edge gestures.
- Persistent metadata/status pills on standard rows, double-height standard rows, the dedicated View Lyrics action, and the separate center-hold action screen.

### Fixed
- Liquid glass diagnostics were written to an undefined global. They now go to `window.DebriPod.liquidDiagnostics`.
- Selection/refraction flicker during rapid wheel and finger scrolling: one scroll owner, coordinated geometry, cleared hidden-lens cutouts, and native text replacement committed after glass drawing.
- Songs Random resolves cached library references for every queue entry, retains its chosen item through async navigation, and prevents overlapping playback starts.
- Lyrics browsing now preserves offscreen reading positions, recenters small scrolls, and supports seeking by click or keyboard. Full-height blur feathers toward the cover's midpoint, leaving right-side artwork taps available to pin playback pills.
- Short inward pulls from the Next Track region open the information panel without conflicting wheel scrolling.
- Selected row labels, secondary text, and indicators move together; default and migrated foreground opacity uses 40% normal and 80% emphasis.
- Neighboring row text retains glass refraction with synchronous native cutouts and cached text textures, avoiding repeatedly decoded SVG masks and clipped glyph edges.
- Replaced approximate symbol SVGs with the requested upstream SF Symbol glyphs, restored MENU text, and included imported assets in offline shell caching.
- Pointer capture handoffs, center-origin panel dismissal, action cancellation, and restoration of normal wheel icons.
- Numeric keyboard input and complete album submission through the playlist picker after the row redesign.
- Metadata units, zero-value counts, audio quality normalization, and video watch-progress rings.
- Info navigation no longer waits indefinitely for a service worker that has not been installed.
