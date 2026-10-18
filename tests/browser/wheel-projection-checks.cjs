const assert = require('node:assert/strict');

module.exports = async function checkWheelProjection(page) {
  const result = await page.evaluate(() => {
    const glass = DebriPod.glass.instance, surface = DebriPod.glass.surface, gl = surface.gl;
    // One frame draws the whole surface; lens geometry is re-read in its measure phase.
    const draw = () => { glass.requestRender(); glass.frame({timestamp: performance.now(), flags: {render: true}}); };
    // A known 128x256 gradient stands in for the backdrop: R = 2x, G = y, B = 90.
    const picture = document.createElement('canvas');
    picture.width = 128; picture.height = 256;
    const pictureCtx = picture.getContext('2d'), pixels = pictureCtx.createImageData(128, 256);
    for (let y = 0; y < 256; y++) for (let x = 0; x < 128; x++) {
      const i = (y * 128 + x) * 4;
      pixels.data[i] = x * 2; pixels.data[i + 1] = y; pixels.data[i + 2] = 90; pixels.data[i + 3] = 255;
    }
    pictureCtx.putImageData(pixels, 0, 0);
    const previousBackdrop = glass._backdropProvider, allLenses = surface.lenses;
    const probe = document.createElement('div');
    probe.style.transform = 'perspective(900px) rotateX(18deg) rotateY(-13deg)';
    document.body.appendChild(probe);
    const matrix = new DOMMatrix(getComputedStyle(probe).transform);
    probe.remove();
    const samples = [], hasTransform = [];
    // debugFlat draws the backdrop with no optics, so each lens pixel shows the
    // backdrop at the place the (projected) lens puts it on screen.
    glass.setBackdrop(SFGL.imageBackdrop(picture, {fit: 'stretch'}));
    glass.debugFlat(true);
    try {
      for (const lens of allLenses.filter(item => item.group === 'wheel')) {
        const oldTransform = lens.options.transform;
        // Pivot at the lens centre, the same transform the wheel's CSS tilt applies.
        lens.options.transform = item => {
          const r = item.rect, cx = r.left + r.width / 2, cy = r.top + r.height / 2;
          return {matrix: new DOMMatrix().translate(cx, cy).multiply(matrix).translate(-cx, -cy), tiltX: 18, tiltY: -13};
        };
        surface.lenses = [lens];
        try {
          draw();
          hasTransform.push(lens.hasTransform);
          const r = lens.rect, cx = r.left + r.width / 2, cy = r.top + r.height / 2;
          const scale = surface.renderScale, H = surface.canvas.height;
          for (const [fx, fy] of [[.2, .2], [.8, .7]]) {
            const p = new DOMPoint(r.left + fx * r.width - cx, r.top + fy * r.height - cy, 0, 1).matrixTransform(matrix);
            const sx = cx + p.x / p.w, sy = cy + p.y / p.w;
            const px = Math.floor(sx * scale), py = Math.floor(H - sy * scale);
            const rgba = new Uint8Array(4);
            gl.readPixels(px, py, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, rgba);
            samples.push({id:lens.el.id, actual:[...rgba], expected:[sx / surface.cssWidth * 256 - 1, sy / surface.cssHeight * 256 - .5]});
          }
        } finally {
          lens.options.transform = oldTransform;
        }
      }
    } finally {
      surface.lenses = allLenses;
      glass.debugFlat(false);
      glass.setBackdrop(previousBackdrop);
      draw();
    }
    return {samples, hasTransform, error:gl.getError()};
  });
  assert.equal(result.error, 0);
  assert.ok(result.hasTransform.length && result.hasTransform.every(Boolean), 'tilted wheel lenses must carry a transform');
  for (const sample of result.samples) {
    assert.ok(Math.abs(sample.actual[0] - sample.expected[0]) < 2, JSON.stringify(sample));
    assert.ok(Math.abs(sample.actual[1] - sample.expected[1]) < 2, JSON.stringify(sample));
    assert.equal(sample.actual[3], 255);
  }
};
