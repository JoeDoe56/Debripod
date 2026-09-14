import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../../debripod/static/js/performance-overlay.js',import.meta.url),'utf8');
function load(){
 const listeners=new Map(),elements=[];
 const settings={performanceOverlayText:false};
 const node=()=>({style:{},hidden:false,setAttribute(){},addEventListener(name,fn){this[name]=fn;},getBoundingClientRect:()=>({left:0,top:0,right:34,bottom:34,width:34,height:34})});
 const document={readyState:'complete',body:{appendChild(el){elements.push(el);}},createElement:node,getElementById:()=>null};
 const window={innerWidth:400,innerHeight:800,addEventListener:(key,fn)=>listeners.set(key,fn),DebriPod:{uiSettings:{settings,saveUiSettings(){}}}};
 vm.runInNewContext(source,{window,document,setInterval:()=>1,clearInterval(){}});
 return {api:window.DebriPod.performanceOverlay,settings,listeners,elements};
}
test('P toggles the overlay independently of the hidden button and ignores typing',()=>{
 const f=load(),key=f.listeners.get('keydown');
 assert.equal(f.elements[0].style.opacity,'0');
 key({key:'p',preventDefault(){}});assert.equal(f.settings.performanceOverlayText,true);
 key({key:'P',repeat:true});assert.equal(f.settings.performanceOverlayText,true);
 key({key:'p',target:{isContentEditable:true}});assert.equal(f.settings.performanceOverlayText,true);
 key({key:'p',preventDefault(){}});assert.equal(f.settings.performanceOverlayText,false);
});
test('rub requires sustained reversals and rejects pauses or one-way swipes',()=>{
 const {rubSample}=load().api.testing;
 const start=()=>({x:0,y:0,startedAt:0,lastAt:0,turns:0,distance:0,direction:0});
 let s=start();for(let t=80;t<=1600;t+=80)s=rubSample(s,t%160===0?-10:10,0,t);
 assert.equal(s.complete,true);
 s=start();for(let t=80;t<=1600;t+=80)s=rubSample(s,t,0,t);
 assert.equal(s.complete,false);
 assert.equal(rubSample(start(),10,0,500),null);
});
