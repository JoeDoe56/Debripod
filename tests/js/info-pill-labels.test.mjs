import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const sourcePath = path.resolve(here, "../../debripod/static/js/now-playing-ui.js");
const source = fs.readFileSync(sourcePath, "utf8");
const functionMatch = source.match(/function infoPillLabelValues\(mode, volume, progress\)\{[\s\S]*?\n\}/);

test("info-pill labels switch cleanly between playback progress and volume", () => {
  assert.ok(functionMatch, "infoPillLabelValues must remain a standalone label renderer");
  const context = {};
  vm.createContext(context);
  vm.runInContext(functionMatch[0], context, {filename: sourcePath});
  const labels = context.infoPillLabelValues;

  assert.deepEqual({...labels("progress", 0.42, {left: "1:23", center: "AAC", right: "3:45"})}, {left: "1:23", center: "AAC", right: "3:45"});
  assert.deepEqual({...labels("volume", 0.426, {})}, {left: "min", center: "43%", right: "max"});
});
