import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const settings = fs.readFileSync("debripod/static/js/settings-ui.js", "utf8");
const lists = fs.readFileSync("debripod/static/js/list-view.js", "utf8");

function functionSource(source, name) {
  const match = source.match(new RegExp(`(?:async )?function ${name}\\([^)]*\\)\\{[\\s\\S]*?\\n  \\}`));
  assert.ok(match, `${name} is available`);
  return match[0];
}

test("glass quality cycles every preset and stays in advanced glass settings", async () => {
  const levels = ["auto", "superfluid", "glass", "lite", "frost", "static"];
  const destinations = [];
  let saves = 0;
  let invalidations = 0;
  const root = {uiSettings: {GLASS_QUALITY_LEVELS: levels}, glass: {instance: {invalidate: () => invalidations++}}};
  const context = {
    state: {}, uiSettings: {glassQuality: "auto"}, window: {DebriPod: root}, DebriPod: root,
    saveUiSettings: () => saves++,
    viewLibAdvancedCategory: async (category, push) => destinations.push([category, push]),
    viewLibUiSettings: () => assert.fail("glass quality must not open Visualizer"),
  };
  vm.runInNewContext(functionSource(settings, "handleLibUiAction"), context);
  for (const expected of [...levels.slice(1), "auto"]) {
    assert.equal(await context.handleLibUiAction("cycle_glass_quality"), true);
    assert.equal(context.uiSettings.glassQuality, expected);
  }
  assert.deepEqual(destinations, levels.map(() => ["glass", false]));
  assert.equal(saves, levels.length);
  assert.equal(invalidations, levels.length);
});
