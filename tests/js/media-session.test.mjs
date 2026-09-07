import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const sourcePath = path.resolve(here, "../../debripod/static/js/media-session.js");
const source = fs.readFileSync(sourcePath, "utf8");

class FakeMediaMetadata {
  constructor(fields){ Object.assign(this, fields); }
}

function loadSession(){
  const mediaSession = {
    metadata: null,
    playbackState: "none",
    setActionHandler: ()=>{}
  };
  const navigator = {mediaSession};
  const window = {
    MediaMetadata: FakeMediaMetadata,
    DebriPod: {},
    location: {href: "https://debripod.test/"}
  };
  const context = {
    window,
    navigator,
    MediaMetadata: FakeMediaMetadata,
    DebriPod: window.DebriPod,
    activeAudio: {paused: true, duration: 0, currentTime: 0, playbackRate: 1},
    audioMain: null,
    standbyAudio: null,
    npVideo: null,
    state: {lastfmEnabled: false},
    isVideoActive: ()=>false,
    playbackArtworkUrl: (value)=>new URL(value, window.location.href).href,
    URL,
    setTimeout,
    clearTimeout,
    Promise,
    fetch: async()=>({}),
    apiGet: async()=>({}),
    updateWheelLabels: ()=>{}
  };
  vm.createContext(context);
  vm.runInContext(source, context, {filename: sourcePath});
  return {context, mediaSession};
}

test("MediaSession receives dynamic track metadata and absolute artwork", () => {
  const {context, mediaSession} = loadSession();
  context.updateMediaSession({
    title: "Song",
    artist: "Artist",
    album: "Album",
    art: "/art/root/album/song.flac?v=7"
  });

  assert.equal(mediaSession.metadata.title, "Song");
  assert.equal(mediaSession.metadata.artist, "Artist");
  assert.equal(mediaSession.metadata.album, "Album");
  assert.equal(mediaSession.metadata.artwork.length, 1);
  assert.equal(mediaSession.metadata.artwork[0].src, "https://debripod.test/art/root/album/song.flac?v=7");
  assert.equal(mediaSession.metadata.artwork[0].sizes, "512x512");
});
