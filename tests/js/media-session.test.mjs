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
