import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const glue = fs.readFileSync(path.resolve(here, "../../debripod/static/js/liquid-glue.js"), "utf8");
const liquid = fs.readFileSync(path.resolve(here, "../../debripod/static/liquidGL.js"), "utf8");
const visualizer = fs.readFileSync(path.resolve(here, "../../debripod/static/js/visualizer-engine.js"), "utf8");

function extractFunction(source, name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} must remain independently testable`);
  const open = source.indexOf("{", start);
  let depth = 0;
  let quote = "";
  let escaped = false;
  for(let i = open; i < source.length; i++){
    const ch = source[i];
    if(quote){
      if(escaped) escaped = false;
      else if(ch === "\\") escaped = true;
      else if(ch === quote) quote = "";
      continue;
    }
    if(ch === '"' || ch === "'" || ch === "`") quote = ch;
    else if(ch === "{") depth += 1;
    else if(ch === "}" && --depth === 0) return source.slice(start, i + 1);
  }
  assert.fail(`${name} body is not balanced`);
}

test("glass uses only main and wheel render contexts", () => {
  assert.match(glue, /LIQUID_VISUALIZER_RENDERER_KEYS = \["main", "wheel"\]/);
  assert.match(glue, /rendererKey: "main"/);
  assert.match(glue, /rendererKey: "wheel"/);
  assert.doesNotMatch(glue, /rendererKey: "lib(?:List|Selection|Pills)"/);
  assert.match(glue, /syncLensGroup\("listPills"/);
});

test("reactive artwork is uploaded only on its art key and sampled as uniforms", () => {
  assert.match(liquid, /adapter && adapter\.ready && adapter\.image/);
  assert.match(liquid, /artKey === this\._reactiveArtKey && this\.texture/);
  assert.match(liquid, /_bindReactiveVisualizerUniforms\(fs\)/);
  assert.match(liquid, /u_reactiveBands\[9\]/);
  assert.match(visualizer, /return \{image:visualizerArtField\.image, artKey:/);
  assert.doesNotMatch(visualizer, /return \{canvas:visualizerBg/);
});

test("the glass backing scale is independent of device DPR and frost is deterministic", () => {
  assert.match(liquid, /glassRenderScale/);
  assert.match(liquid, /_configuredFrostSamples\(\)/);
  assert.match(liquid, /value : 8/);
  assert.match(liquid, /const int MAX_FROST_SAMPLES = 16/);
  assert.doesNotMatch(liquid, /random\(v_uv/);
  assert.match(liquid, /antialias: false/);
  assert.match(liquid, /depth: false/);
  assert.match(liquid, /stencil: false/);
  assert.match(liquid, /preserveDrawingBuffer: false/);
  assert.doesNotMatch(liquid, /getContext\("webgl2"/);
  assert.doesNotMatch(liquid, /this\.el\.style\.pointerEvents\s*=\s*["']none["']/);
});

test("glass composites premultiplied overlap and smooths power-of-two source minification", () => {
  assert.match(liquid, /gl\.enable\(gl\.BLEND\)/);
  assert.match(liquid, /gl\.blendFunc\(gl\.ONE, gl\.ONE_MINUS_SRC_ALPHA\)/);
  assert.match(liquid, /isPowerOfTwoTexture\(width, height\)/);
  assert.match(liquid, /gl\.generateMipmap\(gl\.TEXTURE_2D\)/);
  assert.match(visualizer, /visualizerTextureUsesMipmaps/);
  assert.match(visualizer, /gl\.generateMipmap\(gl\.TEXTURE_2D\)/);
});

test("pill glass opts into per-render DOM geometry without changing wheel mirror caching", () => {
  assert.match(glue, /liveGeometry: \["pathPill", "infoPill", "listPills", "selectedRow"\]/);
  assert.match(liquid, /this\._syncDomRect = this\.options\.liveGeometry === true/);
  assert.match(liquid, /else if \(this\.lenses\.some\(\(lens\) => lens && lens\._syncDomRect\)\)/);
  assert.match(liquid, /this\._mirrorActive && this\._baseRect/);
  assert.doesNotMatch(liquid, /_liveMirrorBaseRect/);
});

test("NP teardown unregisters transient lenses, cancels selection work, and restores on return", () => {
  const context = {
    listSelectionMotion: {raf: -1},
    frameScheduler: () => ({cancel(key){ context.cancelled = key; }}),
    cancelAnimationFrame(id){ context.cancelledRaf = id; },
    clearTimeout(id){ context.clearedTimer = id; },
  };
  vm.createContext(context);
  vm.runInContext([
    extractFunction(glue, "syncLibTransientLenses"),
    extractFunction(glue, "cancelLibSelectionMotion"),
  ].join("\n"), context);

  const selected = {id: "libListSelectedGlass", isConnected: true};
  const pill = {isConnected: true, matches(selector){ return selector === ".ipodPill[data-liquid-row-pill]"; }};
  const other = {isConnected: true};
  const destroyed = [];
  const lens = (el, group) => ({el, _dpLensGroup: group, destroy(){destroyed.push(el);}});
  const renderer = {
    lenses: [lens(selected), lens(pill), lens(other, "pathPill")],
    addLens(el){ const next = lens(el); this.lenses.push(next); return next; },
    renderCount: 0,
    render(){ this.renderCount += 1; },
  };

  context.syncLibTransientLenses(renderer, {
    active: false,
    selectedElement: selected,
    pillElements: [pill],
  });
  assert.deepEqual([...renderer.lenses].map((item) => item.el), [other]);
  assert.equal(destroyed.length, 2, "NP removes both selected and row-pill lenses");
  renderer.render();
  assert.equal(renderer.lenses.some((item) => item.el === selected || item.el === pill), false);

  context.cancelLibSelectionMotion();
  assert.equal(context.cancelled, "lib-selection-motion");
  assert.equal(context.listSelectionMotion.raf, 0);
  context.listSelectionMotion.raf = 17;
  context.cancelLibSelectionMotion();
  assert.equal(context.cancelledRaf, 17, "native selection RAF is cancelled too");

  context.syncLibTransientLenses(renderer, {
    active: true,
    selectedElement: selected,
    pillElements: [pill],
  });
  assert.equal(renderer.lenses.some((item) => item.el === selected), true, "selected lens returns after NP");
  assert.equal(renderer.lenses.some((item) => item.el === pill), true, "row-pill lens returns after NP");
});

test("selected-row settings preview never re-registers a removed lens", () => {
  const preview = extractFunction(glue, "previewLiquidGlassElementMaterial");
  assert.match(preview, /selectedRow:\[document\.getElementById\("libListSelectedGlass"\)\]/);
  assert.doesNotMatch(preview, /liquidGL\s*\(/, "settings preview only styles existing DOM");
});
