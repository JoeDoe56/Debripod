import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../../debripod/static/js/performance-overlay.js',import.meta.url),'utf8');
function load(){
 const listeners=new Map(),elements=[],timers=new Map(); let timerId=0;
 const settings={performanceOverlayText:false};
 const node=()=>({style:{},hidden:false,setAttribute(){},addEventListener(name,fn){this[name]=fn;},getBoundingClientRect:()=>({left:0,top:0,right:34,bottom:34,width:34,height:34})});
 const document={readyState:'complete',body:{appendChild(el){elements.push(el);}},createElement:node,getElementById:()=>null};
 const window={innerWidth:400,innerHeight:800,addEventListener:(key,fn)=>listeners.set(key,fn),DebriPod:{uiSettings:{settings,saveUiSettings(){}}}};
 vm.runInNewContext(source,{window,document,setInterval:()=>1,clearInterval(){},setTimeout:(fn)=>{timers.set(++timerId,fn);return timerId;},clearTimeout:id=>timers.delete(id)});
 return {api:window.DebriPod.performanceOverlay,settings,listeners,elements,flush:()=>{for(const fn of timers.values())fn();timers.clear();}};
}
test('P toggles the overlay independently of the hidden button and ignores typing',()=>{
 const f=load(),key=f.listeners.get('keydown');
 assert.equal(f.elements[0].style.opacity,'0');
 key({key:'p',preventDefault(){}});assert.equal(f.settings.performanceOverlayText,true);
 key({key:'P',repeat:true});assert.equal(f.settings.performanceOverlayText,true);
 key({key:'p',target:{isContentEditable:true}});assert.equal(f.settings.performanceOverlayText,true);
 key({key:'p',preventDefault(){}});assert.equal(f.settings.performanceOverlayText,false);
});
test('rapid triple taps reveal and hide without toggling the overlay',()=>{
 const f=load(),tap=f.api.testing.tapButton;
 for(const timeStamp of [10,150,300])tap({timeStamp});
 assert.equal(f.elements[0].style.opacity,'1');
 assert.equal(f.settings.performanceOverlayText,false);
 f.flush();assert.equal(f.settings.performanceOverlayText,false);
 for(const timeStamp of [800,900,1000])tap({timeStamp});
 assert.equal(f.elements[0].style.opacity,'0');
 assert.equal(f.settings.performanceOverlayText,false);
});
test('slow taps do not unlock; a visible single tap still toggles the overlay',()=>{
 const f=load(),tap=f.api.testing.tapButton;
 for(const timeStamp of [0,1000,2000]){tap({timeStamp});f.flush();}
 assert.equal(f.elements[0].style.opacity,'0');
 for(const timeStamp of [3000,3100,3200])tap({timeStamp});
 tap({timeStamp:4000});f.flush();
 assert.equal(f.settings.performanceOverlayText,true);
});
