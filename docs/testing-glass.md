# Testing Glass branch

The `testing-glass` branch starts from `codex/testing3`. It replaces the optical
material inside DebriPod's shared LiquidGL renderer, with the original signed
material slider and device settings retained. Source revisions, licensing and
adaptations are recorded in
[`static/vendor/liquid-glass/NOTICE.md`](../debripod/static/vendor/liquid-glass/NOTICE.md).

## Wallpaper comparison

Open **Visualizer → Upload Wallpaper**. This invokes the browser's ordinary
`input type="file" accept="image/*"` picker, with no `capture` attribute forcing
the camera. iOS chooses which Photos, Files and Camera options it presents.

The decoded image is flattened once and limited to 4096 pixels on its long side,
stored locally in IndexedDB for the current device/user, and displayed centered
with `object-fit: cover`. The glass uses the identical crop. It is static, keeps
its original brightness, and is visible when playback is paused. Nothing is
uploaded to the server. Formats must be supported by the browser's image decoder;
unreadable images leave the previous backdrop intact.

Uploading turns Visualizer **off**. Turning Visualizer **on** immediately removes
the wallpaper and deletes its saved copy. Turning Visualizer off again does not
restore it. A synchronous deletion marker also prevents a reload during an
unfinished storage transaction from resurrecting the image. There is no separate
Remove Wallpaper control.

## Rendering and checks

- Two shared glass contexts, existing source artwork reuse, render scale, frame
  scheduling, layered glass and row text remain in place.
- Mip blur prepares a bounded GPU source only when artwork/visualizer state or
  source geometry changes. Slider, pointer-light and press updates reuse it.
- Native CSS shadows on the wheel explicitly use round corners so the global
  squircle CSS cannot produce a second silhouette around the circular shader.
- Specular rims use `codex/testing3`'s 3D light response with the newer sensor
  mapping and touch glow. Small tilts cross neutral without a direction flip.
- `renderer.debugState()` reports `opticalBackend`, `opticalPrepareCount`, and
  `opticalTextureSize` for inspecting cache reuse.

Run `node --test tests/js/*.test.mjs`, then, with `NODE_PATH` pointing to an existing
Playwright/pngjs installation:

```
node tests/browser/glass-ui.cjs
node tests/browser/glass-optics.cjs
node tests/browser/redesign-smoke.cjs
```

The optical browser check exercises the native picker, saved wallpaper restore,
deletion across reloads, invalid images, two-context/1.5x rendering, idle texture
reuse, circular wheel CSS, touch-highlight release, smooth specular tilt through
neutral, and actual GPU output on the no-LOD fallback. Images
are written to `.pytest_cache/testing-glass-*.png`. These are desktop Edge tests,
including a 430×932 viewport at 3x device scale; they do not substitute for Safari
testing on a physical iPhone or a measured comparison with Apple's native glass.
