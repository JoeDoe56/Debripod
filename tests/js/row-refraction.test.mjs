import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../../debripod/static/js/row-refraction.js',import.meta.url),'utf8');
test('only overlapping neighboring text is masked, drawn once, and restored on teardown',()=>{
 const draws=[];
 const text={nodeValue:'Neighbor',parentElement:{}};
 const el={style:{maskImage:'original',webkitMaskImage:'original'},getBoundingClientRect:()=>({left:20,top:40,right:120,bottom:60,width:100,height:20})};
 const ctx={setTransform(){},save(){},restore(){},beginPath(){},rect(){},clip(){},measureText:()=>({actualBoundingBoxAscent:12,actualBoundingBoxDescent:3}),fillText:(...args)=>draws.push(args)};
 const list={getBoundingClientRect:()=>({left:0,top:0,right:300,bottom:400}),querySelectorAll(selector){assert.equal(selector,'.ipodItem:not(.sel) .glassText');return [el];}};
 const document={getElementById:()=>list,createElement:()=>({getContext:()=>ctx}),createTreeWalker(){let read=false;return {nextNode:()=>read?null:(read=true,text)};},createRange:()=>({selectNodeContents(){},getBoundingClientRect:el.getBoundingClientRect})};
 const window={devicePixelRatio:2,DebriPod:{}};
 vm.runInNewContext(source,{window,document,NodeFilter:{SHOW_TEXT:4},getComputedStyle:()=>({font:'16px sans-serif',fontSize:'16px',color:'rgba(255,255,255,.45)'})});
 const api=window.DebriPod.rowRefraction;
 api.beginFrame();const result=api.prepare({left:10,top:50,width:200,height:44},22);api.endFrame();
 assert.equal(draws.length,1);assert.ok(result.canvas.width>0);assert.match(decodeURIComponent(el.style.maskImage),/rx="22"/);
 api.beginFrame();api.endFrame();assert.equal(el.style.maskImage,'original');assert.equal(el.style.webkitMaskImage,'original');
});
