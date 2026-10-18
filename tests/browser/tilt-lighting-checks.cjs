const assert = require('node:assert/strict');

module.exports = async function checkTiltLighting(page) {
  const response = await page.evaluate(() => {
    const glass = DebriPod.glass.instance, surface = DebriPod.glass.surface;
    const lens = surface.lenses.find(item => item.el.id === 'libList');
    // One frame draws the whole surface; lens geometry is re-read in its measure phase.
    const draw = () => { glass.requestRender(); glass.frame({timestamp: performance.now(), flags: {render: true}}); };
    draw();
    const rect = lens.rect, dpr = surface.renderScale, gl = surface.gl;
    const original = glass.lighting;
    const sampleSurface = inset => [rect.left + inset, rect.left + rect.width - inset].map(x => {
      const rgba = new Uint8Array(4);
      gl.readPixels(Math.floor(x * dpr), Math.floor(surface.canvas.height - (rect.top + rect.height * .85) * dpr),
        1, 1, gl.RGBA, gl.UNSIGNED_BYTE, rgba);
      return [...rgba];
    });
    // This is where the old planar light direction vanished. Sample small
    // physical tilt changes across it, without animation hiding a shader jump.
    const scale = 1.15;
    const beta = Math.asin((.22 + .038 / 1.33) / scale) * 180 / Math.PI;
    const gamma = Math.asin((.16 + .024 / 1.33) / scale) * 180 / Math.PI;
    let light;
    // The glass reads its light through glass.lighting.state() every frame.
    glass.lighting = {state: () => light};
    try {
      const sweeps = ['beta', 'gamma'].map(axis => [-1, -.5, -.1, 0, .1, .5, 1].map(delta => {
        const b = beta + (axis === 'beta' ? delta : 0);
        const g = gamma + (axis === 'gamma' ? delta : 0);
        light = {x:-.16 + scale * Math.sin(g * Math.PI / 180), y:-.22 + scale * Math.sin(b * Math.PI / 180),
          intensity:.95, source:'orientation'};
        draw();
        return {delta, rims:sampleSurface(1.5), faces:sampleSurface(20)};
      }));
      const faces = [];
      const extremes = [-35, 35].map(angle => {
        light = {x:-.16 + scale * Math.sin(angle * Math.PI / 180), y:-.22, intensity:.95, source:'orientation'};
        draw();
        // These points are beyond the narrow rim: only the broad face light
        // should brighten the otherwise static black-backed material here.
        faces.push(sampleSurface(20));
        return sampleSurface(1.5);
      });
      return {sweeps, extremes, faces, error:gl.getError()};
    } finally {
      glass.lighting = original;
      draw();
    }
  });
  assert.equal(response.error, 0, 'tilt specular shader renders without GPU errors');
  for (const sweep of response.sweeps) {
    sweep.forEach((sample, index) => {
      assert.ok([...sample.rims, ...sample.faces].every(rgba => rgba[3] > 240), 'glass coverage remains opaque');
      if (!index) return;
      for (let side = 0; side < 2; side++) {
        for (let channel = 0; channel < 3; channel++) {
          for (const layer of ['rims', 'faces']) {
            const change = Math.abs(sample[layer][side][channel] - sweep[index - 1][layer][side][channel]);
            assert.ok(change <= 4, 'small tilt must smoothly cross the neutral light direction: ' + JSON.stringify(sweep));
          }
        }
      }
    });
  }
  const brightness = rgba => rgba.slice(0, 3).reduce((sum, value) => sum + value, 0);
  assert.ok(brightness(response.extremes[0][0]) > brightness(response.extremes[0][1]) + 9,
    'negative tilt lights the left rim: ' + JSON.stringify(response.extremes));
  assert.ok(brightness(response.extremes[1][1]) > brightness(response.extremes[1][0]) + 9,
    'positive tilt lights the right rim: ' + JSON.stringify(response.extremes));
  const neutralFaces = response.sweeps[0].find(sample => sample.delta === 0).faces;
  for (const faces of response.faces) {
    assert.ok(faces.some((rgba, side) => brightness(rgba) > brightness(neutralFaces[side]) + 6),
      'tilt lights the broad face beyond the narrow rim: ' + JSON.stringify({faces, neutralFaces}));
  }
  return response;
};
