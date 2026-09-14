import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const sourcePath = path.resolve(here, "../../debripod/static/js/playback-transport.js");
const source = fs.readFileSync(sourcePath, "utf8");

function load(){
  const levels = [];
  const graph = {
    setTransportLevel(media, value){ levels.push([media, value]); return true; },
    resetTransportLevel(){ levels.push([null, 1]); return true; }
  };
  const timers = new Map();
  let nextTimer = 1;
  const setTimer = (fn)=>{ const id = nextTimer++; timers.set(id, fn); return id; };
  const clearTimer = (id)=>{ timers.delete(id); };
  let now=1000;
  const window = {DebriPod:{mediaAudioGraph:graph}, performance:{now:()=>now}};
  const context = {window, Promise, Date, setTimeout:setTimer, clearTimeout:clearTimer};
  vm.createContext(context);
  vm.runInContext(source, context, {filename:sourcePath});
  return {transport:window.DebriPod.playbackTransport, levels, setTime:(value)=>{now=value;}};
}

function media(){
  return {
    paused:false,
    playbackRate:1,
    preservesPitch:true,
    webkitPreservesPitch:true,
    play(){ this.paused = false; return Promise.resolve(); },
    pause(){ this.paused = true; }
  };
}

test("manual pause ramps a separate transport level and vinyl rate without seeking", () => {
  const {transport, levels} = load();
  const audio = media();
  const originalTime = 17.25;
  audio.currentTime = originalTime;
  transport.pause(audio);
  const state = transport.testing.states.get(audio);
  assert.equal(transport.isPaused(audio), true);
  assert.equal(audio.currentTime, originalTime);
  assert.equal(audio.preservesPitch, false);
  transport.testing.tick(audio, state, state.startedAt + 130);
  assert.ok(state.level < 1 && state.level > 0);
  assert.ok(audio.playbackRate < 1 && audio.playbackRate > 0.24);
  transport.testing.tick(audio, state, state.startedAt + 260);
  assert.equal(state.timer, null);
  assert.equal(audio.paused, true);
  assert.equal(state.level, 0);
  assert.equal(transport.visualizerLevel(audio), 0);
  assert.ok(levels.some((entry)=>entry[1] === 0));
});

test("resume reverses a partial pause and restores rate and pitch", async () => {
  const {transport} = load();
  const audio = media();
  transport.pause(audio);
  let state = transport.testing.states.get(audio);
  transport.testing.tick(audio, state, state.startedAt + 100);
  const levelAtReverse = state.level;
  assert.equal(transport.toggle(audio), true);
  state = transport.testing.states.get(audio);
  assert.equal(transport.isPaused(audio), false);
  await Promise.resolve();
  transport.testing.tick(audio, state, state.startedAt + 260);
  assert.equal(audio.paused, false);
  assert.equal(audio.playbackRate, 1);
  assert.equal(audio.preservesPitch, true);
  assert.equal(transport.visualizerLevel(audio), null);
  assert.ok(levelAtReverse > 0);
});

test("cancel restores the media rate and removes the visualizer transport level", () => {
  const {transport} = load();
  const audio = media();
  transport.pause(audio);
  assert.equal(transport.cancel(audio), true);
  assert.equal(audio.playbackRate, 1);
  assert.equal(audio.preservesPitch, true);
  assert.equal(transport.visualizerLevel(audio), null);
});


test("initial resume primes silent slow playback and starts its clock after play resolves", async () => {
  const {transport,levels,setTime}=load();
  const audio=media();audio.paused=true;
  Object.defineProperty(audio,"currentTime",{get:()=>17.25,set:()=>assert.fail("transport must never seek")});
  let resolvePlay;
  audio.play=()=>{
    assert.equal(levels.at(-1)[1],0,"gain is silent before play");
    assert.equal(audio.playbackRate,.25);
    audio.paused=false;
    return new Promise(resolve=>{resolvePlay=resolve;});
  };
  transport.resume(audio);
  const state=transport.testing.states.get(audio);
  setTime(5000);resolvePlay();await Promise.resolve();
  assert.equal(state.startedAt,5000);
  assert.equal(state.level,0);
  transport.testing.tick(audio,state,5260);
  assert.equal(audio.playbackRate,1);
  assert.equal(audio.currentTime,17.25);
});

test("a stale rejected play promise cannot cancel a newer pause", async () => {
  const {transport}=load();
  const audio=media();audio.paused=true;
  let rejectPlay;
  audio.play=()=>{audio.paused=false;return new Promise((resolve,reject)=>{rejectPlay=reject;});};
  transport.resume(audio);
  transport.pause(audio);
  const state=transport.testing.states.get(audio);
  rejectPlay(new Error("superseded play"));await Promise.resolve();await Promise.resolve();
  assert.equal(transport.testing.states.get(audio),state);
  assert.equal(transport.isPaused(audio),true);
  transport.testing.tick(audio,state,state.startedAt+260);
  assert.equal(audio.paused,true);
});
