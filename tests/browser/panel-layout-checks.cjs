const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

module.exports = async function checkPanelAndFullscreenLayout(page) {
  await page.waitForFunction(() => window.DebriPod?.glass?.instance);
  for(const tier of ['static', 'frost', 'lite', 'glass', 'superfluid']) {
    await page.evaluate(tier => {
      uiSettings.glassQuality = tier;
      DebriPod.glass.instance.invalidate(true);
      DebriPod.rowSystem.setPanelOpen(false);
    }, tier);
    await page.waitForFunction(tier => DebriPod.glass.instance.tier().name === tier, tier);
    await page.waitForTimeout(350);
    const closed = await page.locator('#libListGlass').boundingBox();
    for(const progress of [0.5, 1]) {
      await page.evaluate(progress => DebriPod.rowSystem.setPanelProgress(progress, {immediate:true}), progress);
      await page.waitForTimeout(150);
      const geometry = await page.evaluate(() => {
        const box = element => {const r=element.getBoundingClientRect(); return {left:r.left, right:r.right, top:r.top, bottom:r.bottom, width:r.width};};
        const background = document.getElementById('libListGlass');
        const lens = DebriPod.glass.surface.lenses.find(lens => lens.group === 'libraryList');
        return {background:box(background), content:box(background.parentElement), list:box(libList), panel:box(document.querySelector('.dpContextPanel')),
          color:getComputedStyle(background).backgroundColor, cssTier:background.dataset.sfTier, lensWidth:lens.rect?.width};
      });
      assert.ok(Math.abs(geometry.background.width - closed.width) < 1, `${tier}: glass width stays fixed while the panel slides`);
      assert.ok(geometry.list.width < closed.width - 30, `${tier}: list content gives the panel room`);
      assert.ok(geometry.background.right >= Math.min(geometry.panel.right, geometry.content.right) - 1, `${tier}: visible panel has a background`);
      if(tier === 'static' || tier === 'frost') {
        assert.equal(geometry.cssTier, tier);
        assert.notEqual(geometry.color, 'rgba(0, 0, 0, 0)', `${tier}: CSS glass has a fill`);
      } else {
        assert.ok(Math.abs(geometry.lensWidth - closed.width) < 1, `${tier}: WebGL glass covers the entire screen`);
      }
      if(process.env.DEBRIPOD_TEST_OUTPUT && progress === 1) {
        fs.mkdirSync(process.env.DEBRIPOD_TEST_OUTPUT, {recursive:true});
        await page.screenshot({path:path.join(process.env.DEBRIPOD_TEST_OUTPUT, `panel-${tier}.png`)});
      }
    }
  }
  await page.evaluate(() => DebriPod.rowSystem.setPanelOpen(false));

  // A height-only touch resize normally preserves the layout for browser
  // chrome. Fullscreen entry/exit must explicitly accept the new height.
  await page.setViewportSize({width:360, height:640});
  await page.evaluate(() => document.dispatchEvent(new Event('fullscreenchange')));
  await page.waitForTimeout(250);
  const before = await page.locator('#wheel').boundingBox();
  await page.setViewportSize({width:360, height:740});
  assert.equal(await page.evaluate(() => document.documentElement.style.getPropertyValue('--stable-viewport-height')), '640px');
  await page.evaluate(() => document.dispatchEvent(new Event('fullscreenchange')));
  await page.waitForTimeout(250);
  assert.equal(await page.evaluate(() => document.documentElement.style.getPropertyValue('--stable-viewport-height')), '740px');
  const after = await page.locator('#wheel').boundingBox();
  assert.ok(after.y + after.height / 2 > before.y + before.height / 2 + 20, 'wheel moves into the added fullscreen space');
  assert.ok(after.y + after.height <= 741, 'wheel stays within the fullscreen viewport');
  await page.setViewportSize({width:360, height:640});
  await page.evaluate(() => document.dispatchEvent(new Event('fullscreenchange')));
  await page.waitForTimeout(250);
  const restored = await page.locator('#wheel').boundingBox();
  assert.ok(Math.abs(restored.y - before.y) < 1, 'leaving fullscreen restores wheel position');
  await page.setViewportSize({width:430, height:932});
  await page.waitForTimeout(200);
  console.log('Panel background checks passed across five tiers; touch fullscreen resize moves and restores the wheel.');
};
