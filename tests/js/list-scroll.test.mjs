import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import fs from 'node:fs';
import vm from 'node:vm';
const {createListScrollController}=createRequire(import.meta.url)('../../debripod/static/js/list-scroll.js');

function fixture(){
  let clock=0,id=0,cancelled=0;const timers=new Map(),events=[];
  const controller=createListScrollController({now:()=>clock,capture:()=>({anchor:145}),cancelProgrammatic:()=>cancelled++,
    setTimeout:(fn,delay)=>{timers.set(++id,{fn,at:clock+delay});return id;},clearTimeout:key=>timers.delete(key)});
  controller.subscribe(event=>events.push(event));
  function advance(ms){clock+=ms;for(const [key,timer] of [...timers])if(timer.at<=clock){timers.delete(key);timer.fn();}}
  return {controller,events,advance,cancelled:()=>cancelled};
}

test('finger pauses never restore selection before lifting; momentum retains the original anchor',()=>{
  const {controller:c,events,advance}=fixture();
  c.beginDirect({top:0});c.onScroll(100,{inputActive:true});advance(500);
  assert.equal(c.isDirectScrolling(),true);
  c.endDirect();advance(100);c.onScroll(150,{inputActive:false});advance(100);
  assert.equal(c.isDirectScrolling(),true);advance(41);
  assert.equal(c.isDirectScrolling(),false);
  assert.equal(events.at(-1).snapshot.anchor,145);
  assert.equal(events.filter(e=>!e.active).length,1);
});

test('page changes cancel pending selection restoration; programmatic scrolling stays idle',()=>{
  const {controller:c,events,advance}=fixture();
  assert.equal(c.onScroll(400,{programmatic:true}),false);
  assert.equal(c.isDirectScrolling(),false);
  c.beginDirect();c.endDirect();c.cancel('page-change');advance(500);
  assert.equal(events.at(-1).cancelled,true);
  assert.equal(events.filter(e=>!e.active).length,1);
});

test('a new touch during momentum keeps the screen anchor and cancels the old settle timer',()=>{
  const {controller:c,events,advance,cancelled}=fixture();
  c.beginDirect();c.endDirect();advance(100);c.beginDirect();advance(300);
  assert.equal(c.isDirectScrolling(),true);assert.equal(cancelled(),2);
  assert.equal(events.filter(e=>e.reason==='scroll-start').length,1);
  c.endDirect();c.settle('native-scrollend');advance(300);
  assert.equal(events.filter(e=>!e.active).length,1);
});

test('wheel animation settles on browsers that round scrollTop to whole pixels',()=>{
  const source=fs.readFileSync('debripod/static/js/list-view.js','utf8');
  const animation=source.slice(source.indexOf('  function animateLibListScrollTo('),source.indexOf('  function estimatedItemHeight('));
  let top=0,clock=0,job=null;
  const list={scrollHeight:1000,clientHeight:100,get scrollTop(){return top;},set scrollTop(value){top=Math.round(value);}};
  const root={frameScheduler:{request:(_key,fn)=>{job=fn;}}};
  const context={libList:list,DebriPod:root,window:{DebriPod:root},performance:{now:()=>clock},flushLibScrollFrame:()=>{}};
  vm.runInNewContext(animation,context);
  context.animateLibListScrollTo(100);
  for(let i=0;i<120 && job;i++){
    const fn=job;job=null;clock+=8;fn({timestamp:clock});
    if(i===10)context.animateLibListScrollTo(215);
  }
  assert.equal(top,215);assert.equal(list._dpScrollAnimTarget,null);assert.equal(job,null);
});
