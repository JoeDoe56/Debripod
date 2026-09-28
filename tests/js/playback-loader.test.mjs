import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const sourcePath = path.resolve(here, "../../debripod/static/js/playback-loader.js");
const source = fs.readFileSync(sourcePath, "utf8");

function loadLoader(){
  const elements = new Map();
  const document = {getElementById: (id)=>elements.get(id) || null};
  const window = {
    document,
    location: {href: "https://debripod.test/"},
    DebriPod: {},
    URL,
  };
  const localStorage = {getItem:()=>null, setItem:()=>{}};
  const context = {
    window,
    document,
    DebriPod: window.DebriPod,
    localStorage,
    URL,
    Map,
    Promise,
    Number,
    String,
    isFinite,
    setTimeout,
    clearTimeout,
    encodeURIComponent,
    encodeRel: (value)=>String(value || "").split("/").map(encodeURIComponent).join("/"),
    console,
    state: {playbackStreamingMode: "http"},
  };
  vm.createContext(context);
  vm.runInContext(source, context, {filename: sourcePath});
  return context;
}

class FakeMedia {
  constructor(){
    this.readyState = 1;
    this.src = "";
    this.currentSrc = "";
    this.listeners = new Map();
    this.playCalls = 0;
  }
  addEventListener(name, callback){ this.listeners.set(name, callback); }
  removeEventListener(name){ this.listeners.delete(name); }
  load(){ this.currentSrc = this.src; }
  play(){ this.playCalls += 1; return Promise.resolve(); }
}

test("normalizes flat filemeta into UI/session metadata and resolves artwork", () => {
  const context = loadLoader();
  const normalized = context.normalizePlaybackMetadata({
    title: "Song",
    artist: "Artist",
    album: "Album",
    genre: "Rock",
    duration: 123.5,
    tech: "FLAC 24-bit",
    art: "/art/root/album/song.flac?v=7",
  }, {rel: "album/song.flac", label: "filename.flac"});

  assert.equal(normalized.title, "Song");
  assert.equal(normalized.artist, "Artist");
  assert.equal(normalized.album, "Album");
  assert.equal(normalized.genre, "Rock");
  assert.equal(normalized.duration, 123.5);
  assert.equal(normalized.tech, "FLAC 24-bit");
  assert.equal(normalized.art, "/art/root/album/song.flac?v=7");
  assert.equal(normalized.label, "filename.flac");
  assert.equal(normalized.quality, "FLAC 24-bit");
  assert.equal(context.playbackArtworkUrl(normalized.art), "https://debripod.test/art/root/album/song.flac?v=7");
});

test("beginPlaybackLoad installs the source before the caller issues play", async () => {
  const context = loadLoader();
  const media = new FakeMedia();
  const request = context.beginPlaybackLoad(media, "root id", "album/song.mp3", "audio");
  assert.equal(media.src, "/stream/root%20id/album/song.mp3");
  media.play();
  await request.ready;
  assert.equal(media.playCalls, 1);
  assert.equal(await context.loadPlaybackIntoElement(media, "root", "other.mp3", "audio"), "/stream/root/other.mp3");
});

test("normalizes object-shaped cached artwork without stringifying it", () => {
  const context = loadLoader();
  assert.equal(
    context.normalizePlaybackMetadata({title: "Song", art: {src: "/art/root/song.jpg"}}, {label: "Song"}).art,
    "/art/root/song.jpg"
  );
  assert.equal(
    context.normalizePlaybackMetadata({title: "Song", art: {url: "/art/root/song.webp"}}, {label: "Song"}).art,
    "/art/root/song.webp"
  );
});

test("readiness rejection is observable and HLS installs its source synchronously", async () => {
  const context = loadLoader();
  const failed = new FakeMedia();
  failed.readyState = 0;
  const request = context.beginPlaybackLoad(failed, "root", "broken.mp3", "audio");
  failed.error = {code: 3, message: "decode"};
  failed.listeners.get("error")();
  await assert.rejects(request.ready, /MEDIA_ERR_DECODE/);

  context.state.playbackStreamingMode = "hls";
  const hlsMedia = new FakeMedia();
  hlsMedia.readyState = 0;
  hlsMedia.canPlayType = ()=>"probably";
  const hlsRequest = context.beginPlaybackLoad(hlsMedia, "root", "next.mp3", "audio");
  assert.equal(hlsMedia.src, "/hls/manifest?root_id=root&rel=next.mp3");
  hlsMedia.play();
  hlsMedia.listeners.get("loadedmetadata")();
  await hlsRequest.ready;
  assert.equal(hlsMedia.playCalls, 1);
});


for (const nativeFirstStart of [false, true]) test(`preload with gapless disabled uses one decoded output (native-first: ${nativeFirstStart})`,async()=>{
  const c=loadLoader();c.AbortController=AbortController;
  const events=[];let snap=null;const media={__gapless:true,paused:false,currentTime:0,duration:5,setTransportLevel(){},addEventListener(){},tick(){}};
  const item={root:{id:"r"},rel:"one",media:"audio"},next={root:{id:"r"},rel:"two",media:"audio"};
  c.state={preloadEnabled:true,gaplessEnabled:false,playlist:[item,next],playIndex:0,playbackSession:{}};
  c.npSeek=null;c.npSeekDragging=false;c.seekMode=false;
  c.audioMain=c.activeAudio={pause(){events.push("native-pause");},removeAttribute(){},load(){},play(){events.push("native-play");}};
  c.window.DebriPod.gaplessAudio={supported:()=>true,decode:async()=>({duration:5}),resumeContext:async()=>true,takePrestarted:()=>false,media,
    start:(it,buf,ni,nb,opts)=>{events.push(opts.gap);snap={key:c.gaplessItemKey(it),item:it,position:0,duration:5,playing:true};return true;},snapshot:()=>snap,scheduleNext:()=>events.push("schedule"),stop(){},cancelNext(){}};
  c.apiGet=async()=>({title:"one"});c.nextIndexPeek=()=>1;c.currentPlaybackNavContext=()=>({kind:"metalist"});
  for(const name of ["wireAudio","buildPlaybackSessionUpdate","loadVisualizerAnalysisForTrack","finishVisualizerTrackTransition","updateNowPlayingDisplay","updateMediaSession","syncMediaSessionControls","lastfmOnTrack","syncMediaSessionPosition","renderInfoPillLabels"])c[name]=()=>{};
  c.playbackMaybePost=(...args)=>events.push(args.at(-1));c.setInterval=()=>1;c.clearInterval=()=>{};
  if(nativeFirstStart) await c.gaplessDecodeItem(item);
  assert.equal(await c.startGaplessAudioFromItem(item,[item,next],0,false,0,0,{nativeFirstStart,onSlowStart:()=>{events.push("native-play");return true;}}),true);
  assert.equal(c.activeAudio,media);assert.equal(events.includes("native-play"),false);assert.ok(events.includes(.12));assert.ok(events.includes("start"));
  c.state.preloadEnabled=false;await c.preloadNextAudio();assert.equal(c.gaplessBufferCache.size,0);
});

test("gapless UI keeps the actual played fill while seek mode previews a target",()=>{
  const c=loadLoader();
  const seek={value:"123"};
  let fill=null;
  c.npSeek=seek;c.npSeekDragging=false;c.seekMode=true;
  c.updateProgressMeterFill=value=>{fill=value;};
  c.renderInfoPillLabels=()=>{};c.syncMediaSessionPosition=()=>{};c.syncMediaSessionControls=()=>{};
  c.activeAudio={tick:()=>{}};
  c.window.DebriPod.gaplessAudio={snapshot:()=>({duration:100,position:20,playing:true})};
  c.updateGaplessUi();
  assert.equal(fill,20);
  assert.equal(seek.value,"123");
});

test("cold first playback starts before the following decode completes",async()=>{
  const c=loadLoader();c.AbortController=AbortController;
  const events=[];let snap=null;let resolveNext;
  const media={__gapless:true,paused:false,currentTime:0,duration:5,setTransportLevel(){},addEventListener(){},tick(){}};
  const item={root:{id:"r"},rel:"one",media:"audio"},next={root:{id:"r"},rel:"two",media:"audio"};
  c.state={preloadEnabled:true,gaplessEnabled:true,playlist:[item,next],playIndex:0,playbackSession:{}};
  c.npSeek=null;c.npSeekDragging=false;c.seekMode=false;
  c.audioMain=c.activeAudio={pause(){},removeAttribute(){},load(){},play(){return Promise.resolve();}};
  c.window.DebriPod.gaplessAudio={
    supported:()=>true,
    decode:async(it)=>it.rel==="one"?{duration:5}:new Promise(resolve=>{resolveNext=resolve;}),
    resumeContext:async()=>true,takePrestarted:()=>false,media,
    start:(it)=>{events.push("start:"+it.rel);snap={key:c.gaplessItemKey(it),item:it,position:0,duration:5,playing:true};return true;},
    snapshot:()=>snap,scheduleNext:(it)=>events.push("schedule:"+it.rel),stop(){},cancelNext(){}
  };
  c.apiGet=async()=>({title:"one"});c.nextIndexPeek=()=>1;c.currentPlaybackNavContext=()=>({kind:"metalist"});
  for(const name of ["wireAudio","buildPlaybackSessionUpdate","loadVisualizerAnalysisForTrack","finishVisualizerTrackTransition","updateNowPlayingDisplay","updateMediaSession","syncMediaSessionControls","lastfmOnTrack","syncMediaSessionPosition","renderInfoPillLabels"])c[name]=()=>{};
  c.playbackMaybePost=()=>{};c.setInterval=()=>1;c.clearInterval=()=>{};
  const started=await c.startGaplessAudioFromItem(item,[item,next],0,false,0,0);
  assert.equal(started,true);
  assert.deepEqual(events,["start:one"]);
  resolveNext({duration:5});
  await new Promise(resolve=>setTimeout(resolve,0));
  assert.deepEqual(events,["start:one","schedule:two"]);
});

test("slow current decode hands off to native startup without waiting",async()=>{
  const c=loadLoader();c.AbortController=AbortController;
  const events=[];let releaseCurrent;
  const media={__gapless:true,paused:false,currentTime:0,duration:5,setTransportLevel(){},addEventListener(){},tick(){}};
  const item={root:{id:"r"},rel:"one",media:"audio"},next={root:{id:"r"},rel:"two",media:"audio"};
  c.state={preloadEnabled:true,gaplessEnabled:true,playlist:[item,next],playIndex:0,playbackSession:{}};
  c.npSeek=null;c.npSeekDragging=false;c.seekMode=false;
  c.audioMain=c.activeAudio={pause(){},removeAttribute(){},load(){},play(){return Promise.resolve();}};
  c.setTimeout=(fn)=>{fn();return 1;};c.clearTimeout=()=>{};
  c.window.DebriPod.gaplessAudio={
    supported:()=>true,
    decode:async(it)=>it.rel==="one"?new Promise(resolve=>{releaseCurrent=resolve;}):{duration:5},
    resumeContext:async()=>true,takePrestarted:()=>false,media,
    start:()=>{throw new Error("decoded start should not be reached");},snapshot:()=>null,scheduleNext(){},stop(){},cancelNext(){}
  };
  c.apiGet=async()=>({title:"one"});c.nextIndexPeek=()=>1;c.currentPlaybackNavContext=()=>({kind:"metalist"});
  const onSlowStart=async()=>{events.push("native-start");return true;};
  const started=await c.startGaplessAudioFromItem(item,[item,next],0,false,0,{onSlowStart});
  assert.equal(started,"native-started");
  assert.deepEqual(events,["native-start"]);
  releaseCurrent({duration:5});
  await new Promise(resolve=>setTimeout(resolve,0));
});

test("a superseded slow decode cannot start a stale native fallback",async()=>{
  const c=loadLoader();c.AbortController=AbortController;
  const item={root:{id:"r"},rel:"one",media:"audio"},next={root:{id:"r"},rel:"two",media:"audio"};
  c.state={preloadEnabled:true,gaplessEnabled:true,playlist:[item,next],playIndex:0,playbackSession:{}};
  c.window.DebriPod.gaplessAudio={
    supported:()=>true,decode:async()=>new Promise(()=>{}),resumeContext:async()=>true,takePrestarted:()=>false,
    media:{__gapless:true,setTransportLevel(){},addEventListener(){},tick(){}},stop(){},cancelNext(){},snapshot:()=>null
  };
  c.apiGet=async()=>({title:"one"});c.nextIndexPeek=()=>1;c.currentPlaybackNavContext=()=>({kind:"metalist"});
  let callbackCount=0;
  c.setTimeout=(fn)=>{c.stopGaplessPlayback();fn();return 1;};c.clearTimeout=()=>{};
  const started=await c.startGaplessAudioFromItem(item,[item,next],0,false,0,{onSlowStart:async()=>{callbackCount++;return true;}});
  assert.equal(started,true);
  assert.equal(callbackCount,0);
});
