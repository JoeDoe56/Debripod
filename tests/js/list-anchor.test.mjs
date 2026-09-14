import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const sourcePath = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../debripod/static/js/list-view.js");
const source = fs.readFileSync(sourcePath, "utf8");
const match = source.match(/function resolveListAnchorY\([^)]*\)\{[\s\S]*?\n  \}/);
assert.ok(match, "resolveListAnchorY must remain independently testable");
const context = {};
vm.createContext(context);
vm.runInContext(match[0], context, {filename: sourcePath});

function liveGlassY(glassRect, listRect) {
  return glassRect.top - listRect.top;
}

test("live glass position wins over a stale saved anchor on return", () => {
  const live = liveGlassY({top: 430}, {top: 180});
  assert.equal(live, 250);
  assert.equal(context.resolveListAnchorY(live, 100, 90), 250);
});

test("saved and entry anchors remain fallbacks when the glass is unavailable", () => {
  assert.equal(context.resolveListAnchorY(null, 100, 90), 100);
  assert.equal(context.resolveListAnchorY(undefined, undefined, 90), 90);
  assert.equal(context.resolveListAnchorY(null, null, null), null);
});
