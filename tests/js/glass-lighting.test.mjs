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

function load({permission, stored, motionMultiplier = 1} = {}) {
  const saved = new Map();
  if(stored) saved.set("debripod_glass_orientation_permission:v1:alice", stored);
  const documentListeners = new Map();
  const windowListeners = new Map();
  let permissionCalls = 0;
  const tilts = [];
  const css = new Map();
  const localStorage = {getItem:(key)=>saved.get(key) || null, setItem:(key, value)=>saved.set(key, String(value))};
  const window = {
    DebriPod: {frameScheduler:{mark:()=>{}}, uiSettings:{settings:{glassInteractionFps:60, glassMotionEffectMultiplier:motionMultiplier}}},
    DEBRIPOD_DEVICE_SETTINGS_USER_ID: "alice",
    localStorage,
    innerWidth: 400,
    innerHeight: 800,
    addEventListener:(name, fn)=>windowListeners.set(name, fn),
    DeviceOrientationEvent: permission === undefined ? {} : {requestPermission:()=>{ permissionCalls += 1; return typeof permission === "function" ? permission() : Promise.resolve(permission); }},
    wheelRotationMaxDegrees: 10,
    setWheelTiltTarget:(x,y)=>tilts.push({x,y})
  };
  const document = {documentElement:{style:{setProperty:(key,value)=>css.set(key,value)}}, hidden:false, addEventListener:(name, fn)=>documentListeners.set(name, fn), removeEventListener:(name)=>documentListeners.delete(name)};
  const context = {window, document, localStorage, performance:{now:()=>0}, Date, Math, Number, Promise, setTimeout, clearTimeout, requestAnimationFrame:()=>1};
  vm.createContext(context);
  vm.runInContext(source, context, {filename:sourcePath});
  return {api:window.DebriPod.glassLighting, documentListeners, windowListeners, saved, tilts, css, permissionCalls:()=>permissionCalls};
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

test("direct orientation updates lighting without foreground displacement and settles", () => {
  const fixture = load();
  fixture.windowListeners.get("deviceorientation")({beta:60, gamma:0});
  fixture.windowListeners.get("deviceorientation")({beta:20, gamma:-14});
  fixture.api.testing.step(20);
  const oriented = fixture.api.state();
  assert.equal(oriented.source, "orientation");
  assert.ok(oriented.x < -0.16);
  assert.equal(fixture.tilts.length, 0, "device motion does not double-apply wheel tilt");
  assert.equal(fixture.api.parallax, undefined);
  assert.equal(fixture.css.size, 0);
  for(let tick = 40; tick < 1800; tick += 20) fixture.api.testing.step(tick);
  assert.equal(fixture.api.testing.isAnimating(), false);
});

test("a remembered grant retries on a gesture and retains pointer fallback until sensor data", async () => {
  const fixture = load({permission:"granted", stored:"granted"});
  fixture.api.testing.pointerMove({clientX:400, clientY:0});
  fixture.api.testing.step(20);
  assert.equal(fixture.api.state().source, "pointer");
  assert.equal(fixture.documentListeners.has("touchend"), true);
  assert.equal(fixture.permissionCalls(), 0);
  fixture.documentListeners.get("touchend")();
  await Promise.resolve();
  assert.equal(fixture.permissionCalls(), 1);
  fixture.windowListeners.get("deviceorientation")({beta:0, gamma:0});
  fixture.windowListeners.get("deviceorientation")({beta:45, gamma:45});
  fixture.api.testing.step(40);
  assert.equal(fixture.api.state().source, "orientation");
  assert.equal(fixture.api.parallax, undefined);
  assert.equal(fixture.css.size, 0);
});

test("explicit motion retry can re-request a saved grant only before valid sensor data", async () => {
  const fixture = load({permission:"granted", stored:"granted"});
  assert.equal(fixture.permissionCalls(), 0);
  assert.equal(await fixture.api.requestOrientationPermission(), "granted");
  assert.equal(fixture.permissionCalls(), 1);
  assert.equal(await fixture.api.requestOrientationPermission(true), "granted");
  assert.equal(fixture.permissionCalls(), 1);
  fixture.windowListeners.get("deviceorientation")({beta:0, gamma:0});
  fixture.windowListeners.get("deviceorientation")({beta:15, gamma:15});
  assert.equal(await fixture.api.requestOrientationPermission(true), "granted");
  assert.equal(fixture.permissionCalls(), 1);
});

test("the motion-effect multiplier scales device light without adding displacement", () => {
  const full = load({motionMultiplier:1});
  full.windowListeners.get("deviceorientation")({beta:0, gamma:0});
  full.windowListeners.get("deviceorientation")({beta:22.5, gamma:22.5});
  full.api.testing.step(20);
  const half = load({motionMultiplier:0.5});
  half.windowListeners.get("deviceorientation")({beta:0, gamma:0});
  half.windowListeners.get("deviceorientation")({beta:22.5, gamma:22.5});
  half.api.testing.step(20);
  const lightRatio = Math.abs((half.api.state().x + 0.16) / (full.api.state().x + 0.16));

  assert.ok(Math.abs(lightRatio - 0.5) < 0.01, `lighting ratio was ${lightRatio}`);
  assert.equal(full.css.size,0);
  assert.equal(half.css.size,0);
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

test("light uniforms stay independent from wheel interaction tilt", () => {
  assert.match(liquidSource, /u_globalLight/);
  assert.match(liquidSource, /setGlobalLighting\(state\)/);
  assert.match(liquidSource, /_shadowValue\(strength\)/);
  assert.match(glueSource, /wheel\.style\.transform/);
  assert.doesNotMatch(source, /window\.setWheelTiltTarget|getBoundingClientRect/);
  assert.doesNotMatch(source, /setParallaxTarget|--dp-parallax/);
});

test("device tilt sweeps the light through all quadrants with a short damping time",()=>{
  for(const [beta,gamma] of [[35,35],[35,-35],[-35,35],[-35,-35]]){
    const f=load();
    f.api.testing.orientationChange({beta:0,gamma:0});
    f.api.testing.orientationChange({beta,gamma});
    for(let t=20;t<=200;t+=20)f.api.testing.step(t);
    assert.equal(Math.sign(f.api.state().x),Math.sign(gamma));
    assert.equal(Math.sign(f.api.state().y),Math.sign(beta));
    assert.ok(f.api.state().intensity>.9);
  }
});

test("device tilt keeps diagonal motion below the saturated cardinal clamp",()=>{
  const f=load();
  f.api.testing.orientationChange({beta:0,gamma:0});
  f.api.testing.orientationChange({beta:35,gamma:35});
  for(let t=20;t<=200;t+=20)f.api.testing.step(t);
  const state=f.api.state();
  assert.ok(state.x > -0.16 && state.x < 1, `x saturated: ${state.x}`);
  assert.ok(state.y > -0.22 && state.y < 1, `y saturated: ${state.y}`);
});

test("strong diagonal device tilt preserves direction without rectangular clamping",()=>{
  const f=load({motionMultiplier:2});
  f.api.testing.orientationChange({beta:0,gamma:0});
  f.api.testing.orientationChange({beta:45,gamma:45});
  for(let t=20;t<=200;t+=20)f.api.testing.step(t);
  const state=f.api.state();
  assert.ok(Math.abs(state.x) < 1 && Math.abs(state.y) < 1);
  assert.ok(Math.sign(state.x + 0.16) === Math.sign(state.y + 0.22));
});

test("large unequal tilts retain their angle instead of clipping a component",()=>{
  const f=load({motionMultiplier:2});
  f.api.testing.orientationChange({beta:0,gamma:0});
  f.api.testing.orientationChange({beta:20,gamma:60});
  for(let t=20;t<=1000;t+=20)f.api.testing.step(t);
  const state=f.api.state();
  const x=-.16+2.3*Math.sin(Math.PI/3),y=-.22+2.3*Math.sin(Math.PI/9);
  assert.ok(Math.hypot(state.x,state.y)<1);
  assert.ok(Math.abs(Math.atan2(state.y,state.x)-Math.atan2(y,x))<.001);
});
