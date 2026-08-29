import assert from "node:assert/strict";
import {createRequire} from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const {createBrowserControlDispatcher, resolveControlCommand} = require("../../debripod/static/js/control-dispatcher.js");
const {contextMenuRows, normalizeMediaTarget} = require("../../debripod/static/js/media-actions.js");

test("Q and E map through the same command table in all contexts", () => {
  assert.equal(resolveControlCommand("keyboard", "scroll_back", "list"), "scroll_back");
  assert.equal(resolveControlCommand("keyboard", "scroll_back", "now_playing"), "volume_down");
  assert.equal(resolveControlCommand("keyboard", "scroll_back", "seek_mode"), "seek_back");
  assert.equal(resolveControlCommand("keyboard", "scroll_forward", "list"), "scroll_forward");
  assert.equal(resolveControlCommand("keyboard", "scroll_forward", "now_playing"), "volume_up");
  assert.equal(resolveControlCommand("keyboard", "scroll_forward", "seek_mode"), "seek_forward");
});

test("unchanged center seek cancels instead of opening a playlist", () => {
  assert.equal(resolveControlCommand("tap", "center", "seek_mode", {seekChanged: false}), "cancel_seek");
  assert.equal(resolveControlCommand("tap", "center", "seek_mode", {seekChanged: true}), "commit_seek");
});

test("hold contract is context independent", () => {
  assert.equal(resolveControlCommand("hold", "center", "list"), "open_context");
  assert.equal(resolveControlCommand("hold", "top", "seek_mode"), "jump_to_item");
  assert.equal(resolveControlCommand("hold", "right", "list"), "open_queue");
  assert.equal(resolveControlCommand("hold", "bottom", "now_playing"), "open_now_playing");
  assert.equal(resolveControlCommand("hold", "left", "list"), "open_history");
});

test("context menus are target-driven and reject nonplayable rows", () => {
  assert.deepEqual(contextMenuRows({kind:"dir", label:"Folder"}), []);
  assert.deepEqual(contextMenuRows({kind:"heading", label:"Heading"}), []);
  const music = normalizeMediaTarget({kind:"track", media:"audio", root:{id:"r"}, rel:"song.flac"});
  assert.deepEqual(contextMenuRows(music).map((row) => row.label), ["Lyrics", "Add to playlist", "Like"]);
  const movie = normalizeMediaTarget({kind:"movie", media:"video", root:{id:"r"}, rel:"movie.mkv"});
  assert.deepEqual(contextMenuRows(movie).map((row) => row.label), ["View information", "Like"]);
  const youtube = normalizeMediaTarget({kind:"file", media:"video", root:{id:"r"}, rel:"video.mp4", source:"youtube"});
  assert.deepEqual(contextMenuRows(youtube).map((row) => row.label), ["View comments", "Like"]);
});

test("range editor consumes center tap, center hold, and Menu before ordinary controls", async () => {
  const calls = [];
  const win = {
    DebriPod: {
      navigationController: {isActive:()=>true, back:()=>calls.push("nav-back")},
      mediaActions: {openContextMenuForCurrentTarget:()=>calls.push("context")},
    },
    nowPlaying: {style:{display:"none"}},
    rangeEditorCenterPress: ()=>{ calls.push("commit"); return true; },
    rangeEditorCenterHold: ()=>{ calls.push("keyboard"); return true; },
    rangeEditorCancelActive: ()=>{ calls.push("cancel"); return true; },
  };
  const dispatcher = createBrowserControlDispatcher(win);
  await dispatcher.dispatch("tap", "center");
  await dispatcher.dispatch("hold", "center");
  await dispatcher.dispatch("tap", "top");
  assert.deepEqual(calls, ["commit", "keyboard", "cancel"]);
});
