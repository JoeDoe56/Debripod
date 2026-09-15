import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import test from "node:test";

function extractFunction(source, marker){
  const start = source.indexOf(marker);
  assert.notEqual(start, -1, marker);
  const brace = source.indexOf("{", start);
  let depth = 0;
  let quote = "";
  let escaped = false;
  for(let index = brace; index < source.length; index += 1){
    const character = source[index];
    if(quote){
      if(escaped) escaped = false;
      else if(character === "\\") escaped = true;
      else if(character === quote) quote = "";
      continue;
    }
    if(character === "\"" || character === "'" || character === "`"){ quote = character; continue; }
    if(character === "{") depth += 1;
    else if(character === "}" && --depth === 0) return source.slice(start, index + 1);
  }
  throw new Error("unbalanced function");
}

function makeMotionContext(selected){
  const calls = [];
  const context = {
    window: {state: {items: Array.from({length: 2100}, () => ({kind: "track"})), sel: selected}},
    listSelectionMotion: {
      targetStretch: 0,
      targetDirection: 0,
      boundaryHeld: false,
      boundaryDirection: 0,
      boundaryLastInputTs: 0,
      boundaryReleaseTimer: 0,
    },
    scheduleLibSelectionMotion: () => calls.push("schedule"),
    setTimeout,
    clearTimeout,
    Date,
  };
  context.globalThis = context;
  return {context, calls};
}

test("actual list selection motion holds terminal stretch across repeated wheel input", async () => {
  const source = readFileSync("debripod/static/js/liquid-glue.js", "utf8");
  const setter = extractFunction(source, "function setLibSelectionStretch(progress)");
  const {context} = makeMotionContext(2099);
  vm.runInNewContext(setter, context);

  context.setLibSelectionStretch(0.35);
  context.setLibSelectionStretch(0.35);
  assert.equal(context.listSelectionMotion.targetStretch, 1);
  assert.equal(context.listSelectionMotion.boundaryHeld, true);
  assert.equal(context.listSelectionMotion.boundaryDirection, 1);

  context.setLibSelectionStretch(0);
  assert.equal(context.listSelectionMotion.targetStretch, 1);
  await new Promise((resolve) => setTimeout(resolve, 115));
  assert.equal(context.listSelectionMotion.targetStretch, 0);
  assert.equal(context.listSelectionMotion.boundaryHeld, false);
});

test("actual list selection motion releases terminal pull on direction change", () => {
  const source = readFileSync("debripod/static/js/liquid-glue.js", "utf8");
  const setter = extractFunction(source, "function setLibSelectionStretch(progress)");
  const {context} = makeMotionContext(0);
  vm.runInNewContext(setter, context);
  context.setLibSelectionStretch(-0.5);
  assert.equal(context.listSelectionMotion.targetStretch, 1);
  context.window.state.sel = 1;
  context.setLibSelectionStretch(0.5);
  assert.equal(context.listSelectionMotion.targetStretch, 0);
  assert.equal(context.listSelectionMotion.boundaryHeld, false);
});


test("rapid selection fades the lens and restores it after input settles",()=>{
  const source = readFileSync("debripod/static/js/liquid-glue.js", "utf8");
  const timers = new Map(); let id = 0;
  const context = {listSelectionMotion:{},setTimeout:fn=>{timers.set(++id,fn);return id;},clearTimeout:id=>timers.delete(id),updateLibSelectionGlass:()=>{}};
  vm.runInNewContext(extractFunction(source,"function noteLibSelectionInput(now)"),context);
  for(const t of [100,180,260]) context.noteLibSelectionInput(t);
  assert.equal(context.listSelectionMotion.rapidInput,true);
  assert.equal(timers.size,1);
  for(const fn of timers.values())fn();
  assert.equal(context.listSelectionMotion.rapidInput,false);
  context.noteLibSelectionInput(1000);
  assert.equal(context.listSelectionMotion.rapidInput,false);
});

test("selected foreground follows the lens vertically with no redundant style writes",()=>{
  const source = readFileSync("debripod/static/js/list-view.js", "utf8");
  const values = new Map(); let writes = 0;
  const row = {style:{setProperty:(k,v)=>{values.set(k,v);writes++;},getPropertyValue:k=>values.get(k),removeProperty:k=>values.delete(k)}};
  const context = {libList:{querySelector:()=>row}};
  vm.runInNewContext(extractFunction(source,"function setSelectedRowContentOffset(currentY, targetY)"),context);
  assert.equal(context.setSelectedRowContentOffset(120,140),-20);
  assert.equal(values.get("--dp-selected-content-offset-y"),"-20.000px");
  context.setSelectedRowContentOffset(120,140);
  assert.equal(writes,1);
  context.setSelectedRowContentOffset(140,140);
  assert.equal(values.get("--dp-selected-content-offset-y"),"0.000px");
});


test("unselected overflowing labels retain their fade but never start scrolling",()=>{
  const source = readFileSync("debripod/static/js/path-pill.js", "utf8");
  const classes = new Set();
  const label = {scrollWidth:200,clientWidth:100,scrollLeft:42,closest:()=>null,classList:{toggle:(k,on)=>on?classes.add(k):classes.delete(k),remove:k=>classes.delete(k)}};
  const context = {libList:{querySelectorAll:()=>[label]},libHeader:null,cancelAnimationFrame(){},clearTimeout(){}};
  const functions = ["hScrollTextIsScrollable(el)","stopHScrollTextAuto(el)","refreshSelectedHScrollText()"];
  vm.runInNewContext(functions.map(name=>extractFunction(source,"function "+name)).join("\n"),context);
  context.refreshSelectedHScrollText();
  assert.equal(classes.has("hScrollTextScrollable"),true);
  assert.equal(label._dpHScrollAutoRunning,false);
  assert.equal(label.scrollLeft,0);
});
