# Shared glass motion and overlays

Load `static/js/glass-motion.js` and `static/js/glass-overlays.js` before `static/liquidGL.js`. They have no DebriPod state dependencies and are exposed as `liquidGL.motion` and `liquidGL.overlays` as well as standalone globals.

## Geometry

`motion.normalize(geometry)` clamps a radius to the physical dimensions before interpolation. This avoids the plateau caused by interpolating a 999px pill radius. `motion.interpolate(from, to, progress)` interpolates position, width, height, radius, independent X/Y scales, and extra numeric properties together. `motion.advance(from, to, elapsedMilliseconds, timeConstant)` provides frame-rate independent smoothing. All values settle in the same sample.

`motion.apply(element, geometry)` writes a complete DOM pose; the lens reads that pose for shader metrics. `motion.animate({frames, duration, update, complete, visible})` supplies one clock for keyframe sequences, supports cancellation, and respects reduced motion. Frames contain `offset` and `value`. Application adapters can map the same sample into CSS variables or custom lens layout metrics.

DebriPod uses this for selected-row geometry/stretch, path-pill dimensions/corners/padding/row expansion, and wheel-center bounce. CSS must not add separate height or radius transitions to those elements.

## Overlay content

The overlay observer starts at DOM readiness. `overlays.stop()` disconnects it and cancels active jobs; `start()` enables it again. Text replacement uses grapheme-aware differences and retains unchanged character runs. Both outgoing and incoming changed runs receive a 135ms blur/scale transition. Layout, selection motion, and horizontal scrolling remain separate.

Use `data-liquid-key` on reusable content hosts to match the same item across DOM replacement. Mark image symbols with `data-liquid-symbol`; ordinary artwork is not treated as a symbol. `overlays.attach(host, content, {hidden})` provides a pointer-transparent, accessibility-hidden overlay that follows a host without changing its layout. Hidden, offscreen, and reduced-motion updates skip animation. Content transitions are inspired by Apple's SwiftUI ContentTransition and symbol replacement behavior, not a pixel-identical port of private animations.

Verification: `node --test tests/js/glass-motion.test.mjs` and `node tests/browser/glass-ui.cjs` (Playwright; optionally set `PLAYWRIGHT_MODULE` and `BROWSER_CHANNEL`). The browser test samples actual WebGL lens metrics during a pill-to-rectangle transition and checks isolated text updates, row reuse, cleanup, offscreen behavior, and overflow alignment.
