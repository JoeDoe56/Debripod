import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const glue = fs.readFileSync(path.resolve(here, "../../debripod/static/js/liquid-glue.js"), "utf8");
const liquid = fs.readFileSync(path.resolve(here, "../../debripod/static/liquidGL.js"), "utf8");
const visualizer = fs.readFileSync(path.resolve(here, "../../debripod/static/js/visualizer-engine.js"), "utf8");

function extractFunction(source, name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} must remain independently testable`);
  const open = source.indexOf("{", start);
  let depth = 0;
  let quote = "";
  let escaped = false;
  for(let i = open; i < source.length; i++){
    const ch = source[i];
    if(quote){
      if(escaped) escaped = false;
      else if(ch === "\\") escaped = true;
      else if(ch === quote) quote = "";
      continue;
    }
    if(ch === '"' || ch === "'" || ch === "`") quote = ch;
    else if(ch === "{") depth += 1;
    else if(ch === "}" && --depth === 0) return source.slice(start, i + 1);
  }
  assert.fail(`${name} body is not balanced`);
}

test("glass uses only main and wheel render contexts", () => {
  assert.match(glue, /LIQUID_VISUALIZER_RENDERER_KEYS = \["main", "wheel"\]/);
  assert.match(glue, /rendererKey: "main"/);
  assert.match(glue, /rendererKey: "wheel"/);
  assert.doesNotMatch(glue, /rendererKey: "lib(?:List|Selection|Pills)"/);
  assert.match(glue, /syncLensGroup\("listPills"/);
});

test("reactive artwork is uploaded only on its art key and sampled as uniforms", () => {
  assert.match(liquid, /adapter && adapter\.ready && adapter\.image/);
  assert.match(liquid, /artKey === this\._reactiveArtKey && this\.texture/);
  assert.match(liquid, /_bindReactiveVisualizerUniforms\(fs\)/);
  assert.match(liquid, /u_reactiveBands\[9\]/);
  assert.match(visualizer, /return \{image:visualizerArtField\.image, artKey:/);
  assert.doesNotMatch(visualizer, /return \{canvas:visualizerBg/);
});

test("the glass backing scale is independent of device DPR and frost is deterministic", () => {
  assert.match(liquid, /glassRenderScale/);
  assert.match(liquid, /_configuredFrostSamples\(\)/);
  assert.match(liquid, /value : 8/);
  assert.match(liquid, /const int MAX_FROST_SAMPLES = 16/);
  assert.doesNotMatch(liquid, /random\(v_uv/);
  assert.match(liquid, /antialias: false/);
  assert.match(liquid, /depth: false/);
  assert.match(liquid, /stencil: false/);
  assert.match(liquid, /preserveDrawingBuffer: false/);
  assert.doesNotMatch(liquid, /getContext\("webgl2"/);
  assert.doesNotMatch(liquid, /this\.el\.style\.pointerEvents\s*=\s*["']none["']/);
});

test("glass composites premultiplied overlap and smooths power-of-two source minification", () => {
  assert.match(liquid, /gl\.enable\(gl\.BLEND\)/);
  assert.match(liquid, /gl\.blendFunc\(gl\.ONE, gl\.ONE_MINUS_SRC_ALPHA\)/);
  assert.match(liquid, /isPowerOfTwoTexture\(width, height\)/);
  assert.match(liquid, /gl\.generateMipmap\(gl\.TEXTURE_2D\)/);
  assert.match(visualizer, /visualizerTextureUsesMipmaps/);
  assert.match(visualizer, /gl\.generateMipmap\(gl\.TEXTURE_2D\)/);
});

test("glass follows per-render DOM geometry including the bouncing center", () => {
  assert.match(glue, /liveGeometry: true/);
  assert.match(liquid, /this\._syncDomRect = this\.options\.liveGeometry === true/);
  assert.match(liquid, /else if \(this\.lenses\.some\(\(lens\) => lens && lens\._syncDomRect\)\)/);
  assert.match(liquid, /this\._mirrorActive && this\._baseRect/);
  assert.doesNotMatch(liquid, /_liveMirrorBaseRect/);
});

test("NP teardown unregisters transient lenses, cancels selection work, and restores on return", () => {
  const context = {
    listSelectionMotion: {raf: -1},
    frameScheduler: () => ({cancel(key){ context.cancelled = key; }}),
    cancelAnimationFrame(id){ context.cancelledRaf = id; },
    clearTimeout(id){ context.clearedTimer = id; },
  };
  vm.createContext(context);
  vm.runInContext([
    extractFunction(glue, "syncLibTransientLenses"),
    extractFunction(glue, "cancelLibSelectionMotion"),
  ].join("\n"), context);

  const selected = {id: "libListSelectedGlass", isConnected: true};
  const pill = {isConnected: true, matches(selector){ return selector === ".ipodPill[data-liquid-row-pill]"; }};
  const other = {isConnected: true};
  const destroyed = [];
  const lens = (el, group) => ({el, _dpLensGroup: group, destroy(){destroyed.push(el);}});
  const renderer = {
    lenses: [lens(selected), lens(pill), lens(other, "pathPill")],
    addLens(el){ const next = lens(el); this.lenses.push(next); return next; },
    renderCount: 0,
    render(){ this.renderCount += 1; },
  };

  context.syncLibTransientLenses(renderer, {
    active: false,
    selectedElement: selected,
    pillElements: [pill],
  });
  assert.deepEqual([...renderer.lenses].map((item) => item.el), [other]);
  assert.equal(destroyed.length, 2, "NP removes both selected and row-pill lenses");
  renderer.render();
  assert.equal(renderer.lenses.some((item) => item.el === selected || item.el === pill), false);

  context.cancelLibSelectionMotion();
  assert.equal(context.cancelled, "lib-selection-motion");
  assert.equal(context.listSelectionMotion.raf, 0);
  context.listSelectionMotion.raf = 17;
  context.cancelLibSelectionMotion();
  assert.equal(context.cancelledRaf, 17, "native selection RAF is cancelled too");

  context.syncLibTransientLenses(renderer, {
    active: true,
    selectedElement: selected,
    pillElements: [pill],
  });
  assert.equal(renderer.lenses.some((item) => item.el === selected), true, "selected lens returns after NP");
  assert.equal(renderer.lenses.some((item) => item.el === pill), true, "row-pill lens returns after NP");
});

test("selected-row settings preview never re-registers a removed lens", () => {
  const preview = extractFunction(glue, "previewLiquidGlassElementMaterial");
  assert.match(preview, /selectedRow:\[document\.getElementById\("libListSelectedGlass"\)\]/);
  assert.doesNotMatch(preview, /liquidGL\s*\(/, "settings preview only styles existing DOM");
});

test("artwork recovers after a temporary unavailable source, including the same album", () => {
  let adapter = {ready:true, image:{}, artKey:"album:a"};
  let uploads = 0;
  const context = {window:{innerWidth:400, innerHeight:800, DebriPod:{visualizerRenderer:{sourceForLiquidGL:()=>adapter}}}};
  vm.createContext(context);
  const start = liquid.indexOf('    refreshSourceTexture(reason = "") {');
  const end = liquid.indexOf('    _createAlbumTexture()', start);
  const method = vm.runInContext('({' + liquid.slice(start,end) + '}).refreshSourceTexture', context);
  const renderer = {sourceType:"visualizerWebgl", sourceRefreshCount:0, _resolveSourceElement:()=>null,
    updateTextureFromImage(){uploads++; this.texture={}; this._sourceIsSolidFallback=false; return true;},
    updateTextureFromSolidColor(){this.texture={}; this._sourceIsSolidFallback=true; return true;}};
  method.call(renderer);
  assert.equal(uploads,1);
  method.call(renderer);
  assert.equal(uploads,1);
  adapter = {ready:false};
  method.call(renderer);
  assert.equal(renderer._reactiveArtActive,false);
  adapter = {ready:true,image:{},artKey:"album:a"};
  method.call(renderer);
  assert.equal(uploads,2);
  assert.equal(renderer._sourceIsSolidFallback,false);
});

test("glass stack capture reallocates only on resize and reuses the texture", () => {
  const calls = [];
  const gl = new Proxy({}, {get:(_target,key)=>key === "createTexture" ? ()=>({}) : (...args)=>calls.push([key,...args])});
  const context = {};
  vm.createContext(context);
  const start = liquid.indexOf('    _captureUnderGlass() {');
  const end = liquid.indexOf('    _lensVisible(lens)', start);
  const method = vm.runInContext('({' + liquid.slice(start,end) + '})._captureUnderGlass', context);
  const renderer = {gl, canvas:{width:400,height:800},u:{}};
  method.call(renderer);
  method.call(renderer);
  assert.equal(calls.filter(c=>c[0] === "copyTexImage2D").length,1);
  assert.equal(calls.filter(c=>c[0] === "copyTexSubImage2D").length,1);
  renderer.canvas.width=800;
  method.call(renderer);
  assert.equal(calls.filter(c=>c[0] === "copyTexImage2D").length,2);
});

test("shared scheduler resolves the app namespace and carries visualizer state into glass frames", () => {
  const scheduler = {mark(){}};
  let rendered = null;
  const context = {window:{DebriPod:{frameScheduler:scheduler}},
    updateGlassTextUnderColors(){}, updateLibSelectionGlass(){},
    liquidGlassRenderers:()=>[{render:frame=>{rendered=frame;}}], rendererTargetVisible:()=>true,
    currentVisualizerFrameState:()=>({fade:.8,active:true,angleRadians:2.4}),
    positionMainLiquidCanvas(){}};
  vm.createContext(context);
  vm.runInContext(extractFunction(glue,"frameScheduler") + extractFunction(glue,"renderLiquidGlassNow"),context);
  assert.equal(context.frameScheduler(),scheduler);
  context.renderLiquidGlassNow({timestamp:100,flags:{render:true}});
  assert.equal(rendered.fade,.8);
  assert.equal(rendered.angleRadians,2.4);
  assert.equal(rendered.timestamp,100);
});

test("rounded lens shadows stay on the element and never spawn detached clones",()=>{
  const start=liquid.indexOf('    setShadow(enabled, strength) {');
  const end=liquid.indexOf('    _reveal()',start);
  const context={clamp:(n,a,b)=>Math.max(a,Math.min(b,n)),finiteNumber:(n,f)=>Number.isFinite(Number(n))?Number(n):f,window:{removeEventListener(){}}};
  vm.createContext(context);
  const method=vm.runInContext('({'+liquid.slice(start,end)+'}).setShadow',context);
  let removed=0;
  const lens={options:{},el:{style:{}},originalShadow:'none',_shadowEl:{remove(){removed++;}},_shadowValue:()=> 'rounded-shadow'};
  method.call(lens,true,.2);
  assert.equal(removed,1);assert.equal(lens._shadowEl,null);assert.equal(lens.el.style.boxShadow,'rounded-shadow');
  method.call(lens,false,.2);assert.equal(lens.el.style.boxShadow,'none');
});

test("reactive glass shares crossfade progress and uploads outgoing artwork only once",()=>{
  const start=liquid.indexOf('    _bindReactiveVisualizerUniforms(frameState) {');
  const end=liquid.indexOf('    _globalLightingState()',start);
  const context={window:{innerWidth:400,innerHeight:800},Float32Array};vm.createContext(context);
  const method=vm.runInContext('({'+liquid.slice(start,end)+'})._bindReactiveVisualizerUniforms',context);
  const uniforms=new Map();
  const gl=new Proxy({}, {get:(_t,key)=>String(key).startsWith('uniform') ? (name,value)=>uniforms.set(name,value) : ()=>{}});
  let uploads=0;
  const renderer={gl,texture:{},_reactiveArtActive:true,u:new Proxy({}, {get:(_t,key)=>key}),_uploadAlbumImageTexture(){uploads++;return {};}};
  const transition={active:true,fromImage:{},fromKey:'old',progress:.25,fromAngle:7,toAngle:Math.PI};
  method.call(renderer,{artTransition:transition,fade:1});
  assert.equal(uniforms.get('reactiveArtMix'),.25);assert.equal(uniforms.get('reactivePreviousAngle'),7);assert.equal(uniforms.get('reactiveAngle'),Math.PI);
  transition.progress=.75;method.call(renderer,{artTransition:transition,fade:1});
  assert.equal(uploads,1);assert.equal(uniforms.get('reactiveArtMix'),.75);
  method.call(renderer,{fade:1,angleRadians:9});assert.equal(uniforms.get('reactiveArtMix'),1);assert.equal(uniforms.get('reactiveAngle'),9);
});
