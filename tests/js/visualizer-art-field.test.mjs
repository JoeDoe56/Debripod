import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const sourcePath = path.resolve(here, "../../debripod/static/js/visualizer-engine.js");
const source = fs.readFileSync(sourcePath, "utf8");

function loadHelpers() {
  const matches = ["clamp01", "visualizerBandLumaEligibility", "normalizeVisualizerArtLuma", "visualizerArtRotationOverscan", "rotatedVisualizerArtUv"].map((name) => {
    const match = source.match(new RegExp(`function ${name}\\([^)]*\\)\\{[\\s\\S]*?\\n\\}`));
    assert.ok(match, `${name} must remain independently testable`);
    return match[0];
  });
  const context = {Math, Number, isFinite};
  vm.createContext(context);
  vm.runInContext(matches.join("\n"), context, {filename: sourcePath});
  return context;
}

test("extreme-blur luma fields normalize their P3/P97 range", () => {
  const {normalizeVisualizerArtLuma} = loadHelpers();
  assert.equal(normalizeVisualizerArtLuma(0.18, 0.18, 0.81), 0);
  assert.equal(normalizeVisualizerArtLuma(0.81, 0.18, 0.81), 1);
  assert.ok(normalizeVisualizerArtLuma(0.50, 0.18, 0.81) > 0.49);
});

test("cover-specific color ranges retain dark and bright colors without reacting to pure black or white", () => {
  const {visualizerBandLumaEligibility: eligible} = loadHelpers();
  assert.equal(eligible(0.025, 0.025, 0.11), 1);
  assert.equal(eligible(0.98, 0.90, 0.98), 1);
  for (const [low, high] of [[0, 1], [0.025, 0.11], [0.90, 0.98], [0.2, 0.8]]) {
    assert.equal(eligible(0, low, high), 0);
    assert.equal(eligible(1, low, high), 0);
  }
  assert.equal(eligible(0.025), 0);
  assert.equal(eligible(0.98), 0);
  assert.equal(eligible(0.5, 0.2, 0.8), 1);
  assert.ok(Math.abs(eligible(0.07) - 0.5) < 1e-10);
  assert.ok(Math.abs(eligible(0.93) - 0.5) < 1e-10);
});

test("rotated square field has enough overscan for every viewport corner", () => {
  const {visualizerArtRotationOverscan, rotatedVisualizerArtUv} = loadHelpers();
  assert.ok(visualizerArtRotationOverscan(430, 932) > 1);
  for(const angle of [0, Math.PI / 7, Math.PI / 4, Math.PI * 0.81, Math.PI * 1.4]) {
    for(const [u, v] of [[0, 0], [1, 0], [0, 1], [1, 1]]) {
      const sample = rotatedVisualizerArtUv(u, v, angle, 430, 932);
      assert.ok(sample.u >= 0 && sample.u <= 1);
      assert.ok(sample.v >= 0 && sample.v <= 1);
    }
  }
});
