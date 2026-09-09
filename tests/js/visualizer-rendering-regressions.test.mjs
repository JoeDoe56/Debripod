import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const visualizerPath = path.resolve(here, "../../debripod/static/js/visualizer-engine.js");
const liquidPath = path.resolve(here, "../../debripod/static/liquidGL.js");
const gluePath = path.resolve(here, "../../debripod/static/js/liquid-glue.js");
const ambientPath = path.resolve(here, "../../debripod/static/js/video-ambient.js");
const palettePath = path.resolve(here, "../../debripod/static/js/palette-utils.js");
const visualizer = fs.readFileSync(visualizerPath, "utf8");
const liquid = fs.readFileSync(liquidPath, "utf8");
const glue = fs.readFileSync(gluePath, "utf8");
const ambient = fs.readFileSync(ambientPath, "utf8");
const palette = fs.readFileSync(palettePath, "utf8");

function loadHelpers(names) {
  const snippets = names.map((name) => {
    const match = visualizer.match(new RegExp(`function ${name}\\([^)]*\\)\\{[\\s\\S]*?\\n\\}`));
    assert.ok(match, `${name} must remain independently testable`);
    return match[0];
  });
  const context = {Math, Number, Array, encodeURIComponent};
  vm.createContext(context);
  vm.runInContext(snippets.join("\n"), context, {filename: visualizerPath});
  return context;
}

test("visualizer uses a capped HiDPI backing store and versioned art URL", () => {
  const {visualizerBackingSize, visualizerArtUrlWithCacheBust} = loadHelpers([
    "visualizerBackingSize", "visualizerArtUrlWithCacheBust"
  ]);
  const backing = visualizerBackingSize(430, 932, 3);
  assert.equal(backing.cssWidth, 430);
  assert.equal(backing.cssHeight, 932);
  assert.equal(backing.width, 860);
  assert.equal(backing.height, 1864);
  assert.equal(backing.dpr, 2);
  const url = visualizerArtUrlWithCacheBust("/media/art.jpg", {
    cache_key: "cache-7", art_identity: "art-7", algorithm_version: 1, width: 512, height: 512
  });
  assert.match(url, /^\/media\/art\.jpg\?dp_art=/);
  assert.match(url, /cache-7%3Aart-7%3A1%3A512%3A512/);
});

test("glass reactive sampling matches the background transform and stays premultiplied", () => {
  assert.match(liquid, /vec2 backgroundUv = vec2\(clamp\(uv\.x, 0\.0, 1\.0\), 1\.0 - clamp\(uv\.y, 0\.0, 1\.0\)\)/);
  const premultiply = liquid.indexOf("final.rgb *= final.a");
  const coverage = liquid.indexOf("final.rgb *= inShape");
  assert.ok(premultiply >= 0 && coverage > premultiply, "source alpha must be premultiplied before edge coverage");
  assert.doesNotMatch(liquid, /final\.rgb \*= u_revealProgress/);
  assert.match(visualizer, /float alpha=opacity\*fade;gl_FragColor=vec4\(rgb\*alpha,alpha\)/);

  const reactiveUv = ([u, v], angle, width, height) => {
    const x = (u - 0.5) * width;
    const y = (1 - v - 0.5) * height;
    const c = Math.cos(angle), s = Math.sin(angle), side = Math.hypot(width, height);
    return [((c * x + s * y) / side) + 0.5, ((-s * x + c * y) / side) + 0.5];
  };
  const backgroundUv = ([u, v], angle, width, height) => {
    const x = (u - 0.5) * width;
    const y = (v - 0.5) * height;
    const c = Math.cos(angle), s = Math.sin(angle), side = Math.hypot(width, height);
    return [((c * x + s * y) / side) + 0.5, ((-s * x + c * y) / side) + 0.5];
  };
  assert.deepEqual(reactiveUv([0.25, 0.75], 0.37, 430, 932), backgroundUv([0.25, 0.25], 0.37, 430, 932));
  const source = [0.8, 0.4, 0.2], alpha = 0.5, shape = 0.5;
  assert.deepEqual(source.map(channel => channel * alpha * shape), [0.2, 0.1, 0.05]);
  assert.equal(alpha * shape, 0.25);
  const reveal = 0.5;
  assert.deepEqual(source.map(channel => channel * alpha * reveal * shape), [0.1, 0.05, 0.025]);
  assert.equal(alpha * reveal * shape, 0.125);
});

test("grayscale source samples softly exclude clipped luma and keep glass coverage opaque", () => {
  const {visualizerBandLumaEligibility, visualizerReactiveSourcePixel} = loadHelpers([
    "clamp01", "visualizerBandLumaEligibility", "visualizerReactiveSourcePixel"
  ]);
  assert.equal(visualizerBandLumaEligibility(0), 0);
  assert.equal(visualizerBandLumaEligibility(0.04), 0);
  assert.equal(visualizerBandLumaEligibility(1), 0);
  assert.equal(visualizerBandLumaEligibility(0.96), 0);
  assert.equal(visualizerBandLumaEligibility(0.5), 1);
  assert.ok(visualizerBandLumaEligibility(0.06) < visualizerBandLumaEligibility(0.5));
  assert.ok(visualizerBandLumaEligibility(0.94) < visualizerBandLumaEligibility(0.5));

  assert.deepEqual(
    {...visualizerReactiveSourcePixel([0.8, 0.4, 0.2], 0.5, 0.5)},
    {r:0.2, g:0.1, b:0.05, a:1}
  );
  assert.deepEqual(
    {...visualizerReactiveSourcePixel([0.8, 0.4, 0.2], 0.5, 0)},
    {r:0, g:0, b:0, a:1}
  );
  assert.match(liquid, /color\.rgb \*= opacity \* u_reactiveFade/);
  assert.match(liquid, /color\.a = 1\.0/);
  assert.match(visualizer, /smoothstep\(0\.04,0\.10,luma\)/);
});

test("Now Playing suppresses selected-row glass and opaque zero-opacity lenses", () => {
  assert.match(glue, /if\(list\.hasAttribute\("aria-hidden"\) \|\| nowPlayingSurfaceVisible\(\)\)/);
  assert.match(glue, /Number\(style\.opacity \|\| 1\) <= 0\.01/);
  assert.match(liquid, /style\.display === "none" \|\| style\.visibility === "hidden" \|\| Number\(style\.opacity \|\| 1\) <= 0\.01/);
});

test("paused video cannot restart ambient sampling", () => {
  const match = ambient.match(/function canSampleVideoAmbient\([^)]*\)\{[\s\S]*?\n  \}/);
  assert.ok(match, "canSampleVideoAmbient must remain independently testable");
  const context = {Boolean};
  vm.createContext(context);
  vm.runInContext(match[0], context, {filename: ambientPath});
  const video = {paused: false, ended: false, readyState: 3, src: "track.mp4"};
  assert.equal(context.canSampleVideoAmbient(video, true), true);
  video.paused = true;
  assert.equal(context.canSampleVideoAmbient(video, true), false);
  video.paused = false;
  assert.equal(context.canSampleVideoAmbient(video, false), false);
});

test("selected row stays white across changing visualizer artwork", () => {
  const start = visualizer.indexOf("function applySelectedTextContrast()");
  const end = visualizer.indexOf("function visualizerShouldShow()", start);
  const colors = new Map();
  const context = {document:{documentElement:{style:{setProperty:(key,value)=>colors.set(key,value)}}}};
  vm.createContext(context);
  vm.runInContext(visualizer.slice(start,end), context);
  context.applySelectedTextContrast();
  assert.equal(colors.get("--lib-selected-render-contrast"), "#ffffff");
  assert.equal(colors.get("--lib-selected-pill-render-contrast"), "#ffffff");
});
