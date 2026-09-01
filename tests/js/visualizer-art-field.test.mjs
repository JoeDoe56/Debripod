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
  const matches = ["clamp01", "normalizeVisualizerArtLuma", "visualizerArtRotationOverscan", "rotatedVisualizerArtUv"].map((name) => {
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
