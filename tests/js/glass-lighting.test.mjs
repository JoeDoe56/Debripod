import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const sourcePath = path.resolve(here, "../../debripod/static/js/glass-lighting.js");
const source = fs.readFileSync(sourcePath, "utf8");
const liquidSource = fs.readFileSync(path.resolve(here, "../../debripod/static/liquidGL.js"), "utf8");
const glueSource = fs.readFileSync(path.resolve(here, "../../debripod/static/js/liquid-glue.js"), "utf8");

function load({permission} = {}) {
  const saved = new Map();
  const documentListeners = new Map();
  const windowListeners = new Map();
  let permissionCalls = 0;
  const localStorage = {getItem:(key)=>saved.get(key) || null, setItem:(key, value)=>saved.set(key, String(value))};
  const window = {
    DebriPod: {frameScheduler:{mark:()=>{}}, uiSettings:{settings:{glassInteractionFps:60}}},
    DEBRIPOD_DEVICE_SETTINGS_USER_ID: "alice",
    localStorage,
    innerWidth: 400,
    innerHeight: 800,
    addEventListener:(name, fn)=>windowListeners.set(name, fn),
    DeviceOrientationEvent: permission === undefined ? {} : {requestPermission:()=>{ permissionCalls += 1; return Promise.resolve(permission); }}
  };
  const document = {hidden:false, addEventListener:(name, fn)=>documentListeners.set(name, fn), removeEventListener:(name)=>documentListeners.delete(name)};
  const context = {window, document, localStorage, performance:{now:()=>0}, Date, Math, Number, Promise, setTimeout, clearTimeout, requestAnimationFrame:()=>1};
  vm.createContext(context);
  vm.runInContext(source, context, {filename:sourcePath});
  return {api:window.DebriPod.glassLighting, documentListeners, windowListeners, saved, permissionCalls:()=>permissionCalls};
}

test("orientation permission is prompted once and a denial keeps pointer fallback available", async () => {
  const fixture = load({permission:"denied"});
  fixture.documentListeners.get("pointerdown")();
  await Promise.resolve();
  await fixture.api.requestOrientationPermission();
  assert.equal(fixture.permissionCalls(), 1);
  assert.equal(fixture.api.testing.storedPermission(), "denied");
  fixture.api.testing.pointerMove({clientX:400, clientY:0});
  fixture.api.testing.step(20);
  assert.equal(fixture.api.state().source, "pointer");
});

test("direct orientation and pointer changes update only the light state and settle", () => {
  const fixture = load();
  fixture.windowListeners.get("deviceorientation")({beta:20, gamma:-14});
  fixture.api.testing.step(20);
  const oriented = fixture.api.state();
  assert.equal(oriented.source, "orientation");
  assert.ok(oriented.x < -0.16);
  for(let tick = 40; tick < 1800; tick += 20) fixture.api.testing.step(tick);
  assert.equal(fixture.api.testing.isAnimating(), false);
});

test("light uniforms alter highlights and shadows while only the wheel retains geometry tilt", () => {
  assert.match(liquidSource, /u_globalLight/);
  assert.match(liquidSource, /setGlobalLighting\(state\)/);
  assert.match(liquidSource, /_shadowValue\(strength\)/);
  assert.match(glueSource, /wheel\.style\.transform/);
  assert.doesNotMatch(source, /getBoundingClientRect|\.style\./);
});
