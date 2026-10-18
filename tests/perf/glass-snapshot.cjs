/* Deterministic glass screenshot for before/after comparisons.
 *
 * Boots the shell with fixed fixtures, a fixed artwork backdrop with constant
 * audio bands, a fixed light direction and a fixed selection, pumps a few
 * frames, and writes a PNG. Compare two PNGs with --compare a.png b.png.
 *
 *   NODE_PATH=<dir with playwright,pngjs> node tests/perf/glass-snapshot.cjs --out a.png [--profile phone|desktop] [--root <repo>]
 *   NODE_PATH=... node tests/perf/glass-snapshot.cjs --compare a.png b.png [--diff diff.png]
 */
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');

const args = process.argv.slice(2);
const arg = (name, fallback) => { const i = args.indexOf('--' + name); return i >= 0 ? args[i + 1] : fallback; };

if (args.includes('--compare')) {
  const {PNG} = require('pngjs');
  const i = args.indexOf('--compare');
  const a = PNG.sync.read(fs.readFileSync(args[i + 1]));
  const b = PNG.sync.read(fs.readFileSync(args[i + 2]));
  if (a.width !== b.width || a.height !== b.height) { console.log(JSON.stringify({sizeMismatch: [a.width, a.height, b.width, b.height]})); process.exit(2); }
  const diff = new PNG({width: a.width, height: a.height});
  let max = 0, sum = 0, over8 = 0, over32 = 0;
  for (let p = 0; p < a.data.length; p += 4) {
    const d = Math.max(Math.abs(a.data[p] - b.data[p]), Math.abs(a.data[p + 1] - b.data[p + 1]), Math.abs(a.data[p + 2] - b.data[p + 2]));
    max = Math.max(max, d); sum += d; if (d > 8) over8++; if (d > 32) over32++;
    const v = Math.min(255, d * 4);
    diff.data[p] = v; diff.data[p + 1] = v; diff.data[p + 2] = v; diff.data[p + 3] = 255;
  }
  const px = a.width * a.height;
  if (arg('diff', '')) fs.writeFileSync(arg('diff', ''), PNG.sync.write(diff));
  console.log(JSON.stringify({max, mean: +(sum / px).toFixed(3), pctOver8: +(100 * over8 / px).toFixed(3), pctOver32: +(100 * over32 / px).toFixed(3)}));
  process.exit(0);
}

const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = path.resolve(arg('root', path.resolve(__dirname, '../..')));
const out = arg('out', 'glass-snapshot.png');
const profiles = {
  phone: {viewport: {width: 430, height: 932}, deviceScaleFactor: 2, isMobile: true, hasTouch: true},
  desktop: {viewport: {width: 1280, height: 800}, deviceScaleFactor: 1, isMobile: false, hasTouch: false},
};
const profile = profiles[arg('profile', 'phone')] || profiles.phone;
const types = {'.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.ttf': 'font/ttf', '.woff2': 'font/woff2', '.png': 'image/png', '.html': 'text/html'};
const ART = '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512"><defs><linearGradient id="a" x2="1" y2="1"><stop stop-color="#214758"/><stop offset=".5" stop-color="#d0a040"/><stop offset="1" stop-color="#a55536"/></linearGradient></defs><rect width="512" height="512" fill="url(#a)"/><circle cx="300" cy="200" r="140" fill="#3a8fd0"/><rect x="40" y="320" width="220" height="140" fill="#e8e0c8"/><path d="M0 0L512 512M512 0L0 512" stroke="#fff" stroke-width="18"/></svg>';
function api(url) {
  if (url.pathname === '/api/bootstrap') return {ok: true, asset_version: 'snap', device_settings_user_id: 'snap', ui_defaults: {visualizer: true}};
  if (url.pathname === '/api/library/config') return {ok: true, roots: [{id: 'fixture', name: 'Fixture library', mode: 'metadata'}], aggregate_root: {id: '__all__', name: 'Library', mode: 'metadata'}};
  if (url.pathname === '/api/setup/status') return {ok: true, complete: true, required: false};
  if (url.pathname === '/api/settings') return {ok: true, settings: {}, connections: {}, tools: {}, device_settings_user_id: 'snap'};
  return {ok: true, items: [], categories: [], tasks: [], now: null, queue: [], history: [], roots: [], settings: {}};
}

(async () => {
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname === '/snap-art.svg') { res.setHeader('Content-Type', 'image/svg+xml'); res.end(ART); return; }
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
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const browser = await chromium.launch({headless: true});
  const page = await browser.newPage(profile);
  page.setDefaultTimeout(300000);
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.addInitScript(() => {
    // Freeze time-dependent inputs: no pointer light, fixed random.
    let seed = 7;
    Math.random = () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; };
  });
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.waitForFunction(() => window.liquidGlassReady && window.state && document.querySelector('#libList .ipodItem'));
  await page.evaluate(() => {
    state.current = {kind: 'metalist', level: 'songs', label: 'Songs', root: {id: '__all__'}};
    resetList(Array.from({length: 200}, (_, i) => ({kind: 'track', media: 'audio', root_id: 'fixture', rel: `song-${i}.flac`, label: `Song ${i}`, secondary: `Artist ${i % 40} · Album ${i % 90}`, track_number: i + 1})));
    setSelectionFast(3);
  });
  await page.evaluate(() => {
    const img = new Image();
    img.src = '/snap-art.svg';
    return img.decode().then(() => {
      const field = window.visualizerArtField;
      field.image = img; field.loaded = true; field.artIdentity = 'snap-art'; field.algorithmVersion = 1;
      field.usefulLumaLow = 0.05; field.usefulLumaHigh = 0.95;
      const media = {paused: false, ended: false, currentTime: 60, duration: 240};
      window.currentVisualizerMediaElement = () => media;
      window.currentVisualizerMediaKind = () => 'audio';
      window.visualizerShouldShow = () => true;
      window.sampleCachedVisualizerAnalysis = () => ({bands: [0.6, 0.5, 0.4, 0.5, 0.6, 0.3, 0.2, 0.4, 0.5], energy: 0.5, beat: 0});
      if (typeof window.updateVisualizerState === 'function') window.updateVisualizerState();
    });
  });
  // Settle motion, fades and the visualizer.
  await page.waitForTimeout(Number(arg("settle", "12000")));
  await page.screenshot({path: out, timeout: 300000});
  console.log(JSON.stringify({out, errors}));
  await browser.close();
  server.close();
})().catch((e) => { console.error(e); process.exit(1); });
