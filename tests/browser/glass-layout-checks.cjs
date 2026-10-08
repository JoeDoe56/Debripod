const assert = require('node:assert/strict');

module.exports = async function checkGlassLayout(page) {
  const original = await page.evaluate(() => ({
    path: libHeaderText.textContent,
    now: pathPillNowText.textContent,
    expanded: libHeader.classList.contains('pathPillExpanded'),
  }));
  for (const expanded of [false, true, false]) {
    await page.evaluate(expanded => {
      libHeaderText.textContent = 'Library';
      pathPillNowText.textContent = 'Example song – Example artist';
      libHeader.classList.toggle('pathPillExpanded', expanded);
      updatePathPillMaxWidth();
    }, expanded);
    await page.waitForTimeout(450);
    const geometry = await page.evaluate(() => {
      const rect = selector => document.querySelector(selector).getBoundingClientRect();
      const style = selector => getComputedStyle(document.querySelector(selector));
      const pill = rect('#libHeader'), rows = rect('.pathPillRows');
      const icon = rect('.dpRowIconArea');
      return {
        pathHeight: pill.height, infoHeight: rect('#infoPill').height,
        centerOffset: Math.abs(pill.y + pill.height / 2 - rows.y - rows.height / 2),
        pathFont: style('#libHeaderText').fontSize, infoFont: style('.infoPill .npTime').fontSize,
        secondaryFont: style('.dpRowSecondary').fontSize,
        rowHeights: [...document.querySelectorAll('.dpStandardRow')].map(el => el.getBoundingClientRect().height),
        icon: [icon.width, icon.height],
        frame: style('#libList').paddingLeft,
        infoInset: (rect('.ipodScreenContent').width - rect('#infoPill').width) / 2,
      };
    });
    assert.equal(geometry.pathHeight, 48);
    assert.equal(geometry.infoHeight, 48);
    assert.ok(geometry.centerOffset < .1, JSON.stringify(geometry));
    assert.equal(geometry.pathFont, expanded ? '12px' : '15px');
    assert.equal(geometry.infoFont, '12px');
    assert.equal(geometry.secondaryFont, '12px');
    assert.ok(geometry.rowHeights.every(height => height === 48));
    assert.deepEqual(geometry.icon, [36, 36]);
    assert.equal(geometry.frame, '12px');
    assert.equal(geometry.infoInset, 12);
  }
  await page.evaluate(() => DebriPod.rowSystem.setPanelOpen(true));
  await page.waitForTimeout(350);
  const panel = await page.evaluate(() => {
    const list = libList.getBoundingClientRect();
    const panel = document.querySelector('.dpContextPanel').getBoundingClientRect();
    const screen = document.querySelector('.ipodScreenContent').getBoundingClientRect();
    return {widthFraction: panel.width / screen.width, gap: panel.left - list.right,
      padding: getComputedStyle(document.querySelector('.dpContextPanel')).padding};
  });
  assert.ok(Math.abs(panel.widthFraction - .4) < .001);
  assert.ok(Math.abs(panel.gap) < .1, JSON.stringify(panel));
  assert.equal(panel.padding, '12px');
  await page.evaluate(original => {
    libHeaderText.textContent = original.path;
    pathPillNowText.textContent = original.now;
    libHeader.classList.toggle('pathPillExpanded', original.expanded);
    updatePathPillMaxWidth();
    DebriPod.rowSystem.setPanelOpen(false);
  }, original);
  await page.waitForTimeout(350);
};
