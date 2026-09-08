import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import test from "node:test";

function extractFunction(source, marker){
  const start = source.indexOf(marker);
  assert.notEqual(start, -1, marker);
  const brace = source.indexOf("{", start);
  let depth = 0;
  let quote = "";
  let escaped = false;
  for(let index = brace; index < source.length; index += 1){
    const character = source[index];
    if(quote){
      if(escaped) escaped = false;
      else if(character === "\\") escaped = true;
      else if(character === quote) quote = "";
      continue;
    }
    if(character === "\"" || character === "'" || character === "`"){ quote = character; continue; }
    if(character === "{") depth += 1;
    else if(character === "}" && --depth === 0) return source.slice(start, index + 1);
  }
  throw new Error("unbalanced function");
}

function makeMotionContext(selected){
  const calls = [];
  const context = {
    window: {state: {items: Array.from({length: 2100}, () => ({kind: "track"})), sel: selected}},
    listSelectionMotion: {
      targetStretch: 0,
      targetDirection: 0,
      boundaryHeld: false,
      boundaryDirection: 0,
      boundaryLastInputTs: 0,
      boundaryReleaseTimer: 0,
    },
    scheduleLibSelectionMotion: () => calls.push("schedule"),
    setTimeout,
    clearTimeout,
    Date,
  };
  context.globalThis = context;
  return {context, calls};
}

test("actual list selection motion holds terminal stretch across repeated wheel input", async () => {
  const source = readFileSync("debripod/static/js/liquid-glue.js", "utf8");
  const setter = extractFunction(source, "function setLibSelectionStretch(progress)");
  const {context} = makeMotionContext(2099);
  vm.runInNewContext(setter, context);

  context.setLibSelectionStretch(0.35);
  context.setLibSelectionStretch(0.35);
  assert.equal(context.listSelectionMotion.targetStretch, 1);
  assert.equal(context.listSelectionMotion.boundaryHeld, true);
  assert.equal(context.listSelectionMotion.boundaryDirection, 1);

  context.setLibSelectionStretch(0);
  assert.equal(context.listSelectionMotion.targetStretch, 1);
  await new Promise((resolve) => setTimeout(resolve, 115));
  assert.equal(context.listSelectionMotion.targetStretch, 0);
  assert.equal(context.listSelectionMotion.boundaryHeld, false);
});

test("actual list selection motion releases terminal pull on direction change", () => {
  const source = readFileSync("debripod/static/js/liquid-glue.js", "utf8");
  const setter = extractFunction(source, "function setLibSelectionStretch(progress)");
  const {context} = makeMotionContext(0);
  vm.runInNewContext(setter, context);
  context.setLibSelectionStretch(-0.5);
  assert.equal(context.listSelectionMotion.targetStretch, 1);
  context.window.state.sel = 1;
  context.setLibSelectionStretch(0.5);
  assert.equal(context.listSelectionMotion.targetStretch, 0);
  assert.equal(context.listSelectionMotion.boundaryHeld, false);
});
