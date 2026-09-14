import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../../debripod/static/js/frame-scheduler.js',import.meta.url),'utf8');
test('geometry work is visible to renderers in the same frame and does not run forever',()=>{
 let queued=null;const window={DebriPod:{}};
 vm.runInNewContext(source,{window,document:{hidden:false},requestAnimationFrame:fn=>{queued=fn;return 1;},cancelAnimationFrame(){queued=null;}});
 const scheduler=window.DebriPod.frameScheduler;const seen=[];
 scheduler.register('renderer',frame=>seen.push({...frame.flags}));
 scheduler.request('geometry',()=>scheduler.mark({metrics:true,render:true}));
 const frame=queued;queued=null;frame(100);
 assert.equal(seen[0].metrics,true);assert.equal(seen[0].render,true);assert.equal(queued,null);
});
