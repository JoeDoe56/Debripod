import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const motion=require('../../debripod/static/js/glass-motion.js');
const overlays=require('../../debripod/static/js/glass-overlays.js');
test('pill height and corner radius share progress without a radius plateau',()=>{
 const half=motion.interpolate({width:200,height:44,radius:999},{width:300,height:80,radius:16},.5);
 assert.equal(half.width,250);assert.equal(half.height,62);assert.equal(half.radius,19);
});
test('circle to rectangle and independent axis stretch share one clock',()=>{
 const half=motion.interpolate({width:100,height:100,radius:50,scaleX:1,scaleY:1},{width:240,height:80,radius:12,scaleX:.9,scaleY:1.2},.5);
 assert.equal(half.width,170);assert.equal(half.height,90);assert.equal(half.radius,31);assert.equal(half.scaleX,.95);assert.equal(half.scaleY,1.1);
});
test('geometry is frame-rate independent without overshoot',()=>{
 const a={width:100,height:100,radius:50},b={width:300,height:80,radius:16};
 const single=motion.advance(a,b,32,70),double=motion.advance(motion.advance(a,b,16,70),b,16,70);
 for(const key of ['width','height','radius'])assert.ok(Math.abs(single[key]-double[key])<1e-8);
});
test('overlay diff retains stable runs between changed characters',()=>{
 const runs=overlays.changes('Track 12 - X','Track 13 - Y');
 assert.deepEqual(runs.filter(x=>x.changed).map(x=>x.text),['3','Y']);
 assert.deepEqual(runs.filter(x=>!x.changed).map(x=>x.text),['Track 1',' - ']);
 assert.deepEqual(overlays.changes('A 👨‍👩‍👧 B','A 👨‍👩‍👦 B').filter(x=>x.changed).map(x=>x.text),['👨‍👩‍👦']);
});
