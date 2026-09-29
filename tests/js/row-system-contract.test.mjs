import test from "node:test";
import {createRequire} from "node:module";
const require=createRequire(import.meta.url);
require("../../debripod/static/js/ui-primitives.js");
const {model}=require("../../debripod/static/js/row-system.js");
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const source = fs.readFileSync(path.join(root, "debripod/static/js/row-system.js"), "utf8");
const style = fs.readFileSync(path.join(root, "debripod/static/row-system.css"), "utf8");

test("row system exposes shared panel and normalized value APIs", () => {
  for (const api of ["createRing", "createSelectedState", "setPanelProgress", "setPanelOpen", "isPanelOpen"]) {
    assert.match(source, new RegExp(`\\b${api}\\b`));
  }
  assert.match(source, /uiPrimitives\.createRing/);
  assert.doesNotMatch(source, /createElementNS\([\s\S]*?circle/);
});

test("context panel reflows list content and preserves a shared safe-zone token", () => {
  assert.match(style, /--dp-panel-width:30%/);
  assert.match(style, /right:calc\(var\(--dp-panel-progress\) \* \(var\(--dp-panel-width\) \+ var\(--dp-panel-gap\)\)\)/);
  assert.match(style, /--dp-row-safe-zone:var\(--panel-safe-zone/);
  assert.match(style, /-webkit-mask-image:linear-gradient/);
  assert.doesNotMatch(style, /--dp-panel-width:36%/);
});

test("metadata retains zero values, units and sparse navigation context without internal IDs", () => {
  const pairs=model.panelEntries({label:"Recording",sample_rate:96000,bit_depth:24,bitrate:320000,file_count:0,available:false,root:{id:"private-id"}},{});
  const values=Object.fromEntries(pairs);
  assert.equal(values["Sample rate"],"96 kHz");
  assert.equal(values["Bitrate"],"320 kb/s");
  assert.equal(values.Files,"0");
  assert.equal(values.Availability,"Unavailable");
  assert.ok(!JSON.stringify(values).includes("private-id"));
  assert.equal(model.itemDescription({kind:"metacat",cat:"albums"}),"Browse complete albums");
});

test("quality and watch rings consume actual index fields monotonically",()=>{
  assert.equal(model.itemNumber({track:"3/12"}),"3");
  assert.equal(model.itemProgress({completion_percent:50}),.5);
  assert.equal(model.itemProgress({position:30,duration:120}),.25);
  const quality=[{bitrate:128000},{bitrate:320000},{codec:"flac",sample_rate:44100,bit_depth:16},{codec:"flac",sample_rate:192000,bit_depth:24}].map(model.itemQuality);
  assert.ok(quality.every((value,index)=>index===0||value>quality[index-1]));
  assert.equal(model.itemQuality({}),null);
  assert.equal(model.itemSymbol({kind:"track",media:"audio"}),"");
});
