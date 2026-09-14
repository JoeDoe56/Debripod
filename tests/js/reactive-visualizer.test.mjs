import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const sourcePath = path.resolve(here, "../../debripod/static/js/visualizer-engine.js");
const source = fs.readFileSync(sourcePath, "utf8");

function load(names) {
  const snippets = names.map((name) => {
    const match = source.match(new RegExp(`function ${name}\\([^)]*\\)\\{[\\s\\S]*?\\n\\}`));
    assert.ok(match, `${name} must remain independently testable`);
    return match[0];
  });
  const context = {Math, Number, Array, Float32Array, Infinity};
  vm.createContext(context);
  vm.runInContext(snippets.join("\n"), context, {filename: sourcePath});
  return context;
}

test("rotation is exactly three deterministic clockwise turns across a track by default", () => {
  const {clamp01, visualizerRotationForProgress} = load(["clamp01", "visualizerRotationForProgress"]);
  const pi = Math.PI;
  assert.equal(visualizerRotationForProgress(0), pi);
  assert.equal(visualizerRotationForProgress(0.25), 2.5 * pi);
  assert.equal(visualizerRotationForProgress(0.5), 4 * pi);
  assert.equal(visualizerRotationForProgress(0.75), 5.5 * pi);
  assert.equal(visualizerRotationForProgress(1), 7 * pi);
  assert.equal(visualizerRotationForProgress(0.5), visualizerRotationForProgress(0.5));
  assert.equal(clamp01(1.2), 1);
});

test("configured rotation count starts upside down and is integer bounded", () => {
  const {clamp01, normalizeVisualizerRotationsPerTrack, visualizerRotationForProgress} = load([
    "clamp01", "normalizeVisualizerRotationsPerTrack", "visualizerRotationForProgress"
  ]);
  const pi = Math.PI;
  assert.equal(normalizeVisualizerRotationsPerTrack(undefined), 3);
  assert.equal(normalizeVisualizerRotationsPerTrack(3.8), 4);
  assert.equal(normalizeVisualizerRotationsPerTrack(99), 12);
  assert.equal(visualizerRotationForProgress(0, 3), pi);
  assert.equal(visualizerRotationForProgress(1, 3), 7 * pi);
});

test("active high band owns the brightest useful luma and low-only spans the field", () => {
  const {clamp01, normalizeActiveBands, buildVisualizerBandLumaMap, visualizerBandWeightsAtLuma, visualizerResponseForLuma} = load([
    "clamp01", "normalizeActiveBands", "buildVisualizerBandLumaMap", "visualizerBandWeightsAtLuma", "visualizerResponseForLuma"
  ]);
  const full = buildVisualizerBandLumaMap([true, true, true, true, true, true, true, true, true]);
  const bright = visualizerBandWeightsAtLuma(1, full);
  assert.equal(bright.indexOf(Math.max(...bright)), 8);

  const lowOnly = buildVisualizerBandLumaMap([true, false, false, false, false, false, false, false, false]);
  const lowBands = [1, 0, 0, 0, 0, 0, 0, 0, 0];
  assert.equal(visualizerResponseForLuma(0.98, lowBands, lowOnly), 1);
  assert.equal(visualizerResponseForLuma(0.02, lowBands, lowOnly), 1);
});

test("adjacent luma bands overlap smoothly instead of stepping", () => {
  const {clamp01, normalizeActiveBands, buildVisualizerBandLumaMap, visualizerBandWeightsAtLuma, visualizerResponseForLuma} = load([
    "clamp01", "normalizeActiveBands", "buildVisualizerBandLumaMap", "visualizerBandWeightsAtLuma", "visualizerResponseForLuma"
  ]);
  const mapping = buildVisualizerBandLumaMap([true, true, true, true, true, true, true, true, true]);
  const bands = [0, .1, .2, .3, .4, .5, .6, .7, .8];
  const before = visualizerResponseForLuma(0.49, bands, mapping);
  const center = visualizerResponseForLuma(0.50, bands, mapping);
  const after = visualizerResponseForLuma(0.51, bands, mapping);
  assert.ok(Math.abs(center - before) < 0.04);
  assert.ok(Math.abs(after - center) < 0.04);
});

test("frequency, energy, and beat settings independently affect their selected channel", () => {
  const {clamp01, visualizerResponseChannels} = load(["clamp01", "visualizerResponseChannels"]);
  const base = visualizerResponseChannels(0, 0, 0, {});
  const freq = visualizerResponseChannels(1, 0, 0, {frequency:{brightness:.5}});
  const energy = visualizerResponseChannels(0, 1, 0, {energy:{opacity:.1}});
  const beat = visualizerResponseChannels(0, 0, 1, {beat:{contrast:.25}});
  assert.ok(freq.brightness > base.brightness);
  assert.equal(freq.opacity, base.opacity);
  assert.ok(energy.opacity > base.opacity);
  assert.equal(energy.brightness, base.brightness);
  assert.ok(beat.contrast > base.contrast);
  assert.equal(beat.saturation, base.saturation);
});

test("black fade scheduling stops once the final black frame has been drawn", () => {
  const {visualizerShouldSchedule} = load(["visualizerShouldSchedule"]);
  assert.equal(visualizerShouldSchedule(0, 0, false), false);
  assert.equal(visualizerShouldSchedule(.01, 0, false), true);
  assert.equal(visualizerShouldSchedule(0, 1, false), true);
  assert.equal(visualizerShouldSchedule(0, 0, true), true);
});
