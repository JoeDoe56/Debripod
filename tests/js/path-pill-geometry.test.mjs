import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const sourcePath = path.resolve(here, "../../debripod/static/js/path-pill.js");
const source = fs.readFileSync(sourcePath, "utf8");
const liquidGluePath = path.resolve(here, "../../debripod/static/js/liquid-glue.js");
const liquidGlueSource = fs.readFileSync(liquidGluePath, "utf8");

function loadFunction(name, globals = {}) {
  const match = source.match(new RegExp(`function ${name}\\([^)]*\\)\\{[\\s\\S]*?\\n  \\}`));
  assert.ok(match, `${name} must remain independently testable`);
  const context = {...globals};
  vm.createContext(context);
  vm.runInContext(match[0], context, {filename: sourcePath});
  return context[name];
}

test("path pill never exceeds the smaller info-pill or displayed cover width", () => {
  const constrain = loadFunction("constrainPathPillWidth");
  assert.equal(constrain(340, 280, 360), 280);
  assert.equal(constrain(220, 480, 360), 220);
  assert.equal(constrain(0, 0, 300), 300);
});

test("intrinsic measurement shrinks after shorter text despite a stretched row", () => {
  let current;
  const measure = loadFunction("pathPillIntrinsicTextWidth", {document: {createRange(){
    return {selectNodeContents(el){ current = el; }, getBoundingClientRect(){ return {width: current.textContent.length * 7}; }, detach(){}};
  }}});
  const el = {textContent: "A long library breadcrumb", scrollWidth: 300, offsetWidth: 300};
  assert.equal(measure(el), 175);
  el.textContent = "Songs";
  assert.equal(measure(el), 35);
  el.textContent = "";
  assert.equal(measure(el), 0);
});

test("path pill text fades only when it overflows", () => {
  const overflows = loadFunction("pathPillTextOverflows");
  assert.equal(overflows(120, 120), false);
  assert.equal(overflows(122, 120), true);
});

test("width changes coalesce glass work into the shared frame scheduler", () => {
  const calls = [];
  const lens = {invalidate(shape){ calls.push(["invalidate", shape]); }};
  const mark = loadFunction("markPathPillWidthChanged", {
    glassLensesWithClass(className){ calls.push(["lens", className]); return [lens]; },
    window: {DebriPod: {frameScheduler: {mark(options){ calls.push(["schedule", options.metrics, options.render]); }}}}
  });
  mark();
  assert.deepEqual(calls, [["lens", "pathPillGlass"], ["invalidate", true], ["schedule", true, true]]);
});

test("list pill remains eligible while partially visible", () => {
  const match = liquidGlueSource.match(/function rowPillIntersectsListInnerRect\([^)]*\)\{[\s\S]*?\n  \}/);
  assert.ok(match, "row-pill intersection helper must remain independently testable");
  const context = {};
  vm.createContext(context);
  vm.runInContext(match[0], context, {filename: liquidGluePath});
  const intersects = context.rowPillIntersectsListInnerRect;
  const inner = {left: 0, top: 0, right: 100, bottom: 100};
  assert.equal(intersects({left: 8, top: -10, right: 42, bottom: 4}, inner, 2), true);
  assert.equal(intersects({left: 8, top: -30, right: 42, bottom: -3}, inner, 2), false);
});
