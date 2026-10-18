import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const glue = fs.readFileSync(path.resolve(here, "../../debripod/static/js/liquid-glue.js"), "utf8");
// sfgl is vendored as one bundle; property names and GLSL survive minification.
const sfgl = fs.readFileSync(path.resolve(here, "../../debripod/static/vendor/sfgl/sfgl.iife.js"), "utf8");
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

test("one glass surface draws every lens, including the tilted wheel", () => {
  assert.equal((glue.match(/debripodGlass\.surface\(/g) || []).length, 1);
  for (const group of ["libraryList", "pathPill", "infoPill", "wheel"]) assert.match(glue, new RegExp(`syncGroup\\("${group}"`));
  assert.match(glue, /syncGroup\("listPills"/);
  assert.match(glue, /syncGroup\("selectedRow"/);
  assert.doesNotMatch(glue, /rendererKey/);
  assert.match(glue, /options\.transform = wheelGlassTransform/);
});

function reactiveContext(adapter, frameState) {
  const context = {
    window: {innerWidth: 400, innerHeight: 800, DebriPod: {visualizerRenderer: {sourceForLiquidGL: () => adapter.current}}},
    currentVisualizerFrameState: () => frameState.current,
    Math, Number, Array, String,
  };
  vm.createContext(context);
  const start = glue.indexOf("  var DEBRIPOD_REACTIVE_BACKDROP");
  const end = glue.indexOf("  var debripodWallpaperBackdrop", start);
  vm.runInContext(extractFunction(glue, "finiteOr") + extractFunction(glue, "visualizerSourceAdapter") + glue.slice(start, end) + ";this.provider = debripodReactiveBackdrop;", context);
  return context.provider;
}

test("reactive artwork is keyed by its art identity and drawn from uniforms", () => {
  const image = {src: "a.jpg"};
  const adapter = {current: {ready: true, image, artKey: "album:a"}};
  const frame = {current: {fade: 0.8, active: true, angleRadians: 2.4, bands: [1, 0, 0, 0, 0, 0, 0, 0, 0], lumaLow: 0.1, lumaHigh: 0.9, energy: 0.3, beat: 0}};
  const provider = reactiveContext(adapter, frame);
  const textures = provider.textures();
  assert.equal(textures.dp_art.source, image);
  assert.equal(textures.dp_art.key, "album:a");
  const u = provider.uniforms({timestamp: 1}, {width: 400, height: 800});
  assert.equal(u.dp_hasArt, true);
  assert.equal(u.dp_fade, 0.8);
  assert.equal(u.dp_angle, 2.4);
  assert.equal(u.dp_bands[0], 1);
  assert.equal(provider.dynamic({}), true, "a visible visualizer re-prepares the backdrop every frame (at the tier's rate)");
  assert.match(provider.fragment, /vec4 sfBackdrop\(vec2 uv\)/);
  assert.match(visualizer, /return \{image:visualizerArtField\.image, artKey:/);
});

test("artwork recovers after a temporary unavailable source, including the same album", () => {
  const adapter = {current: {ready: true, image: {}, artKey: "album:a"}};
  const frame = {current: {fade: 0}};
  const provider = reactiveContext(adapter, frame);
  const first = provider.key({});
  adapter.current = {ready: false};
  assert.equal(provider.uniforms({}, {width: 1, height: 1}).dp_hasArt, false, "missing art draws opaque black");
  assert.notEqual(provider.key({}), first);
  adapter.current = {ready: true, image: {}, artKey: "album:a"};
  assert.equal(provider.key({}), first, "the same album returns to the same backdrop");
  assert.equal(provider.uniforms({}, {width: 1, height: 1}).dp_hasArt, true);
  assert.equal(provider.dynamic({}), false, "paused artwork is prepared once, not every frame");
});

test("reactive glass shares crossfade progress with the visualizer", () => {
  const image = {}, previous = {};
  const adapter = {current: {ready: true, image, artKey: "new"}};
  const transition = {active: true, fromImage: previous, fromKey: "old", progress: .25, fromAngle: 7, toAngle: Math.PI};
  const frame = {current: {artTransition: transition, fade: 1}};
  const provider = reactiveContext(adapter, frame);
  let u = provider.uniforms({}, {width: 1, height: 1});
  assert.equal(u.dp_artMix, .25);
  assert.equal(u.dp_previousAngle, 7);
  assert.equal(u.dp_angle, Math.PI);
  assert.equal(provider.textures().dp_previousArt.key, "old");
  transition.progress = .75;
  u = provider.uniforms({}, {width: 1, height: 1});
  assert.equal(u.dp_artMix, .75);
  frame.current = {fade: 1, angleRadians: 9};
  u = provider.uniforms({}, {width: 1, height: 1});
  assert.equal(u.dp_artMix, 1);
  assert.equal(u.dp_angle, 9);
});

test("the glass backing scale is a setting and WebGL2 is preferred", () => {
  assert.match(glue, /renderScale: \(\)=> settings\(\)\.glassRenderScale/);
  assert.match(glue, /frost: \(\)=> settings\(\)\.glassFrostSamples/);
  assert.match(sfgl, /getContext\("webgl2"/);
  assert.match(sfgl, /antialias:!1/);
  assert.match(sfgl, /preserveDrawingBuffer:!1/);
});

test("glass composites premultiplied overlap", () => {
  assert.match(sfgl, /blendFunc\(\w+\.ONE,\w+\.ONE_MINUS_SRC_ALPHA\)/);
  assert.match(sfgl, /final\.rgb \*= final\.a/);
  assert.match(visualizer, /visualizerTextureUsesMipmaps/);
});

test("lens geometry: live for moving glass, function for the wheel, DOM-invalidated for row pills", () => {
  const options = extractFunction(glue, "glassLensOptions");
  assert.match(options, /key === "selectedRow"[\s\S]*?options\.geometry = "live"/);
  assert.match(options, /key === "listPills"[\s\S]*?options\.geometry = "dom"/);
  assert.match(options, /key === "wheel"[\s\S]*?options\.geometry = wheelLensLayoutRect/);
});

test("NP teardown removes transient lenses and cancels selection work", () => {
  const groups = [];
  const context = {
    listSelectionMotion: {raf: -1},
    frameScheduler: () => ({cancel(key){ context.cancelled = key; }}),
    cancelAnimationFrame(id){ context.cancelledRaf = id; },
    clearTimeout(id){ context.clearedTimer = id; },
    debripodGlassSurface: () => ({syncGroup(group, elements){ groups.push([group, elements.length]); }}),
    markFrameWork(){},
    pillGlassTargetIds: ["a"],
    document: {getElementById: () => ({style: {}, classList: {remove(){}}}), querySelectorAll: () => []},
  };
  vm.createContext(context);
  vm.runInContext([
    extractFunction(glue, "cancelLibSelectionMotion"),
    extractFunction(glue, "destroyLibSelectionGlass"),
    extractFunction(glue, "destroyLibPillGlassLenses"),
    extractFunction(glue, "destroyTransientListGlass"),
  ].join("\n"), context);
  context.destroyTransientListGlass("now playing");
  assert.deepEqual(groups, [["selectedRow", 0], ["listPills", 0]]);
  assert.equal(context.cancelled, "lib-selection-motion");
  assert.equal(context.listSelectionMotion.raf, 0);
  context.listSelectionMotion.raf = 17;
  context.cancelLibSelectionMotion();
  assert.equal(context.cancelledRaf, 17, "native selection RAF is cancelled too");
});

test("selected-row settings preview never re-registers a removed lens", () => {
  const preview = extractFunction(glue, "previewLiquidGlassElementMaterial");
  assert.match(preview, /selectedRow:\[document\.getElementById\("libListSelectedGlass"\)\]/);
  assert.doesNotMatch(preview, /syncGroup|\.lens\(/, "settings preview only updates existing lenses");
});

test("app frames only ask the engine to draw; the engine draws once per frame", () => {
  const scheduler = {mark(){}};
  let requested = 0;
  const context = {window: {DebriPod: {frameScheduler: scheduler}}, glassRequestRender: () => { requested++; }};
  vm.createContext(context);
  vm.runInContext(extractFunction(glue, "frameScheduler") + extractFunction(glue, "renderLiquidGlassNow") + extractFunction(glue, "renderLiquidGlassVisualizerSourceNow"), context);
  assert.equal(context.frameScheduler(), scheduler);
  context.renderLiquidGlassNow({timestamp: 100});
  context.renderLiquidGlassVisualizerSourceNow({timestamp: 100});
  assert.equal(requested, 2);
});

test("selection motion writes its foreground variables to the list, not :root, and only when they change", () => {
  const writes = [];
  const list = {style: {setProperty: (k, v) => writes.push([k, v])}};
  const context = {listSelectionMotion: {foregroundProgress: 0.5}, document: {getElementById: () => list, documentElement: {style: {setProperty(){ throw new Error("root write"); }}}}, Math, Object};
  vm.createContext(context);
  const start = glue.indexOf("  var libSelectionForegroundWritten");
  vm.runInContext(glue.slice(start, glue.indexOf("\n  }", glue.indexOf("function applyLibSelectionForeground", start)) + 4), context);
  context.applyLibSelectionForeground();
  const first = writes.length;
  assert.equal(first, 5);
  context.applyLibSelectionForeground();
  assert.equal(writes.length, first, "unchanged values are not written again");
  context.listSelectionMotion.foregroundProgress = 1;
  context.applyLibSelectionForeground();
  assert.ok(writes.length > first);
});
