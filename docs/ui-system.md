# DebriPod UI system

## Shared contracts

`ui-primitives.js` and `ui-primitives.css` own symbols, normalized rings, filled-circle activation, fonts, and foreground opacity. `row-system.js` adapts existing list models into standard rows and whitelisted contextual metadata. `row-system.css` owns the row/panel geometry. `list-view.js` retains virtualization and selection, using the same 55 px row estimate as the renderer. Dedicated multiline editors retain their natural input height.

The horizontal safe zone comes from `--screenFrame` through `--ui-safe-zone` and `--panel-safe-zone`. The panel occupies 30% of the screen content, with an additional safe-zone gap between it and the list. The list glass samples the full screen geometry, so narrowing the list does not create a new glass boundary. Row text remains on one line and fades at its moving edge.

The ring uses a 36 px SVG, a 15 px path radius, and a 2.25 px rounded stroke. Icons and numbers sit inside with consistent spacing. Active icons use the same circle footprint with the glyph cut out by a composite mask. Foreground opacity defaults to 0.40; emphasis is twice that base (0.80), clamped to the renderer's range. Legacy Text Transparency is migrated before the redesign default; versioned settings retain subsequent user adjustments. Host Grotesk 500 is the normal weight; headings and active lyrics use 600. Changing numeric values use tabular figures.

The symbol registry uses local copies of the SF Symbol PNG glyphs from `wan-kong/sf-symbols-online`; see `static/icons/sf/PROVENANCE.md` for the pinned source revision and explicit mappings for symbols absent from that collection. Masks tint the imported alpha silhouettes with the shared foreground color. Normal wheel navigation retains literal MENU, and the existing shuffle artwork is preserved. New symbols should use this registry and shared mask presentation. Local font files include their OFL license.

## Values and metadata

Numeric controls normalize against their actual minimum and maximum. The ring, exact value, and progress bar consume the same editor value. Keyboard editing updates these without rebuilding or losing focus; commit/cancel restores the playback pill's previous content.

Audio quality is a compact relative encoding of available metadata, not an acoustic quality measurement:

| Metadata | Ring completion |
| --- | --- |
| Lossy bitrate, 32–320 kb/s | 0.10–0.70 |
| CD lossless, 16 bit / 44.1 kHz | 0.82 |
| Lossless bit depth, 16–24 bit | Adds up to 0.09 |
| Lossless sample rate, 44.1–192 kHz | Adds up to 0.09 |
| Unknown quality | No inferred quality score |

Video and episode rings show watch completion. Track/episode numbers remain centered when available. Metadata panels accept useful named fields and format technical values with units. Cached audio facets receive public metadata from the index; album rows receive counts, duration, and folder membership. Internal identifiers are not rendered as metadata.

## Interaction and performance

`wheel-interaction.js` owns one pointer at a time. It resolves potential edge pulls, center holds, action targets, cancellation, and release. Screen state enables only the right information gesture or the left lyrics gesture. Once resolved, competing wheel behavior is suppressed until release. The center remains neutral in action mode, and asynchronous playback updates cannot overwrite the action glyphs.

Each selected standard row moves its icon and both text lines through one foreground wrapper. Neighboring text still refracts through the selected glass: native even-odd CSS clipping paths replace image-decoded SVG cutouts, and a cached, bounded text texture is reused while the lens moves. Glyph padding protects ascenders and descenders; the horizontal text fades remain part of the presentation.

Collections are expanded before mutation. Queue-next insertion reverses the insertion loop to preserve collection order. Like fills missing likes in a mixed collection and unlikes a completely liked collection. Playlist submission includes all members from a single library folder; the existing playlist storage model cannot represent members from several roots, so that action is unavailable for known multi-folder albums.

Lyrics use the same-origin LRCLIB endpoint, cancellable requests, a bounded cache, binary timestamp lookup, and the actual media/gapless position. Only a visible lyrics panel runs the 100 ms synchronization check; the DOM changes when the active line changes. Scrolling uses native smooth scrolling. A small manual scroll recenters the visible active line; scrolling it out of view suspends following until it is visible again or a timestamp is selected. Click, Enter, and Space seek to synchronized lines without changing playback state. Blur stays fixed at 6 px on one horizontally feathered layer with full artwork height; the unblurred right side remains available for pinning playback pills. Reveal transitions change opacity and transform. The panel batches pointer updates with animation frames and keeps its contents stable during reflow. Reduced-motion preferences disable transitions.

`list-scroll.js` owns native touch/momentum lifecycle without writing viewport position. `list-view.js` captures a screen anchor, picks the nearest row on settle without scrolling again, and owns one retargetable wheel scroll animation. Visible virtual rows remain attached; only the window edges change. Standard rows share one measured height, so scrolling does not rebuild a library-wide prefix sum for each newly exposed item. Wheel detents are accumulated once per frame instead of throttled into a delayed input backlog.

Rapid wheel navigation and native scrolling suspend the selected lens, foreground displacement, and native text cutouts together. The lens rebases at its final row before returning. Refraction textures are still cached while the visible lens moves; cutouts are committed only after the replacement pixels have been submitted, and translucent reveals leave native text intact.

Top-inward wheel pulls request browser fullscreen; bottom-inward pulls invoke Random in the same folder/category contexts that previously offered a Random row. Reversing a pull cancels it. Fullscreen remains subject to browser support. Random owns the selected object through asynchronous loading and normalizes cached root references for the complete playback queue.

Library root identities are single-line. Elsewhere, empty secondary lines collapse and the primary is centered. Secondary fields are compared as complete normalized values, so an album title is omitted from its own subtitle without stripping useful partial matches. MENU uses weight 800; navigation, action, and seek glyphs retain their common optical proportions at 88% of their previous size.

## Validation

Run Python tests with `.venv/Scripts/python.exe -m pytest -q` and JavaScript tests with `node --test tests/js/*.test.mjs`.

`tests/browser/redesign-smoke.cjs` uses an existing Playwright installation and Edge (`DEBRIPOD_TEST_BROWSER` can select another installed channel). It serves deterministic API fixtures and never alters a real library or account. Its primary viewport is iPhone 15 Pro Max: **430 × 932 CSS pixels at 3× scale**, equivalent to 1290 × 2796 physical pixels. It also checks narrower/wider layouts.

The browser checks real touch events for panel/lyrics gestures and hold-drag actions, dead-zone cancellation, action-overlay stability, row geometry, missing assets, keyboard numeric entry, rendered ring/bar agreement, and collection playlist submission. Screenshots and logs are written under `.pytest_cache`. Frame sampling records desktop browser animation timing; it does not certify 60 fps on physical iPhone hardware or Safari. Device performance remains a manual verification step.

The scrolling stress checks use a 10,000-song fixture, native touch momentum, fast wheel detents, top/bottom edge pulls, sparse-row centering, and cached Songs queue references. Playback startup is captured at the media boundary so these tests do not stream real files.
