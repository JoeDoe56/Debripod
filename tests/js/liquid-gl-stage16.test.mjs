import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const glue = fs.readFileSync(path.resolve(here, "../../debripod/static/js/liquid-glue.js"), "utf8");
const liquid = fs.readFileSync(path.resolve(here, "../../debripod/static/liquidGL.js"), "utf8");
const visualizer = fs.readFileSync(path.resolve(here, "../../debripod/static/js/visualizer-engine.js"), "utf8");

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
});
