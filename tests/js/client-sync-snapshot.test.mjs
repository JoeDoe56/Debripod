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

test("cached selection distinguishes album and category rows without file paths", () => {
  const source = readFileSync("debripod/static/js/client-sync.js", "utf8");
  const context = {};
  vm.runInNewContext([
    extractFunction(source, "function cachedItemIdentity(item)"),
    extractFunction(source, "function restoreCachedSelectionIndex(items, selectedItem, fallback)"),
    "globalThis.restore = restoreCachedSelectionIndex;"
  ].join("\n"), context);
  const albums = [
    {kind:"metalist", level:"albums", value:"Ride the Lightning", label:"Ride the Lightning"},
    {kind:"metalist", level:"albums", value:"Master of Puppets", label:"Master of Puppets"}
  ];
  assert.equal(context.restore([{kind:"random"}, ...albums], {...albums[1]}, 1), 2);
});

test("actual client-sync snapshot saves and restores all 2100 logical rows", async () => {
  const source = readFileSync("debripod/static/js/client-sync.js", "utf8");
  const sanitize = extractFunction(source, "function sanitizeItem(value, depth)");
  const identity = extractFunction(source, "function cachedItemIdentity(item)");
  const selection = extractFunction(source, "function restoreCachedSelectionIndex(items, selectedItem, fallback)");
  const saveStart = source.indexOf("async function saveRenderedViewSnapshot(renderedItems)");
  const saveEnd = source.indexOf("\n  async function saveCurrentViewState()", saveStart);
  assert.ok(saveStart >= 0 && saveEnd > saveStart, "snapshot saver must remain present");
  const save = source.slice(saveStart, saveEnd);
  const apply = extractFunction(source, "function applyViewRecord(rec)");
  const startup = extractFunction(source, "async function restoreStartupViewState()");
  const records = [];
  const restored = [];
  const logicalItems = [
    {kind: "random", label: "Random"},
    ...Array.from({length: 2100}, (_value, index) => ({kind: "track", rel: "track-" + index, label: "Track " + index})),
  ];
  const context = {
    state: {
      current: {kind: "metalist", label: "Songs", root: {id: "music", name: "Music", mode: "metadata"}},
      items: logicalItems,
      sel: 1777,
    },
    stateSummary: {library_versions: {music: 4}},
    scope: "test-user",
    libList: {scrollTop: 312},
    window: {DEBRIPOD_ASSET_VERSION: "test"},
    descriptorForCurrent: () => ({kind: "metalist", label: "Songs", rootId: "music", rootName: "Music", rootMode: "metadata", level: "songs", value: ""}),
    viewKeyForDescriptor: () => "test-view",
    put: async (store, value) => { records.push({store, value}); },
    sanitizeRoot: (value) => ({id: String(value.id || ""), name: String(value.name || ""), mode: String(value.mode || "")}),
    restoreLoadForCurrent: () => () => {},
    restoreCachedView: async () => false,
    get: async (_store, key) => key.endsWith("last-view") ? {value: {current: {kind: "metalist", label: "Songs", rootId: "music", rootName: "Music", rootMode: "metadata"}, items: [], sel: 0, scrollTop: 0}} : null,
    viewMetaList: async () => {},
    resetList: (items) => {
      const withRandom = [{kind: "random", label: "Random"}, ...items];
      context.state.items = withRandom;
      restored.push(withRandom);
    },
    renderList: () => {},
    requestAnimationFrame: () => {},
  };
  context.globalThis = context;
  vm.runInNewContext([sanitize, identity, selection, save, apply, startup].join("\n"), context);
  context.sourceItems = logicalItems;
  await vm.runInNewContext("saveRenderedViewSnapshot(sourceItems)", context);
  const snapshot = records.find((entry) => entry.store === "view_snapshots").value;
  assert.equal(snapshot.items.length, 2100);
  assert.equal(snapshot.items[0].rel, "track-0");
  assert.equal(snapshot.items[2099].rel, "track-2099");
  assert.equal(snapshot.sel, 1776);

  context.state.items = [];
  assert.equal(vm.runInNewContext("applyViewRecord(snapshot)", Object.assign(context, {snapshot})), true);
  assert.equal(restored.length, 1);
  assert.equal(restored[0].length, 2101);
  assert.equal(context.state.sel, 1777);
  assert.equal(context.state.items[context.state.sel].rel, "track-1776");

  const cachedRecord = {value: {current: snapshot.current, items: snapshot.items, sel: snapshot.sel, scrollTop: 312}};
  context.get = async (_store, key) => key.endsWith("last-view") ? cachedRecord : null;
  context.viewMetaList = async () => { context.resetList(snapshot.items); };
  context.state.items = [];
  assert.equal(await vm.runInNewContext("restoreStartupViewState()", context), true);
  assert.equal(context.state.sel, 1777);
  assert.equal(context.state.items[context.state.sel].rel, "track-1776");
});
