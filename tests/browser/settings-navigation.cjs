/* Uses isolated API fixtures; never changes the running user's settings. */
const {chromium} = require('playwright');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const base = path.resolve(__dirname, '../..');
const types = {'.js':'text/javascript', '.css':'text/css', '.svg':'image/svg+xml', '.ttf':'font/ttf', '.woff2':'font/woff2', '.png':'image/png', '.html':'text/html'};
const saved = {};
function api(url) {
  if(url.pathname === '/api/bootstrap') return {ok:true, asset_version:'settings-navigation', device_settings_user_id:'fixture', ui_defaults:{visualizer:false}};
  if(url.pathname === '/api/library/config') return {ok:true, roots:[], aggregate_root:{id:'__all__', name:'Library', mode:'metadata'}};
  if(url.pathname === '/api/setup/status') return {ok:true, complete:true, required:false};
  if(url.pathname === '/api/settings') return {ok:true, settings:saved, startup:{ENABLE_MCP:false}, server_controls_owner:true, connections:{}, tools:{}, device_settings_user_id:'fixture'};
  return {ok:true, items:[], tasks:[], now:null, queue:[], history:[], roots:[], settings:{}};
}
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if(url.pathname.startsWith('/api/')) {
    let body = '';
    req.on('data', chunk => body += chunk);
    req.on('end', () => {
      if(url.pathname === '/api/settings/save') Object.assign(saved, JSON.parse(body).settings);
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify(api(url)));
    });
    return;
  }
  const file = url.pathname === '/' ? path.join(base, 'debripod/static/shell.html') : path.join(base, 'debripod', url.pathname);
  if(!file.startsWith(base + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) { res.writeHead(404); res.end(); return; }
  res.setHeader('Content-Type', types[path.extname(file)] || 'application/octet-stream');
  res.end(fs.readFileSync(file));
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({headless:true, channel:process.env.DEBRIPOD_TEST_BROWSER || 'msedge'});
    const page = await browser.newPage({viewport:{width:430, height:932}, isMobile:true, hasTouch:true});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.waitForFunction(() => window.state && state.items.length && typeof viewLibAdvancedCategory === 'function');
    await page.evaluate(() => setView({kind:'metalist', label:'Albums', load:async () => resetList([
      {kind:'album', label:'The Band', sub_label:'The Band', artist:'The Band'},
      {kind:'album', label:'Artist — Album', sub_label:'Artist · Album · 2026'},
    ])}, true));
    assert.deepEqual(await page.locator('#libList .dpRowSecondary').allTextContents(), ['The Band', 'Artist · Album · 2026']);
    await require('./panel-layout-checks.cjs')(page);
    const position = () => page.evaluate(() => ({selection:state.sel, scroll:libList.scrollTop, offset:state.pageAnchorOffset,
      y:libList.querySelector('.ipodItem.sel').getBoundingClientRect().top}));
    async function select(action) {
      await page.evaluate(action => {
        const index = state.items.findIndex(item => item.action === action || item.key === action);
        if(index < 0) throw new Error(`Missing row: ${action}`);
        setSelectionFast(index);
      }, action);
      await page.waitForFunction(() => libList._dpScrollAnimTarget == null);
      await page.waitForTimeout(150);
      return position();
    }
    async function unchanged(before, label) {
      await page.waitForTimeout(350);
      const after = await position();
      assert.equal(after.selection, before.selection, `${label}: selected row`);
      assert.ok(Math.abs(after.scroll - before.scroll) <= 1, `${label}: scroll ${before.scroll} -> ${after.scroll}`);
      assert.ok(Math.abs(after.y - before.y) <= 1, `${label}: selected row position ${before.y} -> ${after.y}`);
      assert.equal(after.offset, before.offset, `${label}: list spacer`);
    }

    await page.evaluate(() => viewLibAdvancedCategory('glass', true));
    const before = await select('cycle_glass_quality');
    assert.ok(before.scroll > 0, 'quality regression must exercise a scrolled list');
    for(let i = 0; i < 6; i++) {
      await page.locator('#libList .ipodItem.sel').click();
      await unchanged(before, 'glass quality');
      assert.equal(await page.evaluate(() => state.current.advancedCategory), 'glass');
    }
    const slider = await select('set_glass_quality:glassFrostSamples');
    await page.locator('#libList .ipodItem.sel').click();
    await page.evaluate(async () => { adjustRangeEditor(1); await applyRangeEditor(); });
    await unchanged(slider, 'slider apply');
    await page.locator('#libList .ipodItem.sel').click();
    await page.evaluate(() => cancelRangeEditor());
    await unchanged(slider, 'slider cancel');

    await page.evaluate(() => viewLibUiSettings(true));
    const visualizer = await select('toggle_video_ambient');
    await page.locator('#libList .ipodItem.sel').click();
    await unchanged(visualizer, 'visualizer toggle');

    await page.evaluate(() => viewLibAdvancedCategory('system', true));
    const system = await select('ENABLE_MCP');
    await page.locator('#libList .ipodItem.sel').click();
    await unchanged(system, 'server setting');
    await page.evaluate(() => refreshFullReindexStatus());
    await unchanged(system, 'background status refresh');

    await page.evaluate(() => viewLibAdvancedCategory('animations', true));
    const animation = await select('cycle_animation_fps:pathPill');
    await page.locator('#libList .ipodItem.sel').click();
    await unchanged(animation, 'animation frame cap');
    await page.evaluate(() => viewLibAdvancedCategory('glass', true));
    await page.evaluate(() => goBack());
    await unchanged(animation, 'Back to settings');

    await page.evaluate(() => viewTorrentSources(true));
    await page.evaluate(() => setSelectionFast(state.items.findIndex(item => item.sourceId === 'torapi')));
    await page.waitForFunction(() => libList._dpScrollAnimTarget == null);
    const torrent = await position();
    await page.locator('#libList .ipodItem.sel').click();
    await unchanged(torrent, 'torrent source toggle');

    await page.evaluate(() => viewSettingsCategory('services', true));
    const editor = await select('SOULSEEK_PASSWORD');
    const historyLength = await page.evaluate(() => state.history.length);
    await page.locator('#libList .ipodItem.sel').click();
    await page.evaluate(() => commitSettingsEditor());
    await unchanged(editor, 'text editor save');
    assert.equal(await page.evaluate(() => state.history.length), historyLength, 'editor save consumes the parent history entry');
    await page.locator('#libList .ipodItem.sel').click();
    await page.evaluate(() => handleLibInfoAction('settings_editor_cancel'));
    await unchanged(editor, 'text editor cancel');
    assert.deepEqual(errors, []);
    console.log('Settings browser checks passed: all glass tiers, slider apply/cancel, visualizer toggle, server setting, status polling, animation cap, Back, torrent source toggle, text editor save/cancel.');
  } finally {
    if(browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
