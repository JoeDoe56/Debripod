import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const sourcePath = path.resolve(here, "../../debripod/static/js/gapless-audio.js");
const source = fs.readFileSync(sourcePath, "utf8");

function load(){
  const starts = [];
  const context = {
    currentTime: 10,
    state: "running",
    destination: {},
    createGain(){ return {gain:{value:1},connect(){}}; },
    createBufferSource(){
      const node = {buffer:null,onended:null,connect(){},disconnect(){},stop(){},start(when,offset){ starts.push({when,offset,buffer:this.buffer}); }};
      return node;
    },
    decodeAudioData(){ return Promise.resolve({duration:3}); },
    resume(){ this.state="running"; return Promise.resolve(); }
  };
  const document = {hidden:false,addEventListener(){}};
  const window = {AudioContext:function(){return context;},document,addEventListener(){},fetch:async()=>({ok:true,arrayBuffer:async()=>new ArrayBuffer(0)})};
  const sandbox = {window,Promise,Number,String,Math,encodeURIComponent,setTimeout,clearTimeout};
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, {filename:sourcePath});
  return {api:window.DebriPod.gaplessAudio,context,starts};
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

test("promotes a prestarted next track without scheduling a duplicate source", ()=>{
  const {api,starts}=load();
  const first=item("one"), second=item("two");
  api.start(first,{duration:1},second,{duration:2});
  const session=api.testing.getSession();
  session.source.onended();
  assert.equal(api.takePrestarted(second), true);
  assert.equal(starts.length,2);
  assert.equal(api.snapshot().key, api.testing.keyFor(second));
});

