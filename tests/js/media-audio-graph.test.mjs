import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const sourcePath = path.resolve(here, "../../debripod/static/js/media-audio-graph.js");
const source = fs.readFileSync(sourcePath, "utf8");

class FakeNode {
  constructor() { this.connections = []; }
  connect(node) { this.connections.push(node); return node; }
}

class FakeAudioContext {
  constructor() {
    this.destination = new FakeNode();
    this.state = "suspended";
    this.sources = [];
  }
  createMediaElementSource(element) {
    const source = new FakeNode();
    source.element = element;
    this.sources.push(source);
    return source;
  }
  createAnalyser() {
    const analyser = new FakeNode();
    analyser.fftSize = 0;
    analyser.frequencyBinCount = 128;
    analyser.smoothingTimeConstant = 0;
    analyser.getByteFrequencyData = (target)=>target.fill(64);
    analyser.getByteTimeDomainData = (target)=>target.fill(128);
    return analyser;
  }
  createGain() {
    const gain = new FakeNode();
    gain.gain = {value: 1};
    return gain;
  }
  resume() { this.state = "running"; return Promise.resolve(); }
}

function loadGraph(audioContextClass = FakeAudioContext) {
  const window = {AudioContext: audioContextClass};
  const context = {window, Uint8Array, Promise};
  vm.createContext(context);
  vm.runInContext(source, context, {filename: sourcePath});
  return window.DebriPod.mediaAudioGraph;
}

function mediaElement() {
  return {muted: false, volume: 1};
}

test("creates exactly one source per element and switches gain between active media", async () => {
  const graph = loadGraph();
  const audio = mediaElement();
  const video = mediaElement();

  graph.setActiveElement(audio);
  await graph.unlock();
  graph.setActiveElement(audio);
  graph.setActiveElement(audio);
  graph.setVolume(0.42);

  const context = graph.testing.getContext();
  assert.equal(context.sources.length, 1);
  assert.equal(graph.testing.getRecord(audio).gain.gain.value, 0.42);
  assert.equal(audio.volume, 1);

  graph.setActiveElement(video);
  assert.equal(context.sources.length, 2);
  assert.equal(graph.testing.getRecord(audio).gain.gain.value, 0);
  assert.equal(graph.testing.getRecord(video).gain.gain.value, 0.42);
});

test("uses native media volume when Web Audio is unavailable", () => {
  const graph = loadGraph(undefined);
  const audio = mediaElement();
  graph.setActiveElement(audio);
  graph.setVolume(0.27);
  assert.equal(audio.volume, 0.27);
  assert.equal(graph.isRouted(audio), false);
});

test("preload media stays unrouted and never receives audible gain", async () => {
  const graph = loadGraph();
  const active = mediaElement();
  const preload = mediaElement();
  graph.setActiveElement(active);
  await graph.unlock();
  graph.setVolume(0.8);

  assert.equal(graph.isRouted(preload), false);
  assert.equal(graph.testing.getRecord(active).gain.gain.value, 0.8);
});

test("transport gain is independent from the user volume gain", async () => {
  const graph = loadGraph();
  const audio = mediaElement();
  graph.setActiveElement(audio);
  await graph.unlock();
  graph.setVolume(0.6);
  assert.equal(graph.setTransportLevel(audio, 0.25), true);
  const record = graph.testing.getRecord(audio);
  assert.equal(record.transportGain.gain.value, 0.25);
  assert.equal(record.gain.gain.value, 0.6);
  graph.resetTransportLevel(audio);
  assert.equal(record.transportGain.gain.value, 1);
});
