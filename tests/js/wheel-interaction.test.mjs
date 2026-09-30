import assert from "node:assert/strict";
import test from "node:test";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {createInteraction, STATES, shouldIgnoreLostPointerCapture, requestFullscreen, triggerRandom} = require("../../debripod/static/js/wheel-interaction.js");
const {normalizeMediaTarget, wheelActionsForTarget, createBrowserMediaActions} = require("../../debripod/static/js/media-actions.js");

const rect = {left: 0, top: 0, width: 200, height: 200};
const point = (x, y) => ({x, y});

function allActions() {
  return {
    toggle_like: {action: "toggle_like", enabled: true},
    add_to_playlist: {action: "add_to_playlist", enabled: true},
    play_next: {action: "play_next", enabled: true},
    play_after: {action: "play_after", enabled: true},
  };
}

test("top downward swipe resolves fullscreen exactly once", () => {
  let fullscreen = 0;
  const wheel = createInteraction({callbacks: {fullscreen: () => { fullscreen++; }}});
  wheel.begin(point(100, 10), {rect, verticalHint: "top"});
  wheel.move(point(108, 33));
  assert.equal(wheel.state(), STATES.POTENTIAL_VERTICAL);
  wheel.move(point(110, 42));
  assert.equal(wheel.state(), STATES.FULLSCREEN_GESTURE);
  const result = wheel.end();
  assert.equal(result.gesture, "fullscreen");
  assert.equal(fullscreen, 1);
  wheel.end();
  assert.equal(fullscreen, 1);
});

test("bottom upward swipe resolves the existing random action", () => {
  let random = 0;
  const wheel = createInteraction({callbacks: {random: () => { random++; }}});
  wheel.begin(point(100, 190), {rect, verticalHint: "bottom"});
  wheel.move(point(92, 167));
  assert.equal(wheel.state(), STATES.POTENTIAL_VERTICAL);
  wheel.move(point(90, 156));
  assert.equal(wheel.state(), STATES.RANDOM_GESTURE);
  assert.equal(wheel.end().gesture, "random");
  assert.equal(random, 1);
});

test("vertical gesture arbitration keeps a shallow diagonal alive below threshold", () => {
  const wheel = createInteraction({callbacks: {fullscreen: () => {}}});
  wheel.begin(point(100, 10), {rect, verticalHint: "top"});
  wheel.move(point(108, 33));
  assert.equal(wheel.state(), STATES.POTENTIAL_VERTICAL);
  wheel.move(point(110, 42));
  assert.equal(wheel.state(), STATES.FULLSCREEN_GESTURE);
});

test("wrong-axis vertical movement restores normal wheel handling", () => {
  const wheel = createInteraction();
  wheel.begin(point(100, 10), {rect, verticalHint: "top"});
  wheel.move(point(140, 18));
  assert.equal(wheel.state(), STATES.NORMAL);
  assert.equal(wheel.end().gesture, null);
});

test("fullscreen request stays in the pointer activation call", async () => {
  const calls = [];
  await requestFullscreen({forceFullscreenOn: () => { calls.push("fullscreen"); return true; }});
  assert.deepEqual(calls, ["fullscreen"]);
});

test("random gesture delegates once and handles rejected playback", async () => {
  let calls=0;
  assert.equal(await triggerRandom({randomFromCurrentList:()=>{calls++;return true;}}),true);
  assert.equal(calls,1);
  const warnings=[];
  assert.equal(await triggerRandom({randomFromCurrentList:()=>Promise.reject(new Error("unavailable")),reportUiStatus:message=>warnings.push(message)}),false);
  assert.deepEqual(warnings,["unavailable"]);
});

test("vertical pulls can be reversed or cancelled without executing",()=>{
  let actions=0;
  for(const start of [point(100,10),point(100,190)]){
    const wheel=createInteraction({callbacks:{fullscreen:()=>actions++,random:()=>actions++}});
    wheel.begin(start,{rect});
    wheel.move(point(100,100));
    wheel.move(start);
    assert.equal(wheel.end().gesture,null);
    assert.equal(wheel.consumePointer(),true);
    wheel.begin(start,{rect});wheel.move(point(100,100));wheel.cancel("pointercancel");
    assert.equal(wheel.end().gesture ?? null,null);
  }
  assert.equal(actions,0);
});

test("vertical/circular movement does not resolve an edge pull", () => {
  const progress = [];
  const wheel = createInteraction({callbacks: {panelProgress: value => progress.push(value)}});
  wheel.begin(point(190, 100), {rect});
  wheel.move(point(190, 145));
  assert.equal(wheel.state(), STATES.NORMAL);
  assert.deepEqual(progress, []);
});

test("horizontal right edge pull opens the panel and suppresses wheel navigation", () => {
  const events = [];
  const wheel = createInteraction({callbacks: {
    panelProgress: value => events.push(["progress", value]),
    panelOpen: value => events.push(["open", value]),
  }});
  wheel.begin(point(190, 100), {rect});
  wheel.move(point(110, 106));
  assert.equal(wheel.state(), STATES.RIGHT_PANEL_GESTURE);
  const result = wheel.end();
  assert.equal(result.action, null);
  assert.deepEqual(events.at(-1), ["open", true]);
});

test("a touch beginning on the Next Track hit region resolves even near its inner edge", () => {
  const wheel = createInteraction({callbacks: {panelProgress: () => {}}});
  wheel.begin(point(126, 100), {rect, edgeHint: "right"});
  wheel.move(point(92, 104));
  assert.equal(wheel.state(), STATES.RIGHT_PANEL_GESTURE);
});

test("a shallow inward diagonal remains eligible until it crosses the horizontal threshold", () => {
  const wheel = createInteraction({callbacks: {panelProgress: () => {}}});
  wheel.begin(point(190, 100), {rect});
  wheel.move(point(167, 108));
  assert.equal(wheel.state(), STATES.POTENTIAL_EDGE);
  wheel.move(point(160, 110));
  assert.equal(wheel.state(), STATES.RIGHT_PANEL_GESTURE);
});

test("an inner Next Track start can reach the panel-open threshold at wheel center", () => {
  let opened = false;
  const wheel = createInteraction({callbacks: {panelOpen: value => { opened = value; }}});
  wheel.begin(point(130, 100), {rect, edgeHint: "right"});
  wheel.move(point(100, 100));
  wheel.end();
  assert.equal(opened, true);
});

test("capture transfer from Next Track to the wheel does not cancel the gesture", () => {
  const wheel = {hasPointerCapture: pointerId => pointerId === 7};
  assert.equal(shouldIgnoreLostPointerCapture(wheel, {pointerId: 7}), true);
  assert.equal(shouldIgnoreLostPointerCapture(wheel, {pointerId: 8}), false);
  assert.equal(shouldIgnoreLostPointerCapture(wheel, {pointerId: 9, target: {}}), true);
});

test("edge gestures are restricted to their screen", () => {
  const outside = createInteraction({isNowPlaying: () => false});
  outside.begin(point(10, 100), {rect});
  outside.move(point(90, 104));
  assert.equal(outside.state(), STATES.NORMAL);

  const nowPlaying = createInteraction({isNowPlaying: () => true});
  nowPlaying.begin(point(190, 100), {rect});
  nowPlaying.move(point(110, 104));
  assert.equal(nowPlaying.state(), STATES.NORMAL);
  nowPlaying.cancel("screen-test");
  nowPlaying.begin(point(10, 100), {rect});
  nowPlaying.move(point(90, 104));
  assert.equal(nowPlaying.state(), STATES.LYRICS_GESTURE);
});

test("a panel close begins at the wheel center and starts at the open position", () => {
  const progress = [];
  const wheel = createInteraction({isPanelOpen: () => true, callbacks: {
    panelProgress: value => progress.push(value),
  }});
  wheel.begin(point(100, 100), {rect});
  wheel.move(point(165, 105));
  assert.equal(wheel.state(), STATES.RIGHT_PANEL_GESTURE);
  assert.ok(progress[0] > 0 && progress[0] < 1, `expected continuous close progress, got ${progress[0]}`);
});

test("panel close can start on the center control without stealing a stationary hold", () => {
  const wheel = createInteraction({isPanelOpen: () => true, actionsForTarget: () => allActions(), holdDelay: 8});
  wheel.begin(point(100, 100), {rect, isCenter: true});
  wheel.move(point(165, 104));
  assert.equal(wheel.state(), STATES.RIGHT_PANEL_GESTURE);
});

test("small center jitter does not cancel a pending hold", async () => {
  const wheel = createInteraction({holdDelay: 8, actionsForTarget: () => allActions()});
  wheel.begin(point(100, 100), {rect, isCenter: true});
  wheel.move(point(104, 103));
  await new Promise(resolve => setTimeout(resolve, 18));
  assert.equal(wheel.state(), STATES.ACTION_DEAD_ZONE);
  wheel.cancel("test");
});

test("releasing in the action dead zone cancels without executing", () => {
  let executed = 0;
  const wheel = createInteraction({actionsForTarget: () => allActions(), callbacks: {action: () => executed++}});
  wheel.begin(point(100, 100), {rect, isCenter: true});
  wheel.enterActionMode();
  wheel.move(point(120, 100));
  const result = wheel.end();
  assert.equal(result.action, null);
  assert.equal(executed, 0);
});

test("a selected action executes exactly once on release", () => {
  const executed = [];
  const wheel = createInteraction({actionsForTarget: () => allActions(), callbacks: {
    action: action => executed.push(action),
  }});
  wheel.begin(point(100, 100), {rect, isCenter: true});
  wheel.enterActionMode();
  wheel.move(point(100, 10));
  assert.equal(wheel.state(), STATES.ACTION_TARGET_SELECTED);
  wheel.end();
  wheel.end();
  assert.deepEqual(executed, ["toggle_like"]);
});

test("pointer cancellation restores the original panel state", () => {
  const progress = [];
  const wheel = createInteraction({callbacks: {
    panelProgress: value => progress.push(value),
  }});
  wheel.begin(point(190, 100), {rect});
  wheel.move(point(120, 100));
  wheel.cancel("lostpointercapture");
  assert.equal(progress.at(-1), 0);
});

test("secondary pointers cannot steal or finish the active gesture", () => {
  let updates = 0;
  const wheel = createInteraction({callbacks: {panelProgress: () => { updates++; }}});
  wheel.begin(point(190, 100), {rect, pointerId: 1});
  assert.equal(wheel.move(point(120, 100), {pointerId: 2}), false);
  assert.equal(wheel.end({pointerId: 2}).action, null);
  assert.equal(wheel.isActive(), true);
  wheel.cancel("test", {pointerId: 1});
  assert.equal(updates, 1);
});

test("artist and genre rows do not expose contextual hold actions", () => {
  for (const kind of ["artist", "genre"]) {
    const target = normalizeMediaTarget({kind, label: "Collection", root: {id: "music"}});
    assert.deepEqual(wheelActionsForTarget(target), {});
  }
});

test("bounded collection wheel actions apply to every member", async () => {
  const liked = [];
  const added = [];
  const win = {
    DebriPod: {
      apiClient: {
        apiGet: async url => url.includes("metadata") ? {items: [
          {kind: "track", media: "audio", root_id: "music", rel: "one.flac", label: "One"},
          {kind: "track", media: "audio", root_id: "music", rel: "two.flac", label: "Two"},
        ]} : {like: {liked: false}},
        apiPost: async (_url, body) => { liked.push(body.rel); return {ok: true}; },
      },
      playbackQueue: {
        hasCurrent: () => true,
        insertNext: item => { added.push(item.rel); return true; },
      },
      navigationController: {openTransient: async (_kind, render) => render()},
    },
    viewMediaPlaylistAdd: target => ({target}),
  };
  const actions = createBrowserMediaActions(win);
  assert.equal(actions.openContextMenuForCurrentTarget, undefined);
  const album = normalizeMediaTarget({kind: "album", label: "Album", root: {id: "music"}, value: JSON.stringify({album: "Album"})});
  assert.deepEqual(Object.keys(wheelActionsForTarget(album)), ["toggle_like", "add_to_playlist", "play_next", "play_after"]);
  await actions.executeWheelAction("toggle_like", album);
  assert.deepEqual(liked, ["one.flac", "two.flac"]);
  const picker = await actions.executeWheelAction("add_to_playlist", album);
  assert.deepEqual(picker.target.playlistItems.map(item=>item.rel), ["one.flac", "two.flac"]);
  await actions.executeWheelAction("play_next_collection", album);
  assert.deepEqual(added, ["two.flac", "one.flac"]);
});

test("action mode requires an owned pointer and excludes unbounded shortcuts",()=>{
  const wheel=createInteraction({actionsForTarget:allActions});
  assert.equal(wheel.enterActionMode(),false);
  const shortcut=normalizeMediaTarget({kind:"album",value:'{"artist":"Artist"}'});
  assert.deepEqual(wheelActionsForTarget(shortcut),{});
  const multipleRoots=normalizeMediaTarget({kind:"album",value:'{"album":"Album"}',collection_root_ids:["a","b"]});
  assert.equal(wheelActionsForTarget(multipleRoots).add_to_playlist.enabled,false);
  assert.equal(wheelActionsForTarget(multipleRoots).play_next.enabled,true);
});

test("liking a mixed album preserves existing likes and fills the missing ones",async()=>{
  const writes=[];
  const actions=createBrowserMediaActions({DebriPod:{apiClient:{
    apiGet:async url=>url.includes("metadata")?{items:[{kind:"track",media:"audio",root_id:"r",rel:"a.flac"},{kind:"track",media:"audio",root_id:"r",rel:"b.flac"}]}:{like:{liked:url.includes("a.flac")}},
    apiPost:async(_url,body)=>{writes.push([body.rel,body.liked]);return {ok:true};}
  }}});
  await actions.executeWheelAction("toggle_like",normalizeMediaTarget({kind:"album",root_id:"r",value:'{"album":"Album"}'}));
  assert.deepEqual(writes,[["b.flac",true]]);
});
