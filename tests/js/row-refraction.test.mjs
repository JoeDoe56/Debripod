import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../../debripod/static/js/row-refraction.js", import.meta.url), "utf8");

function fixture(){
  const draws=[]; const clips=[]; const gradients=[];
  const textParent={style:{opacity:".8"},parentElement:null};
  const text={nodeValue:"Neighbor",parentElement:textParent};
  const style={clipPath:"",webkitClipPath:"",clipRule:"",webkitClipRule:"",maskImage:"linear-gradient(to right, transparent, black 16px)",webkitMaskImage:"linear-gradient(to right, transparent, black 16px)",getPropertyValue:name=>name==="--path-text-fade"?"18px":""};
  const el={textContent:"Neighbor",style,dataset:{scrollAway:"true"},classList:{contains:name=>name==="dpRowText"},closest:()=>el,getBoundingClientRect:()=>({left:20,top:40,right:120,bottom:60,width:100,height:20})};
  const ctx={setTransform(){},save(){},restore(){},beginPath(){},rect:(...args)=>clips.push(args),clip(){},createLinearGradient:()=>{const gradient={stops:[],addColorStop:(offset,color)=>gradient.stops.push([offset,color])};gradients.push(gradient);return gradient;},measureText:()=>({actualBoundingBoxAscent:12,actualBoundingBoxDescent:3}),fillText:(...args)=>draws.push({args,alpha:ctx.globalAlpha})};
  const listRect={left:0,top:0,right:300,bottom:400,width:300,height:400};
  const list={dataset:{rowSystem:"standard"},getBoundingClientRect:()=>listRect,querySelector:()=>null,querySelectorAll:selector=>{assert.equal(selector,".ipodItem:not(.sel) .glassText, .ipodItem:not(.sel) .dpRowPrimary, .ipodItem:not(.sel) .dpRowSecondary");return [el];}};
  const document={getElementById:()=>list,createElement:()=>({getContext:()=>ctx}),createTreeWalker(){let read=false;return{nextNode:()=>read?null:(read=true,text)};},createRange:()=>({selectNodeContents(){},getBoundingClientRect:el.getBoundingClientRect})};
  const window={devicePixelRatio:2,DebriPod:{}};
  const context={window,document,NodeFilter:{SHOW_TEXT:4},getComputedStyle:node=>{const opacity=node===textParent?".8":"1";return {opacity,font:"500 16px Host Grotesk",fontSize:"16px",fontWeight:"500",fontFamily:"Host Grotesk",color:"rgba(255,255,255,.45)",visibility:"visible",display:"block",letterSpacing:"0px",getPropertyValue:name=>name==="--path-text-fade"?"18px":""};}};
  vm.runInNewContext(source,context);
  return {api:window.DebriPod.rowRefraction,list,style,draws,clips,gradients};
}

test("standard rows receive a stable rounded CSS cutout while retaining horizontal fades",()=>{
  const {api,style,draws,clips,gradients}=fixture();
  api.beginFrame();
  const result=api.prepare({left:10,top:50,width:200,height:44},22);
  api.endFrame();
  assert.ok(result&&result.canvas);
  assert.equal(draws.length,1);
  assert.equal(draws[0].alpha,.8);
  assert.deepEqual(gradients[0].stops[0][1],"transparent");
  assert.deepEqual(gradients[0].stops.at(-1)[1],"transparent");
  assert.match(style.clipPath,/^path\(evenodd, \"M/);
  assert.equal(style.clipRule,"evenodd");
  assert.equal(style.maskImage,"linear-gradient(to right, transparent, black 16px)");
  assert.ok(clips[0][1]<40,"text clip includes vertical glyph padding");
  api.clear();
  assert.equal(style.clipPath,"");
});

test("moving the lens updates the native cutout without redrawing the texture",()=>{
  const {api,style,draws}=fixture();
  api.prepare({left:10,top:50,width:200,height:44},22);
  const first=style.clipPath;
  const result=api.prepare({left:30,top:50,width:200,height:44},22);
  assert.notEqual(style.clipPath,first);
  assert.equal(draws.length,1);
  assert.equal(result.revision,1);
});

test("missing neighbors restore native styles",()=>{
  const {api,style,list}=fixture();
  api.prepare({left:10,top:50,width:200,height:44},22);
  list.querySelectorAll=()=>[];
  api.prepare({left:10,top:50,width:200,height:44},22);
  assert.equal(style.clipPath,"");
  assert.equal(style.maskImage,"linear-gradient(to right, transparent, black 16px)");
});

test("cutout uses actual lens geometry and no data SVG",()=>{
  const {api}=fixture();
  const value=api.testing.cutout({left:20,top:40,width:100,height:20},{left:10,top:45,width:200,height:44},6);
  assert.match(value,/^path\(evenodd, \"M/);
  assert.doesNotMatch(value,/data:image\/svg/);
  assert.match(value,/Q/);
});
