import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const sourcePath = path.resolve(here, "../../debripod/static/js/gapless-audio.js");
const source = fs.readFileSync(sourcePath, "utf8");

function load(options={}){
  const starts = [];
  const context = {
    currentTime: 10,
    state: "running",
    destination: {},
    createGain(){ const connections=new Set();this.output={gain:{value:1},connections,connect(node){connections.add(node);},disconnect(node){if(node)connections.delete(node);else connections.clear();}};return this.output; },
    createBufferSource(){
      const node = {buffer:null,playbackRate:{value:1},onended:null,connect(){},disconnect(){},stop(){this.stopped=true;},start(when,offset){ starts.push({when,offset,buffer:this.buffer}); }};
      return node;
    },
    decodeAudioData(){ return Promise.resolve({duration:3}); },
    resume(){ this.state="running"; return Promise.resolve(); }
  };
  const bridgeNodes=[];
  const document = {
    hidden:false,addEventListener(){},body:{appendChild(node){bridgeNodes.push(node);}},documentElement:{appendChild(node){bridgeNodes.push(node);}},
    createElement(name){
      if(name!=="audio")return {style:{},setAttribute(){}};
      return {style:{},setAttribute(){},playCalls:0,pauseCalls:0,play(){this.playCalls++;return Promise.resolve();},pause(){this.pauseCalls++;}};
    }
  };
  if(options.ios)context.createMediaStreamDestination=()=>({stream:{id:"gapless-stream"}});
  const window = {AudioContext:function(){return context;},document,navigator:options.ios?{userAgent:"iPhone",platform:"iPhone",maxTouchPoints:5}:{userAgent:"Chrome",platform:"Win32",maxTouchPoints:0},addEventListener(){},fetch:async()=>({ok:true,arrayBuffer:async()=>new ArrayBuffer(0)})};
  const sandbox = {window,Promise,Number,String,Math,encodeURIComponent,setTimeout,clearTimeout};
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, {filename:sourcePath});
  return {api:window.DebriPod.gaplessAudio,context,starts,bridgeNodes};
}

const item = (rel)=>({root:{id:"root"},rel});

test("schedules the next buffer at the current buffer's exact sample timeline", ()=>{
  const {api,starts}=load();
  const current={duration:3}, next={duration:2};
  assert.equal(api.start(item("one"), current, item("two"), next, {offset:1}), true);
  assert.deepEqual(starts.map(x=>({when:x.when,offset:x.offset})), [
    {when:10.025,offset:1},
    {when:12.025,offset:0}
  ]);
});

test("uses one configured intentional gap when gapless mode is disabled", ()=>{
  const {api,starts}=load();
  api.start(item("one"), {duration:3}, item("two"), {duration:2}, {gap:0.12});
  assert.ok(Math.abs(starts[1].when - 13.145) < 1e-9);
  const session=api.testing.getSession();
  session.source.onended();
  assert.equal(api.snapshot().key, api.testing.keyFor(item("one")));
});

test("promotes a prestarted next track without scheduling a duplicate source", ()=>{
  const {api,context,starts}=load();
  const first=item("one"), second=item("two");
  api.start(first,{duration:1},second,{duration:2});
  const session=api.testing.getSession();
  context.currentTime=session.next.when;
  session.source.onended();
  assert.equal(api.takePrestarted(second), true);
  assert.equal(starts.length,2);
  assert.equal(api.snapshot().key, api.testing.keyFor(second));
});

test("keeps the sample timeline when a paused or sought track resumes and queues track three", ()=>{
  const {api,context,starts}=load();
  const first=item("one"), second=item("two"), third=item("three");
  api.start(first,{duration:1},second,{duration:2});
  assert.equal(api.pause(), true);
  assert.equal(api.resume(), true);
  assert.equal(api.testing.getSession().next.item.rel, "two");
  assert.equal(api.seek(0.5), true);
  const session=api.testing.getSession();
  context.currentTime=session.next.when;
  session.source.onended();
  assert.equal(api.snapshot().key, api.testing.keyFor(second));
  assert.equal(api.scheduleNext(third,{duration:4}), true);
  assert.equal(starts.at(-1).when, 12.525);
});


test("a paused source cannot emit a stale end that advances the queue",()=>{
  const {api,context}=load();let ended=0;
  api.start(item("one"),{duration:10},null,null,{onEnded:()=>ended++});
  context.currentTime=12;
  const old=api.testing.getSession().source;
  api.pause();
  assert.equal(old.onended,null);
  assert.equal(api.snapshot().position,1.9749999999999996);
  assert.equal(ended,0);
});

test("rate changes preserve the rendered clock and reschedule the next exact boundary",()=>{
  const {api,context}=load();
  api.start(item("one"),{duration:10},item("two"),{duration:3});
  context.currentTime=12.025;
  const oldNext=api.testing.getSession().next.source;
  api.media.playbackRate=.5;
  context.currentTime=14.025;
  assert.equal(api.media.currentTime,3);
  assert.equal(oldNext.stopped,true);
  assert.equal(api.testing.getSession().next.when,28.025);
});

test("skip cuts the outgoing source on the same clock as the incoming start",()=>{
  const {api,context,starts}=load();
  api.start(item("one"),{duration:10});
  const outgoing=api.testing.getSession().source;let stoppedAt;
  outgoing.stop=when=>{stoppedAt=when;};context.currentTime=12;
  api.start(item("two"),{duration:4},null,null,{gap:0});
  assert.equal(stoppedAt,starts.at(-1).when);
});

test("interrupted audio contexts are resumed without reloading the app",async()=>{
  const {api,context}=load();context.state="interrupted";
  assert.equal(await api.resumeContext(),true);assert.equal(context.state,"running");
});

test("iOS gapless output uses a single native media bridge for system controls",async()=>{
  const {api,bridgeNodes,context}=load({ios:true});
  assert.equal(api.supported(),true);
  const unlocked=api.testing.nativeBridge();
  assert.ok(unlocked);
  assert.equal(unlocked.playCalls,1);
  assert.equal(api.start(item("one"),{duration:3}),true);
  const bridge=api.testing.nativeBridge();
  assert.ok(bridge);
  assert.equal(bridge.srcObject.id,"gapless-stream");
  assert.equal(bridgeNodes.length,1);
  assert.equal(bridge.playCalls,2);
  assert.equal(api.pause(),true);
  assert.equal(bridge.pauseCalls,1);
  const calls=bridge.playCalls;api.supported();assert.equal(bridge.playCalls,calls,"preloading must not resume a paused sink");
  assert.equal(context.output.connections.size,1);
  assert.equal(context.output.connections.has(context.destination),false);
  assert.equal(api.resume(),true);
  assert.equal(bridge.playCalls,3);
});
