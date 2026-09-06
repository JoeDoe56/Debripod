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

function load({permission, stored} = {}) {
  const saved = new Map();
  if(stored) saved.set("debripod_glass_orientation_permission:v1:alice", stored);
  const documentListeners = new Map();
  const windowListeners = new Map();
  let permissionCalls = 0;
  const tilts = [];
  const localStorage = {getItem:(key)=>saved.get(key) || null, setItem:(key, value)=>saved.set(key, String(value))};
  const window = {
    DebriPod: {frameScheduler:{mark:()=>{}}, uiSettings:{settings:{glassInteractionFps:60}}},
    DEBRIPOD_DEVICE_SETTINGS_USER_ID: "alice",
    localStorage,
    innerWidth: 400,
    innerHeight: 800,
    addEventListener:(name, fn)=>windowListeners.set(name, fn),
    DeviceOrientationEvent: permission === undefined ? {} : {requestPermission:()=>{ permissionCalls += 1; return typeof permission === "function" ? permission() : Promise.resolve(permission); }}
  };
  const document = {hidden:false, addEventListener:(name, fn)=>documentListeners.set(name, fn), removeEventListener:(name)=>documentListeners.delete(name)};
  const context = {window, document, localStorage, setWheelTiltTarget:(x,y)=>tilts.push({x,y}), performance:{now:()=>0}, Date, Math, Number, Promise, setTimeout, clearTimeout, requestAnimationFrame:()=>1};
  vm.createContext(context);
  vm.runInContext(source, context, {filename:sourcePath});
  return {api:window.DebriPod.glassLighting, documentListeners, windowListeners, saved, tilts, permissionCalls:()=>permissionCalls};
}

test("orientation permission is prompted once and a denial keeps pointer fallback available", async () => {
  const fixture = load({permission:"denied"});
  fixture.documentListeners.get("touchend")();
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
  fixture.windowListeners.get("deviceorientation")({beta:60, gamma:0});
  fixture.windowListeners.get("deviceorientation")({beta:20, gamma:-14});
  fixture.api.testing.step(20);
  const oriented = fixture.api.state();
  assert.equal(oriented.source, "orientation");
  assert.ok(oriented.x < -0.16);
  assert.ok(fixture.tilts.length > 0);
  assert.notEqual(fixture.tilts.at(-1).y, 0);
  for(let tick = 40; tick < 1800; tick += 20) fixture.api.testing.step(tick);
  assert.equal(fixture.api.testing.isAnimating(), false);
});

test("a remembered grant requests session permission and retains pointer fallback until sensor data", async () => {
  const fixture = load({permission:"granted", stored:"granted"});
  fixture.api.testing.pointerMove({clientX:400, clientY:0});
  fixture.api.testing.step(20);
  assert.equal(fixture.api.state().source, "pointer");
  fixture.documentListeners.get("touchend")();
  await Promise.resolve();
  assert.equal(fixture.permissionCalls(), 1);
});

test("null sensor readings do not disable fallback and activation errors are retryable", async () => {
  const fixture = load({permission:()=>Promise.reject(new Error("activation required"))});
  await fixture.api.requestOrientationPermission();
  assert.equal(fixture.api.testing.storedPermission(), "unknown");
  await fixture.api.requestOrientationPermission();
  assert.equal(fixture.permissionCalls(), 2);
  fixture.api.testing.orientationChange({beta:null, gamma:null});
  fixture.api.testing.pointerMove({clientX:400, clientY:0});
  fixture.api.testing.step(20);
  assert.equal(fixture.api.state().source, "pointer");
});

test("a prior denial is retried only by an explicit motion action", async () => {
  const fixture = load({permission:"granted", stored:"denied"});
  assert.equal(fixture.documentListeners.has("touchend"), false);
  assert.equal(await fixture.api.requestOrientationPermission(), "denied");
  assert.equal(fixture.permissionCalls(), 0);
  assert.equal(await fixture.api.requestOrientationPermission(true), "granted");
  assert.equal(fixture.permissionCalls(), 1);
});

test("light uniforms alter highlights and shadows while only the wheel retains geometry tilt", () => {
  assert.match(liquidSource, /u_globalLight/);
  assert.match(liquidSource, /setGlobalLighting\(state\)/);
  assert.match(liquidSource, /_shadowValue\(strength\)/);
  assert.match(glueSource, /wheel\.style\.transform/);
  assert.doesNotMatch(source, /getBoundingClientRect|\.style\./);
});
