import assert from "node:assert/strict";
import {createRequire} from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const {createSpecialNavigationModel, createBrowserNavigationController} = require("../../debripod/static/js/navigation-controller.js");

function origin(label = "Albums") {
  return {
    current: {kind: "metalist", label, level: "albums", value: ""},
    selectionIndex: 7,
    scrollTop: 128,
    history: [{kind: "metatop", label: "Library"}],
    search: {q: "test", results: [{id: 1}]},
  };
}

test("ordinary -> now playing -> queue unwinds finitely", () => {
  const nav = createSpecialNavigationModel();
  nav.open("now_playing", origin());
  nav.open("queue");
  assert.deepEqual(nav.snapshot().stack.map((entry) => entry.kind), ["now_playing", "queue"]);
  assert.equal(nav.back().kind, "special");
  assert.equal(nav.snapshot().stack.at(-1).kind, "now_playing");
  const result = nav.back();
  assert.equal(result.kind, "origin");
  assert.equal(result.origin.selectionIndex, 7);
  assert.deepEqual(nav.snapshot().stack, []);
  assert.equal(nav.snapshot().origin, null);
});

test("ordinary -> now playing -> history unwinds finitely", () => {
  const nav = createSpecialNavigationModel();
  nav.open("now_playing", origin("Songs"));
  nav.open("history");
  assert.equal(nav.back().entry.kind, "now_playing");
  assert.equal(nav.back().origin.current.label, "Songs");
});

test("opening the active special page does not duplicate it", () => {
  const nav = createSpecialNavigationModel();
  nav.open("queue", origin());
  nav.open("queue");
  assert.deepEqual(nav.snapshot().stack.map((entry) => entry.kind), ["queue"]);
});

test("jump clears both stack and origin", () => {
  const nav = createSpecialNavigationModel();
  nav.open("now_playing", origin());
  nav.open("queue");
  nav.clear();
  assert.deepEqual(nav.snapshot().stack, []);
  assert.equal(nav.snapshot().origin, null);
});

test("special origin preserves live library view references for exact restore", () => {
  const load = () => Promise.resolve();
  const current = {kind: "metalist", label: "Ride", level: "tracks", load};
  const parent = {kind: "metalist", label: "Metallica", level: "albums", load};
  const nav = createSpecialNavigationModel();
  nav.open("queue", {
    current,
    currentRef: current,
    root: {id: "music", name: "Library"},
    rootRef: {id: "music", name: "Library"},
    history: [parent],
    historyRefs: [parent],
  });
  const remembered = nav.snapshot().origin;
  assert.equal(remembered.currentRef, current);
  assert.equal(remembered.currentRef.load, load);
  assert.equal(remembered.historyRefs[0], parent);
});

test("browser controller restores the exact library page after now-playing and queue", async () => {
  const calls = [];
  const libraryPage = {kind: "metalist", label: "Ride", level: "tracks", load: async () => { calls.push("load-library"); }};
  const state = {
    current: libraryPage,
    root: {id: "music", name: "Library"},
    history: [{kind: "metalist", label: "Metallica", load: async () => {}}],
    sel: 9,
    specialNav: {origin: null, stack: [], restoring: false, startedFromDeepLink: false},
  };
  const list = {scrollTop: 246};
  const win = {
    state,
    document: {getElementById: (id) => id === "libList" ? list : null},
    showNowPlaying: (on) => calls.push(on ? "now-playing" : "library"),
    viewPlaybackQueue: async () => { state.current = {kind: "playback_queue", label: "Queue"}; calls.push("queue"); },
    viewHistory: async () => { state.current = {kind: "history", label: "History"}; calls.push("history"); },
    renderList: () => calls.push("render"),
    showRoots: async () => { state.current = {kind: "roots", label: ""}; calls.push("roots"); },
  };
  const nav = createBrowserNavigationController(win);
  await nav.openNowPlaying();
  await nav.openQueue();
  await nav.back();
  await nav.back();
  assert.equal(state.current, libraryPage);
  assert.equal(state.sel, 9);
  assert.equal(list.scrollTop, 246);
  assert.equal(calls.includes("roots"), false);
  assert.equal(calls.includes("load-library"), true);
});
