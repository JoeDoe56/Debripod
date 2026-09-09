import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {createRequire} from "node:module";
import vm from "node:vm";
import test from "node:test";

const require = createRequire(import.meta.url);
const {createPlaybackQueueController, normalizeQueueItem} = require("../../debripod/static/js/playback-queue.js");

function extractFunction(source, marker){
  const start = source.indexOf(marker);
  assert.notEqual(start, -1, "queue builder must remain present in the UI source");
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
  throw new Error("unbalanced queue builder");
}

test("actual playback queue builder renders shuffled order with canonical click indexes", () => {
  const source = readFileSync("debripod/static/js/search-tasks-ui.js", "utf8");
  const builder = extractFunction(source, "function buildPlaybackQueueItems()");
  const items = [
    normalizeQueueItem({media: "audio", root_id: "r", rel: "a.flac", title: "A"}),
    normalizeQueueItem({media: "audio", root_id: "r", rel: "b.flac", title: "B"}),
    normalizeQueueItem({media: "video", root_id: "r", rel: "c.mkv", title: "C"}),
  ];
  const queue = createPlaybackQueueController({items, index: 0, shuffle: true, shuffleOrder: [2, 0, 1]});
  const sandbox = {
    window: {DebriPod: {playbackQueue: queue}},
    DebriPod: {playbackQueue: queue},
  };
  const script = [
    "function queueItemLabel(item, orderIndex){ return String(orderIndex + 1) + ':' + item.title; }",
    builder,
    "globalThis.result = buildPlaybackQueueItems();",
  ].join("\n");
  vm.runInNewContext(script, sandbox);
  const rows = sandbox.result;
  assert.deepEqual(Array.from(rows, (row) => row.queueIndex), [2, 0, 1]);
  assert.deepEqual(Array.from(rows, (row) => row.queueOrderPos), [0, 1, 2]);
  assert.deepEqual(Array.from(rows, (row) => row.label), ["1:C", "2:A", "3:B"]);
  assert.ok(Array.from(rows).every((row) => !Array.from(row.pills).includes("Shuffle")));
  assert.equal(rows[1].pills[0], "Now");
});

test("library Random keeps the chosen logical index through render and selection", () => {
  const source = readFileSync("debripod/static/js/library-browser.js", "utf8");
  const start = source.indexOf('if(it.kind === "random")');
  const end = source.indexOf('if(it.kind === "up")', start);
  assert.ok(start >= 0 && end > start, "random handler must remain present");
  const branch = source.slice(start, end);
  assert.match(branch, /randomEligibleIndexes\(state\.items\)/);
  assert.match(branch, /state\.sel = ri;\s*renderList\(\);[\s\S]*selectItem\(\)/);
  assert.doesNotMatch(branch, /rowAt|rendered|virtualWindow|visibleIndexes/);
});

test("actual shuffle toggle refreshes Queue rows by canonical index and preserves selection", () => {
  const librarySource = readFileSync("debripod/static/js/library-browser.js", "utf8");
  const searchSource = readFileSync("debripod/static/js/search-tasks-ui.js", "utf8");
  const setterStart = librarySource.indexOf("function setShuffleEnabled(on)");
  const setterEnd = librarySource.indexOf("\n  function toggleShuffle()", setterStart);
  assert.ok(setterStart >= 0 && setterEnd > setterStart, "shuffle setter must remain present");
  const setter = librarySource.slice(setterStart, setterEnd);
  assert.match(setter, /canonical\.setShuffle\(nextOn\)/, "every enable must rebuild the canonical shuffle order");
  const label = extractFunction(searchSource, "function queueItemLabel(item, index)");
  const builder = extractFunction(searchSource, "function buildPlaybackQueueItems()");
  const audioItems = [
    normalizeQueueItem({media: "audio", root_id: "r", rel: "a.flac", title: "A"}),
    normalizeQueueItem({media: "audio", root_id: "r", rel: "b.flac", title: "B"}),
    normalizeQueueItem({media: "audio", root_id: "r", rel: "c.flac", title: "C"}),
  ];
  const queue = createPlaybackQueueController({items: audioItems, index: 0, shuffle: false});
  const captured = [];
  const sandbox = {
    window: {DebriPod: {playbackQueue: queue}},
    DebriPod: {playbackQueue: queue},
    state: {shuffleEnabled: false, current: {kind: "playback_queue"}, playlist: audioItems, playIndex: 0, items: [], sel: 0},
    libList: {scrollTop: 217},
    localStorage: {setItem: () => {}},
    replaceListItems: (rows, options) => {
      captured.push({rows, options});
      sandbox.state.items = rows;
      sandbox.state.sel = options.selectionIndex;
    },
    ensurePlayOrder: () => {},
    preloadNextAudio: () => {},
    updateWheelLabels: () => {},
    buildPlaybackSessionUpdate: () => {},
    buildPlaylistFromItems: () => audioItems,
    buildPlaybackQueueItems: null,
    queueItemLabel: null,
  };
  sandbox.globalThis = sandbox;
  vm.runInNewContext([label, builder, "globalThis.buildPlaybackQueueItems = buildPlaybackQueueItems;"].join("\n"), sandbox);
  sandbox.state.items = vm.runInNewContext("buildPlaybackQueueItems()", sandbox);
  sandbox.state.sel = 0;
  vm.runInNewContext(setter, sandbox);
  vm.runInNewContext("setShuffleEnabled(true)", sandbox);
  const shuffled = captured.at(-1);
  assert.deepEqual(Array.from(shuffled.rows, (row) => row.queueIndex), queue.orderedIndexes());
  assert.equal(shuffled.rows[sandbox.state.sel].queueIndex, 0);
  assert.equal(sandbox.libList.scrollTop, 217);
  assert.ok(Array.from(shuffled.rows).every((row) => !Array.from(row.pills).includes("Shuffle")));

  vm.runInNewContext("setShuffleEnabled(false)", sandbox);
  const canonical = captured.at(-1);
  assert.deepEqual(Array.from(canonical.rows, (row) => row.queueIndex), [0, 1, 2]);
  assert.equal(canonical.rows[sandbox.state.sel].queueIndex, 0);
});

test("actual playNext dispatches through the canonical queue controller", async () => {
  const source = readFileSync("debripod/static/js/library-browser.js", "utf8");
  const playNext = extractFunction(source, "function playNext()");
  const calls = [];
  const canonical = {hasItems: () => true, next: () => calls.push("canonical-next")};
  const sandbox = {window: {DebriPod: {playbackQueue: canonical}}, DebriPod: {playbackQueue: canonical}};
  sandbox.globalThis = sandbox;
  vm.runInNewContext([playNext, "globalThis.result = playNext();"].join("\n"), sandbox);
  await sandbox.result;
  assert.deepEqual(calls, ["canonical-next"]);
});
