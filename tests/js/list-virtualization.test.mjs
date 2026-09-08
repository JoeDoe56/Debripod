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

test("actual canVirtualizeList keeps playlist lists virtual with create actions", () => {
  const source = readFileSync("debripod/static/js/list-view.js", "utf8");
  const policy = extractFunction(source, "function nonVirtualInfoView(kind)");
  const canVirtualize = extractFunction(source, "function canVirtualizeList()");
  const context = {
    window: {DebriPod: {rowTransitions: {isNonVirtualInfoView: (kind) => ["roots", "libinfo"].includes(String(kind))}}},
    DebriPod: {rowTransitions: {isNonVirtualInfoView: (kind) => ["roots", "libinfo"].includes(String(kind))}},
    document: {activeElement: null},
    libList: {contains: () => false},
    state: {
      current: {kind: "playlist"},
      items: [
        {kind: "playlist_create", label: "Create playlist"},
        ...Array.from({length: 2100}, (_value, index) => ({kind: "track", rel: "track-" + index})),
      ],
    },
  };
  context.globalThis = context;
  vm.runInNewContext([policy, canVirtualize, "globalThis.result = canVirtualizeList();"].join("\n"), context);
  assert.equal(context.result, true);

  context.state.items[0] = {kind: "playlist_edit_name", label: "Editing"};
  vm.runInNewContext("globalThis.result = canVirtualizeList();", context);
  assert.equal(context.result, false);
});
