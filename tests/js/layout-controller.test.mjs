import assert from "node:assert/strict";
import {createRequire} from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const {chooseLayout, normalWheelWellLayout, mediaBox, stableViewportChange, createBrowserController} = require("../../debripod/static/js/layout-controller.js");

const rect = (left, top, width, height) => ({left, top, right: left + width, bottom: top + height, width, height});
const base = {
  wheel: rect(100, 500, 220, 220),
  screen: rect(70, 70, 280, 280),
  pathPill: rect(80, 20, 260, 36),
  infoPill: rect(80, 370, 260, 60),
  viewport: rect(0, 0, 430, 760),
  padding: 8,
};

test("fitting geometry selects wheel layout", () => {
  assert.equal(chooseLayout(base), "layoutWheel");
});

test("a full-width screen with correctly gapped pills and wheel still fits", () => {
  const viewport = rect(0, 0, 430, 760);
  const geometry = {
    ...base,
    viewport,
    padding: 6,
    screen: rect(0, 60, 430, 280),
    wheel: rect(105, 484, 220, 270),
    pathPill: rect(80, 6, 260, 36),
    infoPill: rect(80, 348, 260, 42),
  };
  assert.equal(chooseLayout(geometry), "layoutWheel");
});

test("normal wheel layout reserves a square screen with g on each side", () => {
  assert.deepEqual(normalWheelWellLayout(
    rect(0, 0, 390, 844), rect(12, 6, 366, 30), 42, 6,
  ), {
    wheelWellSize: 376,
    screenTop: 42,
    infoBottom: 468,
    screenHeight: 378,
    fits: true,
  });
});

test("normal wheel layout expands when the stack and square wheel well do not fit", () => {
  const layout = normalWheelWellLayout(rect(0, 0, 844, 390), rect(12, 6, 820, 30), 42, 6);
  assert.equal(layout.wheelWellSize, -532);
  assert.equal(layout.screenHeight, 832);
  assert.equal(layout.fits, false);
});

test("a centered wheel may meet both side edges without forcing expansion", () => {
  const geometry = {
    ...base,
    viewport: rect(0, 0, 280, 720),
    padding: 6,
    screen: rect(0, 42, 280, 280),
    wheel: rect(0, 434, 280, 280),
    pathPill: rect(108, 6, 64, 30),
    infoPill: rect(12, 328, 256, 42),
  };
  assert.equal(chooseLayout(geometry), "layoutWheel");
});

test("collisions and viewport overflow select expanded layout", () => {
  assert.equal(chooseLayout({...base, wheel: rect(100, 330, 220, 220)}), "layoutExpanded");
  assert.equal(chooseLayout({...base, wheel: rect(100, 40, 220, 220)}), "layoutExpanded");
  assert.equal(chooseLayout({...base, infoPill: rect(110, 650, 200, 80)}), "layoutExpanded");
  assert.equal(chooseLayout({...base, wheel: rect(300, 500, 220, 220)}), "layoutExpanded");
});

test("subpixel overlap below one pixel is tolerated", () => {
  const geometry = {...base, screen: rect(70, 70, 280, 280), wheel: rect(100, 349.5, 220, 220), infoPill: rect(80, 580, 260, 42), padding: 0};
  assert.equal(chooseLayout(geometry, 1), "layoutWheel");
});

test("image media is square and video uses the full box", () => {
  assert.deepEqual(mediaBox("image", {width: 500, height: 300}), {width: 300, height: 300});
  assert.deepEqual(mediaBox("video", {width: 500, height: 300}), {width: 500, height: 300});
});

test("pinch zoom and software keyboard preserve stable viewport geometry", () => {
  const stable = {width:390, height:844};
  assert.equal(stableViewportChange(stable, {width:390, height:520}, {keyboardOpen:true}), stable);
  assert.equal(stableViewportChange(stable, {width:260, height:560}, {zoomed:true}), stable);
  assert.equal(stableViewportChange(stable, {width:390, height:810}, {touchViewport:true}), stable);
  assert.deepEqual(stableViewportChange(stable, {width:844, height:390}, {force:true}), {width:844, height:390});
});

test("fullscreen entry and exit recapture the touch viewport, including a delayed resize", () => {
  const documentEvents = new Map(), windowEvents = new Map(), frames = new Map(), styles = new Map();
  let nextFrame = 0;
  const root = {clientWidth:360, clientHeight:640, classList:{toggle() {}}, style:{setProperty:(key, value) => styles.set(key, value)}};
  const doc = {documentElement:root, readyState:"complete", querySelector:() => null, getElementById:() => null,
    addEventListener:(event, handler) => documentEvents.set(event, handler)};
  const win = {document:doc, navigator:{maxTouchPoints:1}, visualViewport:{scale:1},
    addEventListener:(event, handler) => windowEvents.set(event, handler),
    requestAnimationFrame:handler => { frames.set(++nextFrame, handler); return nextFrame; },
    cancelAnimationFrame:key => frames.delete(key)};
  function flush() {
    for(let i = 0; frames.size && i < 10; i++) {
      const pending = [...frames.values()]; frames.clear(); pending.forEach(handler => handler());
    }
  }
  createBrowserController(win);
  flush();
  assert.equal(styles.get("--stable-viewport-height"), "640px");
  root.clientHeight = 600;
  windowEvents.get("resize")(); flush();
  assert.equal(styles.get("--stable-viewport-height"), "640px", "browser chrome still leaves the layout stable");
  documentEvents.get("fullscreenchange")();
  root.clientHeight = 740;
  windowEvents.get("resize")(); flush();
  assert.equal(styles.get("--stable-viewport-height"), "740px", "fullscreen uses the extra height");
  root.clientHeight = 640;
  windowEvents.get("resize")();
  documentEvents.get("fullscreenchange")(); flush();
  assert.equal(styles.get("--stable-viewport-height"), "640px", "exiting fullscreen restores the layout");
});
