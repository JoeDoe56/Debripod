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

function loadSession(options = {}){
  const handlers = {};
  const metadataConstructor = options.metadata === false ? undefined : FakeMediaMetadata;
  const mediaSession = {
    metadata: null,
    playbackState: "none",
    positionState: null,
    setPositionState: value=>{ mediaSession.positionState = value; },
    setActionHandler: (name, handler)=>{ handlers[name] = handler; }
  };
  const navigator = {mediaSession};
  const window = {
    MediaMetadata: metadataConstructor,
    DebriPod: {},
    location: {href: "https://debripod.test/"}
  };
  const context = {
    window,
    navigator,
    MediaMetadata: metadataConstructor,
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
  return {context, mediaSession, handlers};
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

test("MediaSession controls remain registered when Safari omits metadata support", () => {
  const {context:c, handlers} = loadSession({metadata:false});
  c.activeAudio = {paused:false, duration:10, currentTime:2, playbackRate:1, play:()=>Promise.resolve(), pause:()=>{}};
  c.syncMediaSessionControls();
  assert.equal(typeof handlers.play, "function");
  assert.equal(typeof handlers.pause, "function");
  assert.equal(typeof handlers.nexttrack, "function");
});

test("MediaSession exposes seek and queue actions against the real playback clock", () => {
  const {context:c, handlers} = loadSession();
  const media = {
    paused: false, duration: 100, currentTime: 40, playbackRate: 1,
    currentSrc: "/stream/song.mp3", src: "/stream/song.mp3",
    play: ()=>Promise.resolve(), pause: ()=>{}
  };
  c.activeAudio = media;
  const calls = [];
  c.window.DebriPod.playbackQueue = {
    state: {index: 1, items: [{}, {}, {}]},
    previous: ()=>{ calls.push("previous"); },
    next: ()=>{ calls.push("next"); }
  };
  c.syncMediaSessionControls();

  handlers.seekbackward({seekOffset: 12});
  assert.equal(media.currentTime, 28);
  handlers.seekforward({seekOffset: 7});
  assert.equal(media.currentTime, 35);
  handlers.seekto({seekTime: 82});
  assert.equal(media.currentTime, 82);
  handlers.previoustrack();
  handlers.nexttrack();
  assert.deepEqual(calls, ["previous", "next"]);
});

test("MediaSession position state follows the decoded gapless clock", () => {
  const {context:c, mediaSession} = loadSession();
  c.activeAudio = {paused:false, duration:2, currentTime:0.25, playbackRate:1};
  c.gaplessPlaybackSnapshot = ()=>({duration:240, position:91.5, playbackRate:1.25, playing:true});
  c.syncMediaSessionPosition();
  assert.equal(mediaSession.positionState.duration, 240);
  assert.equal(mediaSession.positionState.position, 91.5);
  assert.equal(mediaSession.positionState.playbackRate, 1.25);
});


test("history writes omit prior history, handle large queues, and retain event order",async()=>{
  const {context:c} = loadSession(); const requests = [];
  c.state.playbackSession = {queueSessionId:"album",queue:Array.from({length:500},(_,i)=>({root_id:"music",rel:"a".repeat(160)+i})),history:[{secretHistory:"x".repeat(100000)}]};
  c.fetch = async(url,options)=>{requests.push(options);return {ok:true};};
  const first = c.playbackPost({event:"start",rel:"one"});
  c.state.playbackSession.queueSessionId="other";
  const second = c.playbackPost({event:"time",rel:"two"});
  await Promise.all([first,second]);
  assert.equal(requests.length,2);
  assert.equal(JSON.parse(requests[0].body).session.queueSessionId,"album");
  assert.equal(JSON.parse(requests[1].body).session.queueSessionId,"other");
  assert.equal(requests[0].keepalive,false);
  assert.equal(requests[0].body.includes("secretHistory"),false);
});

test("history write retries a transient failure before snapshot reads",async()=>{
  const {context:c} = loadSession(); let calls=0;
  c.fetch=async()=>{if(++calls===1)throw new Error("offline");return {ok:true};};
  c.playbackPost({event:"start"});
  await c.flushPlaybackWrites();
  assert.equal(calls,2);assert.equal(c.state.playbackSyncError,false);
});

test("capture navigation keeps the album instead of its parent while now playing",()=>{
  const {context:c}=loadSession();
  const root={id:"all",mode:"metadata"};
  c.state.root=root;
  c.state.current={kind:"metalist",root,level:"album_tracks",value:"Dirt",label:"Dirt"};
  c.state.history=[{kind:"metalist",root,level:"artists",label:"Artists"}];
  c.nowPlaying={style:{display:"block"}};
  const nav=c.captureNavContext();
  assert.equal(nav.value,"Dirt");assert.equal(nav.history[0].level,"artists");
});


test("aggregate metadata navigation rebuilds ordinary parent history",async()=>{
  const {context:c}=loadSession();
  const root={id:"all",mode:"metadata"};
  c.loadConfig=async()=>({roots:[],aggregate_root:root});
  c.showNowPlaying=()=>{};
  const visits=[];
  c.viewMetaList=async(root,level,value)=>visits.push([root.id,level,value]);
  await c.openNavContext({root_id:"all",kind:"metalist",level:"album_tracks",value:"Dirt",history:[{root_id:"all",kind:"metalist",level:"artists",value:""}]});
  assert.equal(c.state.history.length,1);
  await c.state.history[0].load();
  assert.deepEqual(visits,[["all","album_tracks","Dirt"],["all","artists",""]]);
});
