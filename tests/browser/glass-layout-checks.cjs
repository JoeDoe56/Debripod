const assert = require('node:assert/strict');

module.exports = async function checkGlassLayout(page) {
  const original = await page.evaluate(() => ({
    path: libHeaderText.textContent,
    pathData: libHeaderText.dataset.text,
    nowHtml: pathPillNowText.innerHTML,
    nowData: pathPillNowText.dataset.text,
    now: state.now, meta: state.nowMeta,
    pathPinned: pathPillPinned, playbackPinned: playbackPillsPinned,
    playbackVisible: playbackPillsVisible,
  }));
  for (const scenario of ['empty', 'playing', 'cleared', 'playing', 'empty-row']) {
    const expanded = scenario === 'playing';
    await page.evaluate(scenario => {
      setPathPillPinned(true);
      if (scenario === 'playing') {
        state.now = {rel:'example.flac', media:'audio'};
        state.nowMeta = {title:'Example song', artist:'Example artist'};
        setPlaybackPillMetadata(state.nowMeta);
        showPlaybackPills(true);
      } else if (scenario === 'empty-row') {
        // A stale metadata attribute must not reserve an empty second row.
        pathPillNowText.textContent = '';
      } else {
        state.now = null;
        state.nowMeta = null;
        setPlaybackPillMetadata(null);
      }
      setHeader();
    }, scenario);
    await page.waitForTimeout(450);
    const geometry = await page.evaluate(() => {
      const rect = selector => document.querySelector(selector).getBoundingClientRect();
      const style = selector => getComputedStyle(document.querySelector(selector));
      const pill = rect('#libHeader'), rows = rect('.pathPillRows'), text = rect('#libHeaderText');
      const icon = rect('.dpRowIconArea');
      return {
        pathHeight: pill.height, infoHeight: rect('#infoPill').height,
        centerOffset: Math.abs(pill.y + pill.height / 2 - rows.y - rows.height / 2),
        textCenterOffset: Math.abs(pill.y + pill.height / 2 - text.y - text.height / 2),
        textXOffset: Math.abs(pill.x + pill.width / 2 - text.x - text.width / 2),
        expanded: libHeader.classList.contains('pathPillExpanded'),
        nowDisplay: style('#pathPillNowRow').display,
        pathFont: style('#libHeaderText').fontSize, infoFont: style('.infoPill .npTime').fontSize,
        secondaryFont: style('.dpRowSecondary').fontSize,
        rowHeights: [...document.querySelectorAll('.dpStandardRow')].map(el => el.getBoundingClientRect().height),
        icon: [icon.width, icon.height],
        frame: style('#libList').paddingLeft,
        infoInset: (rect('.ipodScreenContent').width - rect('#infoPill').width) / 2,
        seekWidth: rect('.npMeterTrack').width,
        seekX: rect('.npMeterTrack').x,
        pathMax: parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--pathPillMaxWidth')),
        infoWidth: rect('#infoPill').width,
        expectedSeekWidth: Math.floor(rect('.ipodScreenContent').width - 24) - 24,
      };
    });
    assert.equal(geometry.pathHeight, 48);
    assert.equal(geometry.infoHeight, 48);
    assert.equal(geometry.expanded, expanded, scenario);
    assert.ok(geometry.centerOffset < .1, scenario + JSON.stringify(geometry));
    assert.ok(geometry.textXOffset < .1, scenario + JSON.stringify(geometry));
    if (!expanded) {
      assert.equal(geometry.nowDisplay, 'none', scenario);
      assert.ok(geometry.textCenterOffset < .1, scenario + JSON.stringify(geometry));
    }
    assert.equal(geometry.pathFont, expanded ? '12px' : '15px', scenario);
    assert.equal(geometry.infoFont, '12px');
    assert.equal(geometry.secondaryFont, '12px');
    assert.ok(geometry.rowHeights.every(height => height === 48));
    assert.deepEqual(geometry.icon, [36, 36]);
    assert.equal(geometry.frame, '12px');
    assert.equal(geometry.infoInset, 12);
    assert.equal(geometry.seekWidth, geometry.expectedSeekWidth);
    assert.equal(geometry.seekX, 30);
    assert.equal(geometry.pathMax, geometry.infoWidth);
  }
  const caps = await page.evaluate(() => {
    const glass = DebriPod.glass.instance, surface = DebriPod.glass.surface;
    return ['.pathPillGlass', '.infoPillGlass', '#libListSelectedGlass'].map(selector => {
      const el = document.querySelector(selector);
      const lens = surface.lenses.find(item => item.el === el);
      // Lens geometry and shape are read in the frame's measure phase.
      lens.invalidate(true);
      glass.requestRender();
      glass.frame({timestamp: performance.now(), flags: {render: true}});
      const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
      return {selector, power:lens.cornerPower, radius:lens.radiusCss,
        expectedRadius:Math.min(rect.width, rect.height) / 2,
        shape:style.getPropertyValue('corner-shape')};
    });
  });
  for (const cap of caps) {
    assert.equal(cap.power, 2, cap.selector);
    assert.ok(Math.abs(cap.radius - cap.expectedRadius) < .01, JSON.stringify(cap));
    assert.ok(['round', 'superellipse(1)', ''].includes(cap.shape), JSON.stringify(cap));
  }
  const seekCaps = await page.evaluate(() => [...document.querySelectorAll('.npMeterTrack, .npBufferedFill, .npMeterFill')].map(el => ({
    radius:parseFloat(getComputedStyle(el).borderTopLeftRadius),
    height:el.getBoundingClientRect().height,
    shape:getComputedStyle(el).getPropertyValue('corner-shape'),
  })));
  for (const cap of seekCaps) {
    assert.ok(cap.radius >= cap.height / 2);
    assert.ok(['round', 'superellipse(1)', ''].includes(cap.shape), JSON.stringify(cap));
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
    libHeaderText.dataset.text = original.pathData;
    pathPillNowText.innerHTML = original.nowHtml;
    pathPillNowText.dataset.text = original.nowData;
    state.now = original.now;
    state.nowMeta = original.meta;
    playbackPillsVisible = original.playbackVisible;
    setPlaybackPillsPinned(original.playbackPinned);
    setPathPillPinned(original.pathPinned);
    updatePathPillMaxWidth();
    DebriPod.rowSystem.setPanelOpen(false);
  }, original);
  await page.waitForTimeout(350);
};
