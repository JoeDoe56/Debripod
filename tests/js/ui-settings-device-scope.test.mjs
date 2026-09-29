import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const sourcePath = path.resolve(here, "../../debripod/static/js/ui-settings.js");
const source = fs.readFileSync(sourcePath, "utf8");
const settingsUiSource = fs.readFileSync(path.resolve(here, "../../debripod/static/js/settings-ui.js"), "utf8");

function makeStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(key, String(value)); },
    removeItem(key) { values.delete(key); },
  };
}

function loadUiSettings(storage) {
  const context = {window: {}, localStorage: storage, setTimeout, clearTimeout};
  vm.createContext(context);
  vm.runInContext(source, context, {filename: sourcePath});
  return context.window.DebriPod.uiSettings;
}

test("legacy local values migrate once into the first immutable user namespace", () => {
  const storage = makeStorage({
    debripod_ui_settings: JSON.stringify({liquidGlassElements: {wheel: {material: 0.73}}}),
  });
  const settings = loadUiSettings(storage);
  const alice = settings.setDeviceSettingsUserId("user-alice");
  assert.equal(alice.liquidGlassElements.wheel.material, 0.73);
  assert.ok(storage.getItem("debripod_device_ui_settings:v3:user-alice"));

  const bob = settings.setDeviceSettingsUserId("user-bob");
  assert.equal(bob.liquidGlassElements.wheel.material, -0.2);
  assert.equal(bob.liquidGlassElements.selectedRow.material, -0.5);
});

test("two users on one browser retain separate device settings", () => {
  const storage = makeStorage();
  const settings = loadUiSettings(storage);
  let alice = settings.setDeviceSettingsUserId("user-alice");
  alice.glassRenderScale = 1.75;
  settings.saveUiSettings(alice);

  let bob = settings.setDeviceSettingsUserId("user-bob");
  bob.glassRenderScale = 0.75;
  settings.saveUiSettings(bob);

  alice = settings.setDeviceSettingsUserId("user-alice");
  assert.equal(alice.glassRenderScale, 1.75);
  bob = settings.setDeviceSettingsUserId("user-bob");
  assert.equal(bob.glassRenderScale, 0.75);
});

test("fresh device has the release visual-quality defaults and no server write path", () => {
  const settings = loadUiSettings(makeStorage());
  const fresh = settings.setDeviceSettingsUserId("fresh-user");
  assert.equal(fresh.glassRenderScale, 1.5);
  assert.equal(fresh.glassRenderScaleVersion, 1);
  assert.equal(fresh.glassFrostSamples, 8);
  assert.equal(fresh.glassIdleFps, 30);
  assert.equal(fresh.glassInteractionFps, 60);
  assert.equal(fresh.glassMotionEffectMultiplier, 1);
  assert.deepEqual({...fresh.visualizerFrequencyResponse}, {brightness: 1, opacity: 0, saturation: 0.15, contrast: 0.1});
  assert.deepEqual({...fresh.visualizerEnergyResponse}, {brightness: 0.12, opacity: 0, saturation: 0.05, contrast: 0.05});
  assert.deepEqual({...fresh.visualizerBeatResponse}, {brightness: 0.1, opacity: 0, saturation: 0, contrast: 0.05});
  assert.doesNotMatch(source, /apiPost\s*\(/);
});

test("motion-effect strength is bounded and retained per device user", () => {
  const settings = loadUiSettings(makeStorage());
  const alice = settings.setDeviceSettingsUserId("user-alice");
  alice.glassMotionEffectMultiplier = 1.75;
  settings.saveUiSettings(alice);
  const bob = settings.setDeviceSettingsUserId("user-bob");
  assert.equal(bob.glassMotionEffectMultiplier, 1);
  bob.glassMotionEffectMultiplier = 99;
  settings.saveUiSettings(bob);
  assert.equal(settings.setDeviceSettingsUserId("user-bob").glassMotionEffectMultiplier, 2);
  assert.equal(settings.setDeviceSettingsUserId("user-alice").glassMotionEffectMultiplier, 1.75);
});

test("motion-effect range editor keeps a friendly label", () => {
  assert.match(settingsUiSource, /glassMotionEffectMultiplier:\"Motion effect\"/);
});

test("repeated settings responses preserve the live device object and transparency", () => {
  const storage = makeStorage();
  const api = loadUiSettings(storage);
  const initial = api.setDeviceSettingsUserId("alice");
  assert.equal(initial.textTransparency, .4);
  initial.textTransparency = .42;
  assert.equal(api.setDeviceSettingsUserId("alice"), initial);
  assert.equal(api.settings.textTransparency, .42);
  api.saveUiSettings(initial);
  assert.equal(loadUiSettings(storage).setDeviceSettingsUserId("alice").textTransparency, .42);
});

test("retired contrast settings migrate to white", () => {
  const api = loadUiSettings(makeStorage());
  assert.equal(api.normalizeTextMode("contrast"), "white");
  assert.equal(api.normalizeTextMode("engraved"), "white");
  assert.equal(api.settings.textModes.selectedRow, "white");
});

test("opacity migration preserves legacy transparency ahead of an injected redesign default", () => {
  for(const [saved, expected] of [
    [{textTransparency:.4}, .4],
    [{textOpacity:.45, textTransparency:.4}, .4],
    [{textOpacity:.45, textTransparency:.45}, .4],
    [{textTransparency:.31}, .31],
    [{textOpacity:.45, textTransparency:.45, textOpacityVersion:1}, .45],
  ]){
    const storage = makeStorage({debripod_ui_settings:JSON.stringify(saved)});
    const api = loadUiSettings(storage);
    const settings = api.setDeviceSettingsUserId("opacity-user");
    assert.equal(settings.textOpacity, expected);
    assert.equal(settings.textTransparency, expected);
    api.saveUiSettings(settings);
    assert.equal(loadUiSettings(storage).setDeviceSettingsUserId("opacity-user").textOpacity, expected);
  }
});
