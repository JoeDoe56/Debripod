# Glass motion and overlays

The glass engine, motion, lighting, content transitions and the row-text underlay now live in [sfgl](https://github.com/JoeDoe56/sfgl). DebriPod vendors its build in `debripod/static/vendor/sfgl/`; refresh it with `Scripts/sync-sfgl.sh [path-to-sfgl]`. sfgl's [motion guide](https://github.com/JoeDoe56/sfgl/blob/main/docs/motion.md) documents the APIs.

DebriPod wires them up in two files.

## `static/js/glass-host.js`

It creates the shared instances:
- `DebriPod.frameScheduler`: one requestAnimationFrame loop for the app and the glass.
- `DebriPod.glassLighting`: device tilt with the pointer as the alternative. The permission is stored per device user.
- `window.LiquidGlassMotion`: sfgl's `motion`.
- `window.LiquidGlassOverlays`: content transitions on `document.body`. They use opacity only below the `glass` tier.
- `DebriPod.rowRefraction`: the selected row's text underlay.

## `static/js/liquid-glue.js`

It adapts sfgl to DebriPod:
- **Surface:** one surface on `.ipodStage` draws every lens. These are the library list, selected row, list pills, path pill, info pill, and the wheel ring and centre.
- **Wheel:** its tilt is a lens `transform`, the same `perspective(900px)` rotation CSS would apply.
- **Backdrop:** the reactive visualizer is a program backdrop (`DEBRIPOD_REACTIVE_BACKDROP`), or the uploaded wallpaper is used through `SFGL.imageBackdrop`.
- **Diagnostics:** `DebriPod.glass` exposes `instance`, `surface` and `stats()`.

## Motion

DebriPod uses motion for:
- the selected-row geometry and stretch;
- the path pill's size, corners, padding and row expansion;
- the wheel-centre bounce.

CSS must not add separate height or radius transitions to those elements.

## Opting out

`data-liquid-overlay-exempt` excludes a host and its descendants from content transitions. Playback clocks and performance diagnostics use it.
