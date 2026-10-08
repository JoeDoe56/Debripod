const assert = require('node:assert/strict');

module.exports = async function checkWheelProjection(page) {
  const result = await page.evaluate(() => {
    const r = window.__liquidGLRenderers__.wheel, gl = r.gl;
    const texture = gl.createTexture();
    const pixels = new Uint8Array(128 * 256 * 4);
    for (let y = 0; y < 256; y++) for (let x = 0; x < 128; x++) {
      const i = (y * 128 + x) * 4;
      pixels[i] = x * 2; pixels[i + 1] = y; pixels[i + 2] = 90; pixels[i + 3] = 255;
    }
    gl.activeTexture(gl.TEXTURE7); gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 128, 256, 0, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const oldDraw = gl.drawArrays, oldLenses = r.lenses;
    // Bypass material grading with a known gradient, exercising the actual
    // fragment projection and texture lookup on the GPU.
    gl.drawArrays = function(...args) {
      if (!gl.getUniform(r.program, r.u.prepareOpticalSource)) {
        gl.uniform1i(r.u.debugAlbumSourceFlat, 1);
        gl.activeTexture(gl.TEXTURE7); gl.bindTexture(gl.TEXTURE_2D, texture);
        gl.uniform1i(r.u.albumCurrentTex, 7); gl.uniform1i(r.u.albumNextTex, 7);
        gl.uniform1f(r.u.albumMix, 0);
        const source = r._sourceCssRect;
        gl.uniform2f(r.u.albumSourceSize, source.width, source.height);
        gl.uniform2f(r.u.albumCurrentSize, source.width, source.height);
        gl.uniform2f(r.u.albumNextSize, source.width, source.height);
      }
      return oldDraw.apply(this, args);
    };
    const probe = document.createElement('div');
    probe.style.transform = 'perspective(900px) rotateX(18deg) rotateY(-13deg)';
    document.body.appendChild(probe);
    const matrix = new DOMMatrix(getComputedStyle(probe).transform);
    probe.remove();
    const samples = [];
    try {
      for (const lens of oldLenses) {
        const oldTilt = [lens.tiltX, lens.tiltY];
        lens.tiltX = 18; lens.tiltY = -13; r.lenses = [lens]; r.render();
        const rect = lens.rectPx, source = r._sourceCssRect;
        const viewport = gl.getParameter(gl.VIEWPORT);
        const pivot = lens.options.tiltProjection();
        for (const [fx, fy] of [[.2, .2], [.8, .7]]) {
          const x = viewport[0] + Math.floor(viewport[2] * fx);
          const y = viewport[1] + Math.floor(viewport[3] * (1 - fy));
          const localX = (x - viewport[0] + .5) / viewport[2];
          const localY = 1 - (y - viewport[1] + .5) / viewport[3];
          const point = new DOMPoint(rect.left + localX * rect.width - pivot.x,
            rect.top + localY * rect.height - pivot.y, 0, 1).matrixTransform(matrix);
          const uv = [(pivot.x + point.x / point.w - source.left) / source.width,
            (pivot.y + point.y / point.w - source.top) / source.height];
          const rgba = new Uint8Array(4);
          gl.readPixels(x, y, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, rgba);
          samples.push({id:lens.el.id, actual:[...rgba], expected:[uv[0] * 256 - 1, (1 - uv[1]) * 256 - .5]});
        }
        [lens.tiltX, lens.tiltY] = oldTilt;
      }
    } finally {
      gl.drawArrays = oldDraw; r.lenses = oldLenses;
      gl.deleteTexture(texture); gl.activeTexture(gl.TEXTURE0); r.render();
    }
    return {samples, error:gl.getError()};
  });
  assert.equal(result.error, 0);
  for (const sample of result.samples) {
    assert.ok(Math.abs(sample.actual[0] - sample.expected[0]) < 2, JSON.stringify(sample));
    assert.ok(Math.abs(sample.actual[1] - sample.expected[1]) < 2, JSON.stringify(sample));
    assert.equal(sample.actual[3], 255);
  }
};
