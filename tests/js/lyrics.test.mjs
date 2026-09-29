import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {parseLrc, activeLine, createController} = require('../../debripod/static/js/lyrics.js');

test('LRC supports repeated timestamps, offsets, fractions and seeks in either direction', () => {
  const lines = parseLrc('[ar:Artist]\n[offset:100]\n[01:02.500][00:01.25]Again\n[00:02]Next\n[00:04.0]');
  assert.deepEqual(lines, [{time:1.35,text:'Again'}, {time:2.1,text:'Next'}, {time:4.1,text:''}, {time:62.6,text:'Again'}]);
  assert.equal(activeLine(lines, 0), -1);
  assert.equal(activeLine(lines, 70), 3);
  assert.equal(activeLine(lines, 2.2), 1);
});

class Element {
  constructor(){ this.children=[]; this.dataset={}; this.style={setProperty(){}}; this.attrs={}; this.classList={toggle(){}}; this.clientHeight=100; this.offsetTop=0; }
  append(...nodes){this.children.push(...nodes);}
  appendChild(node){this.children.push(node);}
  replaceChildren(){this.children=[];}
  setAttribute(k,v){this.attrs[k]=v;}
  removeAttribute(k){delete this.attrs[k];}
}
function fixture(fetch){
  const host=new Element();host.style.display='block';
  const media={currentTime:0,duration:20};let interval;
  const env={document:{getElementById:()=>host,createElement:()=>new Element()},state:{nowMeta:{title:'First',artist:'Artist',album:'Album',duration:20}},
    wheelMedia:()=>media, AbortController,fetch,setTimeout,clearTimeout,setInterval(fn){interval=fn;return 1;},clearInterval(){interval=null;}};
  const api=createController(env);
  return {api,env,host,media,tick(){interval?.();},panel:()=>host.children[0]};
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
test('visible lyrics follow playback, pause position, backwards seek and new tracks', async()=>{
  let calls=0;
  const f=fixture(async()=>({ok:true,json:async()=>({ok:true,lyrics:{syncedLyrics:`[00:01]Track ${++calls}\n[00:10]Later`}})}));
  f.api.setOpen(true);await flush();
  const content=f.panel().children[1];
  f.media.currentTime=11;f.tick();assert.equal(content.children[1].attrs['aria-current'],'true');
  f.tick();assert.equal(calls,1);
  f.media.currentTime=2;f.tick();assert.equal(content.children[0].attrs['aria-current'],'true');
  f.env.state.nowMeta.title='Second';f.tick();await flush();
  assert.equal(content.children[0].textContent,'Track 2');
  f.api.setOpen(false);assert.equal(f.panel().attrs['aria-hidden'],'true');
});
test('stale track responses cannot overwrite the current recording', async()=>{
  const requests=[];
  const f=fixture(()=>new Promise(resolve=>requests.push(resolve)));
  f.api.setOpen(true);
  f.env.state.nowMeta.title='Second';f.tick();
  requests[1]({ok:true,json:async()=>({ok:true,lyrics:{plainLyrics:'Second words'}})});await flush();
  requests[0]({ok:true,json:async()=>({ok:true,lyrics:{plainLyrics:'Stale words'}})});await flush();
  assert.equal(f.panel().children[1].children[0].textContent,'Second words');
  f.api.setOpen(false);
});
test('plain, missing, instrumental and API errors have distinct visible states; errors retry', async()=>{
  for(const [lyrics,expected] of [[{plainLyrics:'One\nTwo'},'plain'],[null,'missing'],[{instrumental:true},'instrumental']]){
    const f=fixture(async()=>({ok:true,json:async()=>({ok:true,lyrics})}));
    f.api.setOpen(true);await flush();assert.equal(f.panel().dataset.mode,expected);f.api.setOpen(false);
  }
  let calls=0;
  const f=fixture(async()=>{calls++;throw new Error('offline');});
  f.api.setOpen(true);await flush();assert.match(f.panel().children[0].textContent,/unavailable/);
  f.api.setOpen(false);f.api.setOpen(true);await flush();assert.equal(calls,2);f.api.setOpen(false);
});
