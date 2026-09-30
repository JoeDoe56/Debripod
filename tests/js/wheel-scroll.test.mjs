import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function fixture(){
  const source=fs.readFileSync('debripod/static/js/wheel-controls.js','utf8');
  const frames=new Map(),calls=[];let id=0;
  const context={window:{},nowPlaying:{style:{display:'none'}},
    requestAnimationFrame:fn=>{frames.set(++id,fn);return id;},cancelAnimationFrame:key=>frames.delete(key),
    dispatchControl:(...args)=>{calls.push(args);return Promise.resolve();}};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('  let selectionStepFrame='),source.indexOf('  var wheelCenterAnimation')),context);
  return {context,calls,frames,paint(){const jobs=[...frames.values()];frames.clear();jobs.forEach(fn=>fn());}};
}

test('bursts preserve every detent with one dispatch per paint',()=>{
  const {context:c,calls,frames,paint}=fixture();
  for(let i=0;i<9;i++)c.queueSelectionStep('scroll_forward');
  assert.equal(calls.length,0);assert.equal(frames.size,1);
  paint();assert.equal(calls.length,1);assert.equal(calls[0][1],'scroll_forward');assert.equal(calls[0][2].steps,9);
  paint();assert.equal(calls.length,1);
});

test('reversals drop stale distance and cancellation leaves no navigation backlog',()=>{
  const {context:c,calls,paint}=fixture();
  c.queueSelectionStep('scroll_forward');c.queueSelectionStep('scroll_forward');c.queueSelectionStep('scroll_back');
  paint();assert.equal(calls[0][1],'scroll_back');assert.equal(calls[0][2].steps,1);
  c.queueSelectionStep('scroll_forward');c.cancelSelectionStepQueue();paint();assert.equal(calls.length,1);
});

test('Now Playing keeps immediate volume and seek controls',()=>{
  const {context:c,calls,frames}=fixture();c.nowPlaying.style.display='block';
  c.queueSelectionStep('scroll_forward');c.queueSelectionStep('scroll_back');
  assert.equal(calls.length,2);assert.equal(frames.size,0);
});
