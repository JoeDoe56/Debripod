import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const nowPlayingPath = path.resolve(here, "../../debripod/static/js/now-playing-ui.js");
const pathPillPath = path.resolve(here, "../../debripod/static/js/path-pill.js");
const cssPath = path.resolve(here, "../../debripod/static/debripod.css");
const nowPlaying = fs.readFileSync(nowPlayingPath, "utf8");
const pathPill = fs.readFileSync(pathPillPath, "utf8");
const css = fs.readFileSync(cssPath, "utf8");

function loadFunction(source, name) {
  const snippet = extractFunction(source, name);
  const context = {};
  vm.createContext(context);
  vm.runInContext(snippet, context);
  return context[name];
}

function extractFunction(source, name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} must remain independently testable`);
  const open = source.indexOf("{", start);
  assert.ok(open >= 0, `${name} must have a body`);
  let depth = 0;
  let quote = "";
  let escaped = false;
  for(let i = open; i < source.length; i++){
    const ch = source[i];
    if(quote){
      if(escaped) escaped = false;
      else if(ch === "\\") escaped = true;
      else if(ch === quote) quote = "";
      continue;
    }
    if(ch === '"' || ch === "'" || ch === "`"){
      quote = ch;
      continue;
    }
    if(ch === "{") depth += 1;
    else if(ch === "}" && --depth === 0) return source.slice(start, i + 1);
  }
  assert.fail(`${name} body is not balanced`);
}

function loadArtFunctions() {
  const artSource = [
    nowPlaying.match(/function nowPlayingArtSrcValue\([^)]*\)\{[\s\S]*?\n\}/)[0],
    nowPlaying.match(/function nowPlayingArtCompareKey\([^)]*\)\{[\s\S]*?\n\}/)[0],
  ].join("\n");
  const context = {};
  vm.createContext(context);
  vm.runInContext(artSource, context);
  return context;
}

test("flat filemeta artwork values are normalized without an ok wrapper", () => {
  const art = loadArtFunctions();
  const normalize = art.nowPlayingArtSrcValue;
  const key = art.nowPlayingArtCompareKey;
  assert.equal(normalize(" /art/root/song.mp3?v=3 "), "/art/root/song.mp3?v=3");
  assert.equal(normalize({url: "/art/root/song.mp3"}), "/art/root/song.mp3");
  assert.equal(key("/art/root/song.mp3?v=3"), "/art/root/song.mp3?v=3");
});

test("metadata feeds quality first and updates both playback pill consumers", () => {
  assert.match(nowPlaying, /m\.quality \|\| m\.tech \|\| m\.ext/);
  assert.match(nowPlaying, /pathPillNowText\.innerHTML = playbackTitleHtml/);
  assert.match(nowPlaying, /npTech\.dataset\.progressText/);
});

test("cover clicks and double clicks share one pill toggle", () => {
  assert.match(pathPill, /bindPlaybackPillCoverToggle\(npArt\)/);
  assert.match(pathPill, /bindPlaybackPillCoverToggle\(npArtStill\)/);
  assert.equal((pathPill.match(/bindPlaybackPillCoverToggle\(npArt\)/g) || []).length, 1);
  assert.equal((pathPill.match(/bindPlaybackPillCoverToggle\(npArtStill\)/g) || []).length, 1);

  let now = 0;
  let nextTimerId = 1;
  const timers = new Map();
  const calls = [];
  const context = {
    performance: {now: () => now},
    setTimeout(fn, delay){
      const id = nextTimerId++;
      timers.set(id, {at: now + delay, fn});
      return id;
    },
    clearTimeout(id){ timers.delete(id); },
    hasNowPlayingMetadata: () => true,
    playbackPillsPinned: false,
    setPlaybackPillsPinned(){ calls.push("show"); },
    hidePlaybackPillsImmediate(){ calls.push("hide"); },
  };
  vm.createContext(context);
  vm.runInContext([
    extractFunction(pathPill, "togglePlaybackPillsFromArt"),
    extractFunction(pathPill, "bindPlaybackPillCoverToggle"),
  ].join("\n"), context);

  class FakeElement {
    constructor(){ this.listeners = new Map(); }
    addEventListener(type, fn){
      const list = this.listeners.get(type) || [];
      list.push(fn);
      this.listeners.set(type, list);
    }
    dispatch(type, detail){
      const event = {
        detail,
        preventDefault(){},
        stopPropagation(){},
      };
      for(const fn of this.listeners.get(type) || []) fn(event);
    }
  }
  const advance = (ms) => {
    now += ms;
    for(const [id, timer] of [...timers].sort((a, b) => a[1].at - b[1].at)){
      if(timer.at <= now){
        timers.delete(id);
        timer.fn();
      }
    }
  };
  const cover = new FakeElement();
  context.bindPlaybackPillCoverToggle(cover);

  cover.dispatch("click", 1);
  advance(319);
  assert.equal(calls.length, 0, "single click waits for double-click classification");
  advance(1);
  assert.equal(calls.length, 1, "single click commits one toggle");

  advance(600);
  cover.dispatch("click", 1);
  advance(321);
  cover.dispatch("click", 2);
  advance(100);
  cover.dispatch("dblclick", 2);
  advance(600);
  assert.equal(calls.length, 2, "delayed double click does not add a second toggle");
});

test("static art participates in width observation and glass follows opacity", () => {
  assert.match(pathPill, /var npArtStill = document\.getElementById\("npArtStill"\)/);
  assert.match(pathPill, /\[npArt, npArtStill, document\.querySelector\("\.ipodScreenContent"\)/);
  assert.match(pathPill, /lens\._revealProgress = pathPillRenderOpacity\(\)/);
  assert.match(pathPill, /lens\._revealProgress = infoPillRenderOpacity\(\)/);
});

test("progress input has an invisible thumb and symmetric time-label alignment", () => {
  assert.match(css, /npSeek::\-webkit-slider-thumb[\s\S]*?width:0/);
  assert.match(css, /npSeek::\-moz-range-thumb[\s\S]*?width:0/);
  assert.match(css, /\.npMeterFill[\s\S]*?background:#fff/);
  assert.match(css, /#npCur\{text-align:left;\}/);
  assert.match(css, /#npDur\{text-align:right;\}/);
});
