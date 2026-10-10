const assert = require('node:assert/strict');

module.exports = async function checkTiltLighting(page) {
  const response = await page.evaluate(() => {
    const renderer = window.__liquidGLRenderers__.main;
    const lens = renderer.lenses.find(item => item.el.id === 'libList');
    lens.updateMetrics();
    const rect = lens.rectPx, dpr = renderer._dpr, gl = renderer.gl;
    const original = renderer._globalLightingState;
    const sampleRims = () => [rect.left + 1.5, rect.left + rect.width - 1.5].map(x => {
      const rgba = new Uint8Array(4);
      gl.readPixels(Math.floor(x * dpr), Math.floor(renderer.canvas.height - (rect.top + rect.height * .85) * dpr),
        1, 1, gl.RGBA, gl.UNSIGNED_BYTE, rgba);
      return [...rgba];
    });
    // This is where the old planar light direction vanished. Sample small
    // physical tilt changes across it, without animation hiding a shader jump.
    const scale = 1.15;
    const beta = Math.asin((.22 + .038 / 1.33) / scale) * 180 / Math.PI;
    const gamma = Math.asin((.16 + .024 / 1.33) / scale) * 180 / Math.PI;
    let light;
    renderer._globalLightingState = () => light;
    try {
      const sweeps = ['beta', 'gamma'].map(axis => [-1, -.5, -.1, 0, .1, .5, 1].map(delta => {
        const b = beta + (axis === 'beta' ? delta : 0);
        const g = gamma + (axis === 'gamma' ? delta : 0);
        light = {x:-.16 + scale * Math.sin(g * Math.PI / 180), y:-.22 + scale * Math.sin(b * Math.PI / 180),
          intensity:.95, source:'orientation'};
        renderer.render();
        return {delta, rims:sampleRims()};
      }));
      const extremes = [-35, 35].map(angle => {
        light = {x:-.16 + scale * Math.sin(angle * Math.PI / 180), y:-.22, intensity:.95, source:'orientation'};
        renderer.render();
        return sampleRims();
      });
      return {sweeps, extremes, error:gl.getError()};
    } finally {
      renderer._globalLightingState = original;
      renderer.render();
    }
  });
  assert.equal(response.error, 0, 'tilt specular shader renders without GPU errors');
  for (const sweep of response.sweeps) {
    sweep.forEach((sample, index) => {
      assert.ok(sample.rims.every(rgba => rgba[3] > 240), 'rim coverage remains opaque');
      if (!index) return;
      for (let side = 0; side < 2; side++) {
        for (let channel = 0; channel < 3; channel++) {
          const change = Math.abs(sample.rims[side][channel] - sweep[index - 1].rims[side][channel]);
          assert.ok(change <= 4, 'small tilt must smoothly cross the neutral light direction: ' + JSON.stringify(sweep));
        }
      }
    });
  }
  const brightness = rgba => rgba.slice(0, 3).reduce((sum, value) => sum + value, 0);
  assert.ok(brightness(response.extremes[0][0]) > brightness(response.extremes[0][1]) + 9,
    'negative tilt lights the left rim: ' + JSON.stringify(response.extremes));
  assert.ok(brightness(response.extremes[1][1]) > brightness(response.extremes[1][0]) + 9,
    'positive tilt lights the right rim: ' + JSON.stringify(response.extremes));
  return response;
};
