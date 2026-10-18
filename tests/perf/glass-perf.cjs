/* Glass performance harness (virtual frame pump).
 *
 * Serves DebriPod's shell with deterministic fixtures, replaces the page's
 * requestAnimationFrame with a manual pump, and drives the app one frame at a
 * time. For each frame it measures:
 *   cpuMs     time spent in all animation-frame callbacks (scheduler, glass,
 *             motion, lighting, visualizer)
 *   gpuMs     time for gl.finish() on every WebGL canvas after the frame
 *             (with SwiftShader this is CPU-emulated GPU time)
 *   style / layout counts from the DevTools protocol
 *   glass renders, backdrop prepares
 * Real rAF never reaches the app, so results do not depend on how fast the
 * headless compositor presents frames.
 *
 *   NODE_PATH=<dir with playwright> node tests/perf/glass-perf.cjs
 *     [--profile phone|desktop] [--frames 90] [--cpu 4] [--render-scale 0.5]
 *     [--only idle,selection] [--out report.json]
 */
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');

const args = process.argv.slice(2);
const arg = (name, fallback) => { const i = args.indexOf('--' + name); return i >= 0 ? args[i + 1] : fallback; };
const profileName = arg('profile', 'phone');
const cpuRate = Number(arg('cpu', '1')) || 1;
const frames = Number(arg('frames', '90')) || 90;
const renderScale = Number(arg('render-scale', '0')) || 0;
const only = (arg('only', '') || '').split(',').filter(Boolean);
const outFile = arg('out', '');
const base = path.resolve(__dirname, '../..');

const profiles = {
  phone: {viewport: {width: 430, height: 932}, deviceScaleFactor: 3, isMobile: true, hasTouch: true},
  desktop: {viewport: {width: 1280, height: 800}, deviceScaleFactor: 1, isMobile: false, hasTouch: false},
};
const types = {'.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.ttf': 'font/ttf', '.woff2': 'font/woff2', '.png': 'image/png', '.html': 'text/html', '.json': 'application/json'};
const ART = '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512"><defs><linearGradient id="a" x2="1" y2="1"><stop stop-color="#214758"/><stop offset=".5" stop-color="#d0a040"/><stop offset="1" stop-color="#a55536"/></linearGradient></defs><rect width="512" height="512" fill="url(#a)"/><circle cx="300" cy="200" r="140" fill="#3a8fd0"/><rect x="40" y="320" width="220" height="140" fill="#e8e0c8"/></svg>';

function api(url) {
  if (url.pathname === '/api/bootstrap') return {ok: true, asset_version: 'perf', device_settings_user_id: 'perf', ui_defaults: {visualizer: true}};
  if (url.pathname === '/api/library/config') return {ok: true, roots: [{id: 'fixture', name: 'Fixture library', mode: 'metadata'}], aggregate_root: {id: '__all__', name: 'Library', mode: 'metadata'}};
  if (url.pathname === '/api/setup/status') return {ok: true, complete: true, required: false};
  if (url.pathname === '/api/settings') return {ok: true, settings: {}, connections: {}, tools: {}, device_settings_user_id: 'perf'};
  if (url.pathname === '/api/auth/status') return {ok: true, logged_in: false, username: 'Fixture'};
  return {ok: true, items: [], categories: [], tasks: [], now: null, queue: [], history: [], roots: [], settings: {}};
}

function serve() {
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname === '/perf-art.svg') { res.setHeader('Content-Type', 'image/svg+xml'); res.end(ART); return; }
    if (url.pathname.startsWith('/api/')) { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(api(url))); return; }
    const rel = url.pathname === '/' ? 'debripod/static/shell.html'
      : url.pathname.startsWith('/static/') ? 'debripod' + url.pathname
        : url.pathname.startsWith('/icons/') && !url.pathname.endsWith('.svg') ? 'debripod/static' + url.pathname
          : url.pathname.slice(1);
    const file = path.resolve(base, rel);
    if (!file.startsWith(base + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) { res.writeHead(404); res.end(); return; }
    res.setHeader('Content-Type', types[path.extname(file)] || 'application/octet-stream');
    res.end(fs.readFileSync(file));
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
}

/* Runs in the page before any app script. */
function installProbe() {
  const w = window;
  const realRaf = w.requestAnimationFrame.bind(w);
  const realCancel = w.cancelAnimationFrame.bind(w);
  let queue = new Map();
  let nextId = 1;
  w.__pumpMode = false;
  w.requestAnimationFrame = (cb) => {
    if (!w.__pumpMode) return realRaf(cb);
    const id = nextId++;
    queue.set(id, cb);
    return id;
  };
  w.cancelAnimationFrame = (id) => { if (queue.has(id)) queue.delete(id); else realCancel(id); };
  w.__pumpBegin = () => { w.__pumpMode = true; };
  // Run one virtual frame; returns CPU ms spent in callbacks.
  w.__pumpFrame = () => {
    const batch = queue;
    queue = new Map();
    const t = performance.now();
    batch.forEach((cb) => { try { cb(t); } catch (e) { (w.__pumpErrors = w.__pumpErrors || []).push(String(e && e.message || e)); } });
    return {cpuMs: performance.now() - t, callbacks: batch.size};
  };
  // Remember every WebGL context the page creates (canvas or offscreen) so the
  // probe can wait for GPU work without creating contexts of its own.
  const contexts = new Set();
  const wrap = (proto) => {
    if (!proto || !proto.getContext) return;
    const original = proto.getContext;
    proto.getContext = function (type, attrs) {
      const ctx = original.call(this, type, attrs);
      if (ctx && /webgl/.test(String(type))) contexts.add(ctx);
      return ctx;
    };
  };
  wrap(w.HTMLCanvasElement && w.HTMLCanvasElement.prototype);
  wrap(w.OffscreenCanvas && w.OffscreenCanvas.prototype);
  w.__gpuFinish = () => {
    const t = performance.now();
    const px = new Uint8Array(4);
    // readPixels cannot return until all queued drawing for that context is done.
    contexts.forEach((gl) => { try { if (!gl.isContextLost() && gl.drawingBufferWidth) gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px); } catch (e) {} });
    return performance.now() - t;
  };
  w.__glContextCount = () => contexts.size;
  w.__glassStats = () => {
    const out = {renders: 0, prepares: 0, copies: 0, lenses: 0, surfaces: 0};
    try {
      const glass = w.DebriPod && w.DebriPod.glass;
      if (glass && typeof glass.stats === 'function') return Object.assign(out, glass.stats());
      const seen = new Set();
      const list = [w.__liquidGLRenderer__].concat(Object.values(w.__liquidGLRenderers__ || {})).filter((r) => r && !seen.has(r) && seen.add(r));
      list.forEach((r) => {
        out.renders += r.renderCount || 0;
        out.prepares += r._opticalPrepareCount || 0;
        out.lenses += (r.lenses || []).length;
        out.surfaces += 1;
      });
    } catch (e) {}
    return out;
  };
  // Fake audio playback: drives the real visualizer and reactive glass with
  // synthetic band data instead of decoding media.
  w.__fakePlayback = (on) => {
    if (!on) { w.__fakePlaybackOn = false; if (typeof w.updateVisualizerState === 'function') w.updateVisualizerState(); return true; }
    const img = new Image();
    img.src = '/perf-art.svg';
    return img.decode().then(() => {
      const field = w.visualizerArtField;
      field.image = img; field.loaded = true; field.artIdentity = 'perf-art'; field.algorithmVersion = 1;
      field.usefulLumaLow = 0.05; field.usefulLumaHigh = 0.95;
      w.__fakePlaybackOn = true;
      const t0 = performance.now();
      const media = {paused: false, ended: false, currentTime: 0, duration: 240};
      w.currentVisualizerMediaElement = () => (w.__fakePlaybackOn ? media : null);
      w.currentVisualizerMediaKind = () => 'audio';
      w.visualizerShouldShow = () => !!w.__fakePlaybackOn && w.visualizerEnabled !== false;
      w.sampleCachedVisualizerAnalysis = () => {
        const t = (performance.now() - t0) / 1000;
        media.currentTime = t;
        return {bands: Array.from({length: 9}, (_, i) => 0.5 + 0.5 * Math.sin(t * (2 + i) + i)), energy: 0.5 + 0.4 * Math.sin(t * 3), beat: (t * 2) % 1 < 0.15 ? 1 : 0};
      };
      if (typeof w.updateVisualizerState === 'function') w.updateVisualizerState();
      return true;
    }).catch((e) => String(e));
  };
  // Grant motion permission so device-orientation lighting can be exercised.
  if (w.DeviceOrientationEvent) w.DeviceOrientationEvent.requestPermission = () => Promise.resolve('granted');
  w.__tilt = (beta, gamma) => {
    const e = new Event('deviceorientation');
    Object.assign(e, {alpha: 0, beta, gamma});
    w.dispatchEvent(e);
  };
  w.__pointer = (x, y) => {
    const target = document.elementFromPoint(x, y) || document.body;
    target.dispatchEvent(new PointerEvent('pointermove', {clientX: x, clientY: y, bubbles: true, pointerType: 'mouse'}));
  };
}

const METRICS = ['RecalcStyleCount', 'LayoutCount'];
async function metrics(cdp) {
  const {metrics: list} = await cdp.send('Performance.getMetrics');
  const out = {};
  for (const m of list) if (METRICS.includes(m.name)) out[m.name] = m.value;
  return out;
}
const mean = (v) => (v.length ? v.reduce((a, b) => a + b, 0) / v.length : 0);
function pct(values, p) {
  if (!values.length) return 0;
  const s = values.slice().sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(p * s.length))];
}

async function runScenario(page, cdp, name, perFrame) {
  const cpu = [];
  const gpu = [];
  const g0 = await page.evaluate(() => window.__glassStats());
  const m0 = await metrics(cdp);
  for (let i = 0; i < frames; i++) {
    if (perFrame) await perFrame(i);
    const r = await page.evaluate(() => window.__pumpFrame());
    cpu.push(r.cpuMs);
    gpu.push(await page.evaluate(() => window.__gpuFinish()));
    await page.waitForTimeout(4);
  }
  const m1 = await metrics(cdp);
  const g1 = await page.evaluate(() => window.__glassStats());
  const renders = g1.renders - g0.renders;
  return {
    scenario: name,
    frames,
    cpuMsMean: +mean(cpu).toFixed(2),
    cpuMsP95: +pct(cpu, 0.95).toFixed(2),
    gpuMsMean: +mean(gpu).toFixed(1),
    stylePerFrame: +((m1.RecalcStyleCount - m0.RecalcStyleCount) / frames).toFixed(2),
    layoutsPerFrame: +((m1.LayoutCount - m0.LayoutCount) / frames).toFixed(2),
    glassRenders: renders,
    prepares: g1.prepares - g0.prepares,
    copies: (g1.copies || 0) - (g0.copies || 0),
    lenses: g1.lenses,
    surfaces: g1.surfaces,
    webglContexts: await page.evaluate(() => window.__glContextCount()),
  };
}

(async () => {
  const server = await serve();
  const browser = await chromium.launch({headless: true});
  const profile = profiles[profileName] || profiles.phone;
  const page = await browser.newPage(profile);
  page.setDefaultTimeout(240000);
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.addInitScript(installProbe);
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Performance.enable');
  const bootStart = Date.now();
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.waitForFunction(() => window.liquidGlassReady && window.state && document.querySelector('#libList .ipodItem'));
  const bootSeconds = (Date.now() - bootStart) / 1000;
  await page.evaluate((scale) => {
    state.current = {kind: 'metalist', level: 'songs', label: 'Songs', root: {id: '__all__'}};
    resetList(Array.from({length: 2000}, (_, i) => ({kind: 'track', media: 'audio', root_id: 'fixture', rel: `song-${i}.flac`, label: `Song ${i}`, secondary: `Artist ${i % 40} · Album ${i % 90}`, track_number: i + 1})));
    setSelectionFast(4);
    if (scale) {
      DebriPod.uiSettings.settings.glassRenderScale = scale;
      window.dispatchEvent(new Event('resize'));
    }
  }, renderScale);
  await page.evaluate(() => DebriPod.glassLighting && DebriPod.glassLighting.requestOrientationPermission(true));
  await page.waitForTimeout(2500);
  await page.evaluate(() => window.__pumpBegin());
  // Settle: drain pending work from boot.
  for (let i = 0; i < 30; i++) { await page.evaluate(() => window.__pumpFrame()); await page.waitForTimeout(10); }
  if (cpuRate > 1) await cdp.send('Emulation.setCPUThrottlingRate', {rate: cpuRate});

  const vp = profile.viewport;
  const scenarios = [
    ['idle', null],
    ['selection', async (i) => { if (i % 12 === 0) await page.evaluate((d) => setSelectionFast(state.sel + d), (i / 12) % 8 < 4 ? 1 : -1); }],
    ['tilt', async (i) => { await page.evaluate(([b, g]) => window.__tilt(b, g), [40 + 12 * Math.sin(i / 9), 10 * Math.sin(i / 13)]); }],
    ['tiltStill', async () => { await page.evaluate(([b, g]) => window.__tilt(b, g), [40 + (Math.random() - 0.5) * 0.08, 5 + (Math.random() - 0.5) * 0.08]); }],
    ['mouse', async (i) => { await page.evaluate(([x, y]) => window.__pointer(x, y), [vp.width * (0.5 + 0.45 * Math.sin(i / 10)), vp.height * (0.5 + 0.45 * Math.cos(i / 14))]); }],
    ['playback', null],
    ['playbackSelection', async (i) => { if (i % 12 === 0) await page.evaluate((d) => setSelectionFast(state.sel + d), (i / 12) % 8 < 4 ? 1 : -1); }],
  ];

  const results = [];
  for (const [name, perFrame] of scenarios) {
    if (only.length && !only.includes(name)) continue;
    if (name === 'playback') {
      const ok = await page.evaluate(() => window.__fakePlayback(true));
      if (ok !== true) { results.push({scenario: name, skipped: String(ok)}); continue; }
      for (let i = 0; i < 10; i++) await page.evaluate(() => window.__pumpFrame());
    }
    results.push(await runScenario(page, cdp, name, perFrame));
    if (name === 'playbackSelection') await page.evaluate(() => window.__fakePlayback(false));
    // Let timers (pointer idle reset, selection settle) fire, then drain.
    await page.waitForTimeout(1200);
    for (let i = 0; i < 40; i++) await page.evaluate(() => window.__pumpFrame());
  }
  const pumpErrors = await page.evaluate(() => window.__pumpErrors || []);
  const report = {profile: profileName, cpuRate, renderScale: renderScale || 'default', frames, bootSeconds: +bootSeconds.toFixed(2), errors: errors.concat(pumpErrors), results};
  if (outFile) fs.writeFileSync(outFile, JSON.stringify(report, null, 2));
  console.log(`profile=${profileName} cpu=${cpuRate}x frames=${frames} boot=${report.bootSeconds}s errors=${report.errors.length}`);
  console.table(results);
  await browser.close();
  server.close();
})().catch((e) => { console.error(e); process.exit(1); });
