var volBarTimer = null;
var seekMode = false;
var seekChanged = false;
var seekPreview = 0;
var seekIdleTimer = null;

var npPillHideTimer = null;
var npPillSwapTimer = null;
var visualizerEnabled = !!uiSettings.visualizer;
var visualizerActive = false;
var visualizerTrackKey = "";
var visualizerSampleNonce = 0;
var visualizerStrength = normalizeVisualizerStrength(uiSettings.visualizerStrength);
var visualizerPresetName = normalizeVisualizerPreset(uiSettings.visualizerPreset);
var visualizerFpsLock = normalizeVisualizerFpsLock(uiSettings.visualizerFpsLock);
var visualizerStrengthTransition = null;
var defaultTheme = {
  accent: "rgba(10,132,255,.88)",
  accentStrong: "rgba(10,132,255,1)",
  accentSoft: "rgba(10,132,255,.18)",
  accentOutline: "rgba(10,132,255,.42)",
  accentBar: "rgba(10,132,255,.92)",
  accentGlow: "rgba(10,132,255,.36)",
  visualizerA: "rgba(10,132,255,.42)",
  visualizerB: "rgba(94,92,230,.30)",
  visualizerC: "rgba(255,69,58,.18)"
};

var defaultVisualizerPalette = [
  {r:10,g:132,b:255},
  {r:94,g:92,b:230},
  {r:255,g:69,b:58},
  {r:48,g:209,b:88}
];
var MAX_VISUALIZER_PALETTE_COLORS = 16;
var visualizerPaletteCache = new Map();
var visualizerPalette = defaultVisualizerPalette.slice();
var visualizerTargetPalette = defaultVisualizerPalette.slice();
var currentVisualizerPalette = null;
var selectedTextContrastMix = {low: 0.18, mid: 0.42, high: 0.40};
var selectedContrastRgb = {r:255,g:255,b:255};
var selectedPillContrastRgb = {r:255,g:255,b:255};
var visualizerPaletteDbPromise = null;
var visualizerAudioCtx = null;
var visualizerAnalyser = null;
var visualizerData = null;
var visualizerSources = new WeakMap();
var visualizerFrameHandle = 0;
var visualizerFrameTimer = 0;
var visualizerLastFrameTs = 0;
var visualizerEnergy = 0;
var visualizerBass = 0;
var visualizerMid = 0;
var visualizerTreble = 0;
var visualizerBands = [0, 0, 0, 0, 0, 0, 0];
var visualizerBpm = 120;
var visualizerBeatPulse = 0;
var visualizerBeatLastTs = 0;
var visualizerBeatEnergyAvg = 0;
var visualizerBeatIntervals = [];
var visualizerCanvasDpr = 0;
var visualizerCanvasW = 0;
var visualizerCanvasH = 0;
var visualizerGl = null;
var visualizerProgram = null;
var visualizerCopyProgram = null;
var visualizerBuffer = null;
var visualizerTexture = null;
var visualizerFramebuffer = null;
var visualizerUniforms = null;
var visualizerBandUniformData = new Float32Array(7);
var visualizerPaletteUniformData = new Float32Array(MAX_VISUALIZER_PALETTE_COLORS * 3);
var visualizerWebglUnavailable = false;
var visualizerVideoSampleCanvas = null;
var visualizerVideoSampleCtx = null;
var visualizerVideoSampleLastTs = 0;
var visualizerArtBounds = null;
var visualizerArtBoundsLastTs = 0;
var visualizerAnalysisNonce = 0;
var visualizerAnalysisRetryTimer = 0;
var visualizerVideoPaletteFrame = -1;
var visualizerVideoPaletteKey = "";
var visualizerAnalysisState = {
  key: "",
  loaded: false,
  loading: false,
  stale: false,
  rate: 30,
  stride: 9,
  bandCount: 7,
  frameCount: 0,
  bytes: null,
  rootId: "",
  rel: "",
  source: "",
  mediaKind: "",
  videoPaletteFrames: null,
  videoPalettePending: false
};

var VISUALIZER_STRENGTHS = {
  low: {dpr: 0.62, interval: 33, bassFields: 1, midFields: 1, trebleFields: 1, speed: 0.52, alpha: 0.28, bright: 0.52, coverage: 0.62, density: 0.04},
  medium: {dpr: 0.74, interval: 25, bassFields: 1, midFields: 2, trebleFields: 2, speed: 0.66, alpha: 0.48, bright: 0.74, coverage: 0.82, density: 0.22},
  high: {dpr: 0.86, interval: 17, bassFields: 2, midFields: 2, trebleFields: 2, speed: 0.82, alpha: 0.72, bright: 0.98, coverage: 1.05, density: 0.45}
};

function visualizerStrengthConfigFor(name){
  return VISUALIZER_STRENGTHS[normalizeVisualizerStrength(name)] || VISUALIZER_STRENGTHS.medium;
}

function mixVisualizerStrengthConfig(a, b, t){
  var p = Math.max(0, Math.min(1, Number(t || 0)));
  var out = {};
  Object.keys(b || {}).forEach((key)=>{
    const av = Number(a && a[key]);
    const bv = Number(b && b[key]);
    if(Number.isFinite(av) && Number.isFinite(bv)){
      out[key] = av + (bv - av) * p;
    }else{
      out[key] = b[key];
    }
  });
  out.bassFields = Math.max(1, Math.round(out.bassFields || b.bassFields || 1));
  out.midFields = Math.max(1, Math.round(out.midFields || b.midFields || 1));
  out.trebleFields = Math.max(1, Math.round(out.trebleFields || b.trebleFields || 1));
  return out;
}

function currentVisualizerStrengthConfig(ts){
  var target = visualizerStrengthConfigFor(visualizerStrength);
  try{
    const tr = visualizerStrengthTransition;
    if(!tr) return target;
    const now = Number(ts || performance.now() || 0);
    const p = Math.max(0, Math.min(1, (now - tr.start) / tr.duration));
    const eased = 1 - Math.pow(1 - p, 3);
    if(p >= 1){
      visualizerStrengthTransition = null;
      return target;
    }
    return mixVisualizerStrengthConfig(tr.from, tr.to, eased);
  }catch(e){
    visualizerStrengthTransition = null;
    return target;
  }
}

function currentVisualizerMediaElement(){
  try{
    if(isVideoActive && isVideoActive() && npVideo) return npVideo;
  }catch(e){}
  try{
    if(activeAudio && activeAudio.src) return activeAudio;
  }catch(e){}
  return null;
}

function ensureVisualizerAudioGraphFor(el){
  try{
    if(!el || !(window.AudioContext || window.webkitAudioContext)) return false;
    if(!visualizerAudioCtx){
      const Ctx = window.AudioContext || window.webkitAudioContext;
      visualizerAudioCtx = new Ctx();
    }
    if(!visualizerAnalyser){
      visualizerAnalyser = visualizerAudioCtx.createAnalyser();
      visualizerAnalyser.fftSize = 256;
      visualizerAnalyser.smoothingTimeConstant = 0.62;
      visualizerData = new Uint8Array(visualizerAnalyser.frequencyBinCount);
    }
    if(!visualizerSources.has(el)){
      const srcNode = visualizerAudioCtx.createMediaElementSource(el);
      srcNode.connect(visualizerAnalyser);
      visualizerAnalyser.connect(visualizerAudioCtx.destination);
      visualizerSources.set(el, srcNode);
    }
    if(visualizerAudioCtx.state === "suspended"){
      try{ visualizerAudioCtx.resume(); }catch(e){}
    }
    return true;
  }catch(e){
    return false;
  }
}

function clamp01(n){
  var v = Number(n || 0);
  return Math.max(0, Math.min(1, Number.isFinite(v) ? v : 0));
}

function currentVisualizerPreset(){
  return VISUALIZER_PRESETS[normalizeVisualizerPreset(visualizerPresetName)] || VISUALIZER_PRESETS.album;
}

function visualizerPresetLabel(name){
  var preset = VISUALIZER_PRESETS[normalizeVisualizerPreset(name)];
  return preset ? preset.label : "Orbit";
}

function foldedBpmFromInterval(ms){
  var bpm = 60000 / Math.max(1, Number(ms || 0));
  while(bpm < 72) bpm *= 2;
  while(bpm > 168) bpm /= 2;
  return Math.max(72, Math.min(168, bpm));
}

function updateVisualizerTempo(nowTs, bassLevel, energyLevel){
  try{
    const now = Number(nowTs || performance.now() || 0);
    const energy = clamp01((Number(bassLevel || 0) * 0.72) + (Number(energyLevel || 0) * 0.28));
    visualizerBeatEnergyAvg = visualizerBeatEnergyAvg ? (visualizerBeatEnergyAvg * 0.965 + energy * 0.035) : energy;
    visualizerBeatPulse *= 0.86;
    const threshold = Math.max(0.18, visualizerBeatEnergyAvg * 1.34 + 0.055);
    const since = visualizerBeatLastTs ? now - visualizerBeatLastTs : 9999;
    if(energy > threshold && since > 260){
      visualizerBeatPulse = Math.min(1, 0.58 + energy * 0.55);
      if(since < 1500){
        visualizerBeatIntervals.push(since);
        if(visualizerBeatIntervals.length > 10) visualizerBeatIntervals.shift();
        const bpms = visualizerBeatIntervals.map(foldedBpmFromInterval).filter(v=>Number.isFinite(v));
        if(bpms.length){
          bpms.sort((a,b)=>a-b);
          const median = bpms[Math.floor(bpms.length / 2)];
          visualizerBpm = visualizerBpm + (median - visualizerBpm) * 0.18;
        }
      }
      visualizerBeatLastTs = now;
    }else if(since > 2600 && visualizerBpm !== 120){
      visualizerBpm = visualizerBpm + (120 - visualizerBpm) * 0.01;
    }
  }catch(e){}
}

function visualizerMotionTime(ts){
  var preset = currentVisualizerPreset();
  var bpmRate = Math.max(0.55, Math.min(1.65, Number(visualizerBpm || 120) / 120));
  return Number(ts || 0) * 0.001 * bpmRate * (Number(preset.motion || 1));
}

function resetVisualizerTempo(){
  visualizerBpm = 120;
  visualizerBeatPulse = 0;
  visualizerBeatLastTs = 0;
  visualizerBeatEnergyAvg = 0;
  visualizerBeatIntervals = [];
  visualizerBands = [0, 0, 0, 0, 0, 0, 0];
}

function resetVisualizerAnalysis(reason){
  visualizerAnalysisNonce += 1;
  try{ if(visualizerAnalysisRetryTimer) clearTimeout(visualizerAnalysisRetryTimer); }catch(e){}
  visualizerAnalysisRetryTimer = 0;
  visualizerVideoPaletteFrame = -1;
  visualizerVideoPaletteKey = "";
  visualizerAnalysisState = {
    key: "",
    loaded: false,
    loading: false,
    stale: false,
    rate: 30,
    stride: 9,
    bandCount: 7,
    frameCount: 0,
    bytes: null,
    rootId: "",
    rel: "",
    source: String(reason || ""),
    mediaKind: "",
    videoPaletteFrames: null,
    videoPalettePending: false
  };
}

function currentVisualizerMediaKind(){
  try{
    return state && state.now && state.now.media ? String(state.now.media || "").toLowerCase() : "";
  }catch(e){
    return "";
  }
}

function scheduleVisualizerAnalysisRetry(rootId, rel, mediaKind, attempt){
  try{
    if(String(mediaKind || "").toLowerCase() !== "video") return;
    if(visualizerAnalysisRetryTimer) return;
    const nextAttempt = Math.max(1, Number(attempt || 0) + 1);
    if(nextAttempt > 12) return;
    visualizerAnalysisRetryTimer = setTimeout(()=>{
      visualizerAnalysisRetryTimer = 0;
      loadVisualizerAnalysisForTrack(rootId, rel, mediaKind, {retryAttempt: nextAttempt});
    }, Math.min(15000, 1800 + nextAttempt * 900));
  }catch(e){}
}

function bytesFromBase64(value){
  try{
    const text = String(value || "");
    if(!text) return null;
    const raw = atob(text);
    const out = new Uint8Array(raw.length);
    for(let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i) & 255;
    return out;
  }catch(e){
    return null;
  }
}

function applyVisualizerAnalysis(rootId, rel, analysis, nonce){
  try{
    if(nonce !== visualizerAnalysisNonce) return;
    if(!analysis || typeof analysis !== "object"){
      visualizerAnalysisState.loading = false;
      visualizerAnalysisState.loaded = false;
      visualizerAnalysisState.stale = true;
      return;
    }
    const bytes = bytesFromBase64(analysis.feature_blob_b64 || "");
    const metadata = analysis.metadata && typeof analysis.metadata === "object" ? analysis.metadata : {};
    const bandCount = Math.max(1, Math.min(7, Number(analysis.band_count || 7)));
    const stride = Math.max(bandCount + 2, Number(metadata.frame_stride || (bandCount + 2)));
    const frameCount = Math.max(0, Number(analysis.frame_count || Math.floor((bytes ? bytes.length : 0) / stride)));
    if(!bytes || !frameCount || bytes.length < stride){
      visualizerAnalysisState.loading = false;
      visualizerAnalysisState.loaded = false;
      visualizerAnalysisState.stale = true;
      return;
    }
    visualizerAnalysisState = {
      key: String(analysis.analysis_key || (rootId + ":" + rel)),
      loaded: true,
      loading: false,
      stale: false,
      rate: Math.max(1, Number(analysis.analysis_rate_hz || 30)),
      stride: stride,
      bandCount: bandCount,
      frameCount: Math.min(frameCount, Math.floor(bytes.length / stride)),
      bytes: bytes,
      rootId: String(rootId || ""),
      rel: String(rel || ""),
      source: "sqlite",
      mediaKind: String(metadata.media_kind || ""),
      videoPaletteFrames: Array.isArray(metadata.video_palette_frames) ? metadata.video_palette_frames : null,
      videoPalettePending: !!metadata.video_palette_pending
    };
    try{ if(visualizerAnalysisRetryTimer) clearTimeout(visualizerAnalysisRetryTimer); }catch(e){}
    visualizerAnalysisRetryTimer = 0;
    visualizerVideoPaletteFrame = -1;
    visualizerVideoPaletteKey = "";
    resetVisualizerTempo();
    scheduleVisualizerFrame(0);
    if(visualizerAnalysisState.mediaKind === "video" && visualizerAnalysisState.videoPalettePending){
      scheduleVisualizerAnalysisRetry(rootId, rel, "video", 0);
    }
  }catch(e){
    visualizerAnalysisState.loading = false;
    visualizerAnalysisState.loaded = false;
  }
}

function loadVisualizerAnalysisForTrack(rootId, rel, mediaKind, options){
  try{
    const opts = options || {};
    try{ if(visualizerAnalysisRetryTimer && !opts.retryAttempt) clearTimeout(visualizerAnalysisRetryTimer); }catch(e){}
    if(!opts.retryAttempt) visualizerAnalysisRetryTimer = 0;
    const media = String(mediaKind || "audio").toLowerCase();
    const rid = String(rootId || "");
    const rp = String(rel || "");
    if(opts.streamed || !rid || !rp || typeof apiGet !== "function"){
      resetVisualizerAnalysis(opts.streamed ? "streamed idle" : "uncached idle");
      visualizerAnalysisState.mediaKind = media;
      return;
    }
    const key = rid + "\n" + rp;
    if(visualizerAnalysisState.key === key && (visualizerAnalysisState.loaded || visualizerAnalysisState.loading) && !(opts.retryAttempt && visualizerAnalysisState.videoPalettePending)) return;
    const nonce = ++visualizerAnalysisNonce;
    visualizerAnalysisState = Object.assign({}, visualizerAnalysisState, {
      key: key,
      rootId: rid,
      rel: rp,
      loaded: false,
      loading: true,
      stale: false,
      source: "loading"
    });
    apiGet("/api/library/analysis?root_id=" + encodeURIComponent(rid) + "&rel=" + encodeURIComponent(rp), {networkOnly:true, cache:"no-store", abortKey:"visualizer-analysis"})
      .then((res)=>{
        try{
          if(nonce !== visualizerAnalysisNonce) return;
          if(!res || !res.analysis){
            visualizerAnalysisState.loading = false;
            visualizerAnalysisState.loaded = false;
            visualizerAnalysisState.stale = true;
            visualizerAnalysisState.source = media === "video" ? "idle" : "live";
            visualizerAnalysisState.mediaKind = media;
            scheduleVisualizerAnalysisRetry(rid, rp, media, opts.retryAttempt || 0);
            return;
          }
          applyVisualizerAnalysis(rid, rp, res.analysis, nonce);
        }catch(e){}
      })
      .catch(()=>{
        if(nonce !== visualizerAnalysisNonce) return;
        visualizerAnalysisState.loading = false;
        visualizerAnalysisState.loaded = false;
        visualizerAnalysisState.stale = true;
        visualizerAnalysisState.source = media === "video" ? "idle" : "live";
        visualizerAnalysisState.mediaKind = media;
        scheduleVisualizerAnalysisRetry(rid, rp, media, opts.retryAttempt || 0);
      });
  }catch(e){
    resetVisualizerAnalysis("analysis error");
  }
}

function applyCachedVideoPaletteForFrame(analysis, frameIndex){
  try{
    const frames = analysis && Array.isArray(analysis.videoPaletteFrames) ? analysis.videoPaletteFrames : null;
    if(!frames || !frames.length) return;
    const idx = Math.max(0, Math.floor(Number(frameIndex || 0)));
    const key = String(analysis.key || "") + ":" + idx;
    if(key === visualizerVideoPaletteKey) return;
    let lo = 0;
    let hi = frames.length - 1;
    let best = frames[0];
    while(lo <= hi){
      const mid = (lo + hi) >> 1;
      const row = frames[mid] || [];
      const fi = Number(row[0] || 0);
      if(fi <= idx){
        best = row;
        lo = mid + 1;
      }else{
        hi = mid - 1;
      }
    }
    const bestFrame = Number(best && best[0]);
    if(bestFrame === visualizerVideoPaletteFrame) return;
    const hexColors = best && Array.isArray(best[1]) ? best[1] : [];
    const colors = hexColors.map(c=>rgbFromHex(c, null)).filter(Boolean);
    if(!colors.length) return;
    visualizerVideoPaletteFrame = bestFrame;
    visualizerVideoPaletteKey = key;
    setVisualizerPalette(colors);
    visualizerPalette = visualizerTargetPalette.map(c=>({r:c.r, g:c.g, b:c.b}));
  }catch(e){}
}

function sampleCachedVisualizerAnalysis(el){
  try{
    const analysis = visualizerAnalysisState;
    if(!analysis || !analysis.loaded || !analysis.bytes || !analysis.frameCount || !el) return null;
    const rate = Math.max(1, Number(analysis.rate || 30));
    const stride = Math.max(1, Number(analysis.stride || 9));
    const count = Math.max(1, Number(analysis.frameCount || 0));
    const time = Math.max(0, Number(el.currentTime || 0));
    const pos = Math.max(0, Math.min(count - 1, time * rate));
    const i0 = Math.floor(pos);
    const i1 = Math.min(count - 1, i0 + 1);
    const frac = pos - i0;
    const off0 = i0 * stride;
    const off1 = i1 * stride;
    const bytes = analysis.bytes;
    const bands = [];
    for(let i = 0; i < 7; i++){
      const a = Number(bytes[off0 + i] || 0) / 255;
      const b = Number(bytes[off1 + i] || 0) / 255;
      bands.push(a + (b - a) * frac);
    }
    const energyIdx = Math.min(stride - 2, 7);
    const beatIdx = Math.min(stride - 1, 8);
    const e0 = Number(bytes[off0 + energyIdx] || 0) / 255;
    const e1 = Number(bytes[off1 + energyIdx] || 0) / 255;
    const p0 = Number(bytes[off0 + beatIdx] || 0) / 255;
    const p1 = Number(bytes[off1 + beatIdx] || 0) / 255;
    const energy = e0 + (e1 - e0) * frac;
    const beat = p0 + (p1 - p0) * frac;
    if(String(analysis.mediaKind || "").toLowerCase() === "video"){
      applyCachedVideoPaletteForFrame(analysis, i0);
    }
    return {
      bands: bands,
      bass: clamp01((bands[0] + bands[1]) * 0.5),
      mid: clamp01((bands[2] + bands[3] + bands[4]) / 3),
      treble: clamp01((bands[5] + bands[6]) * 0.5),
      energy: clamp01(energy),
      beat: clamp01(beat)
    };
  }catch(e){
    return null;
  }
}

function rgbForPaletteIndex(i){
  var palette = visualizerPalette && visualizerPalette.length ? visualizerPalette : defaultVisualizerPalette;
  return palette[i % palette.length] || defaultVisualizerPalette[i % defaultVisualizerPalette.length];
}

function compileVisualizerShader(gl, type, source){
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if(!gl.getShaderParameter(shader, gl.COMPILE_STATUS)){
    try{ console.warn("[DebriPod visualizer] shader compile failed", gl.getShaderInfoLog(shader) || ""); }catch(e){}
    try{ gl.deleteShader(shader); }catch(e){}
    return null;
  }
  return shader;
}

function linkVisualizerProgram(gl, vsSource, fsSource){
  const vs = compileVisualizerShader(gl, gl.VERTEX_SHADER, vsSource);
  const fs = compileVisualizerShader(gl, gl.FRAGMENT_SHADER, fsSource);
  if(!vs || !fs) return null;
  const program = gl.createProgram();
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  if(!gl.getProgramParameter(program, gl.LINK_STATUS)){
    try{ console.warn("[DebriPod visualizer] shader link failed", gl.getProgramInfoLog(program) || ""); }catch(e){}
    try{ gl.deleteProgram(program); }catch(e){}
    return null;
  }
  return program;
}

function cacheVisualizerUniforms(gl, program, copyProgram){
  visualizerUniforms = {
    canvasSize: gl.getUniformLocation(program, "canvasSize"),
    time: gl.getUniformLocation(program, "time"),
    playbackTime: gl.getUniformLocation(program, "playbackTime"),
    presetIndex: gl.getUniformLocation(program, "presetIndex"),
    energy: gl.getUniformLocation(program, "energy"),
    bass: gl.getUniformLocation(program, "bass"),
    mid: gl.getUniformLocation(program, "mid"),
    treble: gl.getUniformLocation(program, "treble"),
    beat: gl.getUniformLocation(program, "beat"),
    activeAmount: gl.getUniformLocation(program, "activeAmount"),
    idleAmount: gl.getUniformLocation(program, "idleAmount"),
    alphaScale: gl.getUniformLocation(program, "alphaScale"),
    brightScale: gl.getUniformLocation(program, "brightScale"),
    coverage: gl.getUniformLocation(program, "coverage"),
    densityScale: gl.getUniformLocation(program, "densityScale"),
    anchor: gl.getUniformLocation(program, "anchor"),
    bands: gl.getUniformLocation(program, "bands[0]"),
    palette: gl.getUniformLocation(program, "palette[0]"),
    paletteCount: gl.getUniformLocation(program, "paletteCount"),
    copyTex: gl.getUniformLocation(copyProgram, "tex")
  };
}

function ensureVisualizerWebGL(){
  if(visualizerWebglUnavailable) return false;
  try{
    if(!visualizerBg || !visualizerBg.getContext) return false;
    if(visualizerGl && visualizerProgram && visualizerCopyProgram && visualizerTexture && visualizerFramebuffer) return true;
    const attrs = {alpha:true, premultipliedAlpha:true, preserveDrawingBuffer:true, antialias:false, depth:false, stencil:false};
    visualizerGl = visualizerBg.getContext("webgl", attrs) || visualizerBg.getContext("experimental-webgl", attrs);
    if(!visualizerGl){
      visualizerWebglUnavailable = true;
      return false;
    }
    const vsSource = "attribute vec2 p; varying vec2 uv; void main(){ uv=(p+1.0)*0.5; gl_Position=vec4(p,0.0,1.0); }";
    let fsSource = [
      "precision mediump float;",
      "varying vec2 uv;",
      "uniform vec2 canvasSize;",
      "uniform float time;",
      "uniform float playbackTime;",
      "uniform float presetIndex;",
      "uniform float energy;",
      "uniform float bass;",
      "uniform float mid;",
      "uniform float treble;",
      "uniform float beat;",
      "uniform float activeAmount;",
      "uniform float idleAmount;",
      "uniform float alphaScale;",
      "uniform float brightScale;",
      "uniform float coverage;",
      "uniform float densityScale;",
      "uniform vec4 anchor;",
      "uniform float bands[7];",
      "uniform vec3 palette[16];",
      "uniform float paletteCount;",
      "vec3 pal(float i){",
      "  float n = max(1.0, paletteCount);",
      "  float x = mod(i, n);",
      "  if(x < 0.5) return palette[0];",
      "  if(x < 1.5) return palette[1];",
      "  if(x < 2.5) return palette[2];",
      "  if(x < 3.5) return palette[3];",
      "  if(x < 4.5) return palette[4];",
      "  if(x < 5.5) return palette[5];",
      "  if(x < 6.5) return palette[6];",
      "  if(x < 7.5) return palette[7];",
      "  if(x < 8.5) return palette[8];",
      "  if(x < 9.5) return palette[9];",
      "  if(x < 10.5) return palette[10];",
      "  if(x < 11.5) return palette[11];",
      "  if(x < 12.5) return palette[12];",
      "  if(x < 13.5) return palette[13];",
      "  if(x < 14.5) return palette[14];",
      "  return palette[15];",
      "}",
      "float band(float i){",
      "  if(i < 0.5) return bands[0];",
      "  if(i < 1.5) return bands[1];",
      "  if(i < 2.5) return bands[2];",
      "  if(i < 3.5) return bands[3];",
      "  if(i < 4.5) return bands[4];",
      "  if(i < 5.5) return bands[5];",
      "  return bands[6];",
      "}",
      "float field(vec2 p, vec2 c, float r){",
      "  vec2 d = p - c;",
      "  float rr = max(0.0008, r * r);",
      "  return exp(-dot(d,d) / rr);",
      "}",
      "vec2 blobMotion(float idx, float level, float t, float style){",
      "  float a = idx * 2.399963 + t * (0.22 + idx * 0.011 + treble * 0.12);",
      "  float r = 0.34 + fract(idx * 0.381) * 0.78 + bass * 0.08 + beat * 0.10;",
      "  vec2 o = vec2(cos(a), sin(a)) * r;",
      "  if(style > 0.5 && style < 1.5){",
      "    float curtain = sin(t * (0.16 + mid * 0.16) + idx * 0.83);",
      "    o = vec2(sin(idx * 1.27 + t * (0.10 + treble * 0.10)) * (0.92 + level * 0.28), curtain * (0.38 + mid * 0.22) + (fract(idx * 0.17) - 0.5) * 0.56);",
      "  }else if(style > 1.5 && style < 2.5){",
      "    float rise = fract(idx * 0.137 + t * (0.055 + mid * 0.035));",
      "    o = vec2(sin(idx * 1.91 + t * 0.20) * (0.24 + treble * 0.22), -0.90 + rise * 1.92 + bass * 0.16);",
      "  }else if(style > 2.5 && style < 3.5){",
      "    float drift = t * (0.19 + treble * 0.18);",
      "    o = vec2(sin(idx * 1.11 + drift) * (0.58 + level * 0.44), cos(idx * 1.47 - drift * 0.73) * (0.42 + mid * 0.24));",
      "  }else if(style > 3.5 && style < 4.5){",
      "    float pulse = sin(t * (0.42 + bass * 0.30) - idx * 0.31) * 0.5 + 0.5;",
      "    o = vec2(cos(a + pulse * 0.9), sin(a * 0.74 - pulse)) * (0.18 + pulse * 0.92 + beat * 0.18);",
      "  }else if(style > 4.5 && style < 5.5){",
      "    float fall = fract(idx * 0.119 + t * (0.065 + mid * 0.055));",
      "    o = vec2((fract(idx * 0.271) - 0.5) * 1.85 + sin(t * 0.13 + idx) * 0.16, 1.05 - fall * 2.10 + treble * 0.08);",
      "  }else if(style > 5.5 && style < 6.5){",
      "    float bloom = 0.22 + energy * 0.52 + beat * 0.48;",
      "    o = vec2(cos(a * 1.13 + sin(t * 0.21 + idx)), sin(a * 0.91)) * (bloom + fract(idx * 0.23) * 0.62);",
      "  }else if(style > 6.5){",
      "    float weave = sin(t * 0.18 + idx * 0.77);",
      "    o = vec2(sin(idx * 0.97 + weave) * (0.74 + mid * 0.22), cos(idx * 1.33 - weave) * (0.54 + treble * 0.18));",
      "  }",
      "  return o;",
      "}",
      "void main(){",
      "  vec2 p = uv;",
      "  p.y = 1.0 - p.y;",
      "  vec2 aspect = vec2(canvasSize.x / max(1.0, canvasSize.y), 1.0);",
      "  vec2 center = anchor.xy;",
      "  vec2 scale = max(anchor.zw, vec2(0.24));",
      "  float style = presetIndex;",
      "  float t = time + playbackTime * 0.08;",
      "  vec3 color = vec3(0.0);",
      "  for(int i=0; i<40; i++){",
      "    float fi = float(i);",
      "    float bi = mod(fi, 7.0);",
      "    float level = band(bi);",
      "    float layer = step(20.0, fi);",
      "    float extra = mix(1.0, densityScale, layer);",
      "    vec2 o = blobMotion(fi, level, t, style);",
      "    vec2 c = center + vec2(o.x * scale.x / aspect.x, o.y * scale.y);",
      "    float lowTone = 1.0 - clamp(bi / 6.0, 0.0, 1.0);",
      "    float highTone = clamp(bi / 6.0, 0.0, 1.0);",
      "    float radius = (0.09 + lowTone * 0.15 + highTone * 0.055 + level * 0.10 + beat * 0.055) * coverage * mix(1.05, 0.55, layer);",
      "    float f = field(p * aspect, c * aspect, radius);",
      "    float shimmer = 0.82 + highTone * treble * 0.42 + lowTone * bass * 0.24;",
      "    float a = (0.022 + level * 0.105 + energy * 0.035 + beat * (0.018 + lowTone * 0.035)) * alphaScale * extra;",
      "    float br = (0.50 + highTone * 0.38 + level * 0.18) * brightScale * shimmer;",
      "    float colorWalk = fi + bi * 2.0 + t * (0.42 + treble * 0.70) + style * 1.7;",
      "    color += pal(colorWalk) * br * f * a;",
      "  }",
      "  vec2 dirA = vec2(cos(style * 0.79 + 0.4), sin(style * 0.61 + 1.1));",
      "  vec2 dirB = vec2(cos(style * 1.13 + 2.2), sin(style * 0.97 + 0.2));",
      "  float softA = 0.5 + 0.5 * sin(dot((p - center) * aspect, dirA) * (2.1 + style * 0.18) + t * (0.34 + bass * 0.30));",
      "  float softB = 0.5 + 0.5 * sin(dot((p - center) * aspect, dirB) * (3.0 + style * 0.14) - t * (0.28 + treble * 0.36));",
      "  float reach = smoothstep(1.28, 0.05, length(vec2((p.x - center.x) * aspect.x / max(scale.x, 0.001), (p.y - center.y) / max(scale.y, 0.001))));",
      "  vec3 sweepA = mix(pal(style * 2.0 + t * 0.32), pal(style * 2.0 + 8.0 + t * 0.27), softA);",
      "  vec3 sweepB = mix(pal(style * 3.0 + 4.0 - t * 0.19), pal(style * 3.0 + 12.0 + t * 0.23), softB);",
      "  color += mix(sweepA, sweepB, 0.45 + 0.35 * mid) * reach * alphaScale * brightScale * (0.012 + energy * 0.018 + beat * 0.010);",
      "  float v = smoothstep(0.92, 0.18, distance(p, vec2(0.5)));",
      "  vec3 outColor = color * mix(0.38, 0.90, v);",
      "  outColor = mix(vec3(0.0), outColor, max(activeAmount, idleAmount));",
      "  gl_FragColor = vec4(outColor, 1.0);",
      "}"
    ].join("\n");
    const copyFs = [
      "precision mediump float;",
      "varying vec2 uv;",
      "uniform sampler2D tex;",
      "void main(){ gl_FragColor = texture2D(tex, uv); }"
    ].join("\n");
    visualizerProgram = linkVisualizerProgram(visualizerGl, vsSource, fsSource);
    visualizerCopyProgram = linkVisualizerProgram(visualizerGl, vsSource, copyFs);
    if(!visualizerProgram || !visualizerCopyProgram){
      visualizerWebglUnavailable = true;
      return false;
    }
    cacheVisualizerUniforms(visualizerGl, visualizerProgram, visualizerCopyProgram);
    visualizerBuffer = visualizerGl.createBuffer();
    visualizerGl.bindBuffer(visualizerGl.ARRAY_BUFFER, visualizerBuffer);
    visualizerGl.bufferData(visualizerGl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, -1,1, 1,-1, 1,1]), visualizerGl.STATIC_DRAW);
    visualizerTexture = visualizerGl.createTexture();
    visualizerFramebuffer = visualizerGl.createFramebuffer();
    visualizerGl.disable(visualizerGl.DEPTH_TEST);
    visualizerGl.disable(visualizerGl.STENCIL_TEST);
    return !!(visualizerBuffer && visualizerTexture && visualizerFramebuffer);
  }catch(e){
    visualizerWebglUnavailable = true;
    return false;
  }
}

function resizeVisualizerSurface(cfg){
  try{
    if(!ensureVisualizerWebGL()) return false;
    const dpr = Math.max(0.45, Math.min(Number(cfg && cfg.dpr) || 1, window.devicePixelRatio || 1));
    const w = Math.max(1, Math.round(window.innerWidth * dpr));
    const h = Math.max(1, Math.round(window.innerHeight * dpr));
    if(w === visualizerCanvasW && h === visualizerCanvasH && dpr === visualizerCanvasDpr) return true;
    visualizerBg.width = w;
    visualizerBg.height = h;
    visualizerCanvasW = w;
    visualizerCanvasH = h;
    visualizerCanvasDpr = dpr;
    const gl = visualizerGl;
    gl.bindTexture(gl.TEXTURE_2D, visualizerTexture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    gl.bindFramebuffer(gl.FRAMEBUFFER, visualizerFramebuffer);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, visualizerTexture, 0);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    return true;
  }catch(e){
    return false;
  }
}

function visualizerPresetIndex(){
  try{
    const order = Object.keys(VISUALIZER_PRESETS || {});
    const idx = order.indexOf(normalizeVisualizerPreset(visualizerPresetName));
    return idx >= 0 ? idx : 0;
  }catch(e){
    return 0;
  }
}

function currentVisualizerPlaybackTime(){
  try{
    const el = currentVisualizerMediaElement();
    return el && Number.isFinite(Number(el.currentTime)) ? Number(el.currentTime) : 0;
  }catch(e){
    return 0;
  }
}

function visualizerAnchorForSurface(){
  const vw = Math.max(1, window.innerWidth || 1);
  const vh = Math.max(1, window.innerHeight || 1);
  const portrait = vh > vw;
  return portrait
    ? {cx:0.5, cy:0.43, rx:0.58, ry:0.48}
    : {cx:0.5, cy:0.50, rx:0.46, ry:0.62};
}

function setVisualizerAttribute(program){
  const gl = visualizerGl;
  const loc = gl.getAttribLocation(program, "p");
  gl.bindBuffer(gl.ARRAY_BUFFER, visualizerBuffer);
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
}

function setPaletteUniforms(program){
  try{
    const gl = visualizerGl;
    const count = Math.max(1, Math.min(MAX_VISUALIZER_PALETTE_COLORS, visualizerPalette.length || 0));
    for(let i = 0; i < MAX_VISUALIZER_PALETTE_COLORS; i++){
      const rgb = visualizerPalette[i % visualizerPalette.length] || defaultVisualizerPalette[i % defaultVisualizerPalette.length];
      const off = i * 3;
      visualizerPaletteUniformData[off] = clampByte(rgb.r) / 255;
      visualizerPaletteUniformData[off + 1] = clampByte(rgb.g) / 255;
      visualizerPaletteUniformData[off + 2] = clampByte(rgb.b) / 255;
    }
    if(visualizerUniforms && visualizerUniforms.palette) gl.uniform3fv(visualizerUniforms.palette, visualizerPaletteUniformData);
    if(visualizerUniforms && visualizerUniforms.paletteCount) gl.uniform1f(visualizerUniforms.paletteCount, count);
  }catch(e){}
}

function blendVisualizerPalette(){
  try{
    const target = visualizerTargetPalette && visualizerTargetPalette.length ? visualizerTargetPalette : defaultVisualizerPalette;
    const maxLen = Math.max(8, target.length);
    while(visualizerPalette.length < maxLen) visualizerPalette.push(target[visualizerPalette.length % target.length]);
    for(let i = 0; i < maxLen; i++){
      const cur = visualizerPalette[i] || target[i % target.length];
      const nxt = target[i % target.length] || cur;
      visualizerPalette[i] = {
        r: cur.r + (nxt.r - cur.r) * 0.08,
        g: cur.g + (nxt.g - cur.g) * 0.08,
        b: cur.b + (nxt.b - cur.b) * 0.08
      };
    }
    visualizerPalette.length = maxLen;
  }catch(e){}
}

function renderVisualizerWebGL(ts){
  try{
    if(!visualizerBg) return false;
    const cfg = currentVisualizerStrengthConfig(ts);
    if(!resizeVisualizerSurface(cfg)) return false;
    const gl = visualizerGl;
    const nowTs = Number(ts || performance.now() || 0);
    const drawActive = visualizerActive || visualizerResidualVisible(nowTs);
    const activeAmount = drawActive ? 1 : 0;
    const idleAmount = visualizerEnabled && !drawActive ? 1 : 0;
    const anchor = visualizerAnchorForSurface();
    blendVisualizerPalette();

    gl.bindFramebuffer(gl.FRAMEBUFFER, visualizerFramebuffer);
    gl.viewport(0, 0, visualizerCanvasW, visualizerCanvasH);
    gl.clearColor(0, 0, 0, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(visualizerProgram);
    setVisualizerAttribute(visualizerProgram);
    setPaletteUniforms(visualizerProgram);
    const u = visualizerUniforms || {};
    gl.uniform2f(u.canvasSize, visualizerCanvasW, visualizerCanvasH);
    gl.uniform1f(u.time, visualizerMotionTime(nowTs) * Number(cfg.speed || 1));
    gl.uniform1f(u.playbackTime, currentVisualizerPlaybackTime());
    gl.uniform1f(u.presetIndex, visualizerPresetIndex());
    gl.uniform1f(u.energy, activeAmount ? clamp01(visualizerEnergy) : 0);
    gl.uniform1f(u.bass, activeAmount ? clamp01(visualizerBass) : 0);
    gl.uniform1f(u.mid, activeAmount ? clamp01(visualizerMid) : 0);
    gl.uniform1f(u.treble, activeAmount ? clamp01(visualizerTreble) : 0);
    gl.uniform1f(u.beat, activeAmount ? clamp01(visualizerBeatPulse) : 0);
    gl.uniform1f(u.activeAmount, activeAmount);
    gl.uniform1f(u.idleAmount, idleAmount);
    gl.uniform1f(u.alphaScale, Number(cfg.alpha || 0.68));
    gl.uniform1f(u.brightScale, Number(cfg.bright || 1));
    gl.uniform1f(u.coverage, Number(cfg.coverage || 1));
    gl.uniform1f(u.densityScale, Number(cfg.density || 0));
    gl.uniform4f(u.anchor, anchor.cx, anchor.cy, anchor.rx, anchor.ry);
    for(let i = 0; i < 7; i++) visualizerBandUniformData[i] = activeAmount ? clamp01((visualizerBands || [])[i] || 0) : 0;
    gl.uniform1fv(u.bands, visualizerBandUniformData);
    gl.drawArrays(gl.TRIANGLES, 0, 6);

    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, visualizerCanvasW, visualizerCanvasH);
    gl.clearColor(0, 0, 0, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(visualizerCopyProgram);
    setVisualizerAttribute(visualizerCopyProgram);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, visualizerTexture);
    gl.uniform1i((visualizerUniforms || {}).copyTex, 0);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
    return true;
  }catch(e){
    return false;
  }
}

function visualizerSourceForLiquidGL(){
  return {
    canvas: visualizerBg,
    gl: visualizerGl,
    texture: visualizerTexture,
    width: visualizerCanvasW,
    height: visualizerCanvasH,
    sourceRect: {left:0, top:0, width: window.innerWidth || 1, height: window.innerHeight || 1},
    ready: !!(visualizerGl && visualizerTexture && visualizerCanvasW && visualizerCanvasH)
  };
}

try{
  const rootForVisualizer = window.DebriPod = window.DebriPod || {};
  rootForVisualizer.visualizerRenderer = Object.assign(rootForVisualizer.visualizerRenderer || {}, {
    sourceForLiquidGL: visualizerSourceForLiquidGL,
    render: renderVisualizerWebGL,
    available: function(){ return !!(visualizerGl && !visualizerWebglUnavailable); }
  });
}catch(e){}

function currentVisualizerFrameState(ts){
  return {
    timestamp: Number(ts || performance.now() || 0),
    active: !!visualizerActive,
    strength: visualizerStrength,
    energy: visualizerEnergy,
    bass: visualizerBass,
    mid: visualizerMid,
    treble: visualizerTreble,
    bands: visualizerBands,
    bandLabels: VISUALIZER_BAND_LABELS,
    bpm: visualizerBpm,
    palette: visualizerPalette,
    paletteRoles: currentVisualizerPalette,
    roleWeights: roleWeightsForSelectedText(),
    selectedTextContrastMix: selectedTextContrastMix,
    analysisSource: visualizerAnalysisState && visualizerAnalysisState.loaded ? "sqlite" : (visualizerAnalysisState && visualizerAnalysisState.source ? visualizerAnalysisState.source : "live"),
    videoPaletteFrames: visualizerAnalysisState && visualizerAnalysisState.videoPaletteFrames ? visualizerAnalysisState.videoPaletteFrames : null
  };
}

function scheduleVisualizerFrame(delayMs){
  try{
    if(visualizerFrameHandle || visualizerFrameTimer) return;
    const delay = Math.max(0, Number(delayMs || 0));
    const queueFrame = ()=>{
      const scheduler = window.DebriPod && DebriPod.frameScheduler ? DebriPod.frameScheduler : null;
      if(scheduler && scheduler.request){
        visualizerFrameHandle = -1;
        scheduler.request("visualizer-frame", (frameState)=> visualizerFrame(frameState && frameState.timestamp ? frameState.timestamp : performance.now()));
        scheduler.mark({keepAlive:true});
      }else{
        visualizerFrameHandle = requestAnimationFrame(visualizerFrame);
      }
    };
    if(delay > 34){
      visualizerFrameTimer = setTimeout(()=>{
        visualizerFrameTimer = 0;
        queueFrame();
      }, delay);
      return;
    }
    queueFrame();
  }catch(e){}
}

function visualizerFrame(ts){
  visualizerFrameHandle = 0;
  try{
    const nowTs = Number(ts || performance.now() || 0);
    const cfg = currentVisualizerStrengthConfig(ts);
    const residual = visualizerResidualVisible(nowTs);
    const pathNeedsFrame = visualizerEnabled && (visualizerActive || residual) && isPathPillVisible();
    const hasResidualEnergy = visualizerEnabled && (visualizerEnergy > 0.003 || visualizerBass > 0.003 || visualizerMid > 0.003 || visualizerTreble > 0.003);
    const glassNeedsFrame = visualizerEnabled || visualizerActive || residual || hasResidualEnergy || pathNeedsFrame;
    const fpsInterval = 1000 / normalizeVisualizerFpsLock(visualizerFpsLock);
    const interval = glassNeedsFrame ? Math.max(cfg.interval, fpsInterval) : 180;
    if(visualizerLastFrameTs && (nowTs - visualizerLastFrameTs) < interval){
      scheduleVisualizerFrame(interval - (nowTs - visualizerLastFrameTs));
      return;
    }
    visualizerLastFrameTs = nowTs;
    const el = currentVisualizerMediaElement();
    const cachedFeatures = visualizerEnabled && visualizerActive && !document.hidden ? sampleCachedVisualizerAnalysis(el) : null;
    const mediaKind = currentVisualizerMediaKind();
    const canAnalyze = !!(mediaKind !== "video" && !cachedFeatures && visualizerEnabled && visualizerActive && !document.hidden && el && ensureVisualizerAudioGraphFor(el) && visualizerAnalyser && visualizerData);
    let nextBass = 0;
    let nextMid = 0;
    let nextTreble = 0;
    let nextEnergy = 0;
    let nextBands = [0, 0, 0, 0, 0, 0, 0];
    if(cachedFeatures){
      nextBass = cachedFeatures.bass;
      nextMid = cachedFeatures.mid;
      nextTreble = cachedFeatures.treble;
      nextEnergy = cachedFeatures.energy;
      nextBands = cachedFeatures.bands;
    }else if(canAnalyze){
      try{ visualizerAnalyser.getByteFrequencyData(visualizerData); }catch(e){}
      const n = visualizerData.length || 0;
      if(n > 0){
        const bassEnd = Math.max(1, Math.floor(n * 0.16));
        const midEnd = Math.max(bassEnd + 1, Math.floor(n * 0.50));
        let bassSum = 0, midSum = 0, trebleSum = 0, allSum = 0;
        const bandCuts = [0, 0.055, 0.12, 0.24, 0.42, 0.60, 0.78, 1.0].map(x=>Math.max(0, Math.min(n, Math.round(n * x))));
        const bandSums = [0, 0, 0, 0, 0, 0, 0];
        const bandCounts = [0, 0, 0, 0, 0, 0, 0];
        for(let i = 0; i < n; i++){
          const v = Number(visualizerData[i] || 0) / 255;
          allSum += v;
          if(i < bassEnd) bassSum += v;
          else if(i < midEnd) midSum += v;
          else trebleSum += v;
          for(let bi = 0; bi < 7; bi++){
            if(i >= bandCuts[bi] && i < Math.max(bandCuts[bi] + 1, bandCuts[bi + 1])){
              bandSums[bi] += v;
              bandCounts[bi] += 1;
              break;
            }
          }
        }
        nextBass = bassSum / Math.max(1, bassEnd);
        nextMid = midSum / Math.max(1, midEnd - bassEnd);
        nextTreble = trebleSum / Math.max(1, n - midEnd);
        nextEnergy = allSum / n;
        const bassPeak = Math.min(1, Math.max(0, (nextBass - 0.08) * 1.90));
        const midPeak = Math.min(1, Math.max(0, (nextMid - 0.06) * 1.62));
        const treblePeak = Math.min(1, Math.max(0, (nextTreble - 0.05) * 1.72));
        const energyPeak = Math.min(1, Math.max(0, (nextEnergy - 0.05) * 1.85));
        nextBass = Math.min(1, (nextBass * 0.55) + (bassPeak * 0.95));
        nextMid = Math.min(1, (nextMid * 0.62) + (midPeak * 0.88));
        nextTreble = Math.min(1, (nextTreble * 0.58) + (treblePeak * 0.92));
        nextEnergy = Math.min(1, (nextEnergy * 0.45) + (energyPeak * 1.05) + (bassPeak * 0.12));
        nextBands = bandSums.map((sum, idx)=>{
          const raw = sum / Math.max(1, bandCounts[idx]);
          const lift = idx < 2 ? 1.95 : (idx < 5 ? 1.72 : 1.88);
          const floor = idx < 2 ? 0.07 : (idx < 5 ? 0.055 : 0.045);
          return Math.min(1, raw * 0.58 + Math.max(0, raw - floor) * lift);
        });
      }
    }else if(visualizerEnabled && !document.hidden){
      const idle = nowTs * 0.001;
      nextBass = 0.10 + Math.sin(idle * 0.71) * 0.035;
      nextMid = 0.08 + Math.sin(idle * 0.53 + 1.6) * 0.025;
      nextTreble = 0.06 + Math.sin(idle * 0.91 + 2.4) * 0.020;
      nextEnergy = 0.08 + Math.sin(idle * 0.43) * 0.025;
      nextBands = [nextBass, nextBass * .82, nextMid * .86, nextMid, nextMid * .78, nextTreble * .86, nextTreble];
    }
    const easeUp = 0.42;
    const easeDown = 0.18;
    const mixVal = (prev, nxt)=> prev + (nxt - prev) * (nxt > prev ? easeUp : easeDown);
    visualizerBass = mixVal(visualizerBass, nextBass);
    visualizerMid = mixVal(visualizerMid, nextMid);
    visualizerTreble = mixVal(visualizerTreble, nextTreble);
    visualizerEnergy = mixVal(visualizerEnergy, nextEnergy);
    visualizerBands = visualizerBands.map((prev, idx)=> mixVal(prev || 0, nextBands[idx] || 0));
    if(cachedFeatures){
      visualizerBeatPulse = visualizerBeatPulse + (cachedFeatures.beat - visualizerBeatPulse) * (cachedFeatures.beat > visualizerBeatPulse ? 0.54 : 0.22);
    }else{
      updateVisualizerTempo(nowTs, nextBands[0] || nextBass, nextEnergy);
    }
    try{ if(state) state.visualizerBpm = Math.round(visualizerBpm); }catch(e){}
    renderVisualizerWebGL(nowTs);
    applySelectedTextContrast();
    refreshLiquidGlassVisualizerSources("visualizer frame");
    renderLiquidGlassVisualizerSourceNow(currentVisualizerFrameState(nowTs));
  }catch(e){}
  try{
    const residualNow = visualizerResidualVisible(performance.now());
    const hasEnergyNow = visualizerEnabled && (visualizerEnergy > 0.003 || visualizerBass > 0.003 || visualizerMid > 0.003 || visualizerTreble > 0.003);
    if(!visualizerActive && !residualNow && !hasEnergyNow && visualizerBg){
      visualizerBg.classList.remove("active");
      visualizerBg.classList.add("off");
    }
    scheduleVisualizerFrame((visualizerEnabled || visualizerActive || residualNow || hasEnergyNow || (visualizerEnabled && residualNow && isPathPillVisible())) ? 0 : 160);
  }catch(e){
    scheduleVisualizerFrame(160);
  }
}

function ensureVisualizerFrameLoop(){
  try{
    scheduleVisualizerFrame(0);
  }catch(e){}
}
var npPillPinned = false;
var npPillVisible = false;
try{
  npPillPinned = (localStorage.getItem("debripod_np_pill_pinned") || "") === "1";
}catch(e){}

function setNpPillPinned(on){
  npPillPinned = !!on;
  try{ localStorage.setItem("debripod_np_pill_pinned", npPillPinned ? "1" : "0"); }catch(e){}
  if(npPillPinned){
    showNpPill(true, "pin");
  }else{
    npPillActivity(false);
  }
}

function setNpOverlayLiquidGlassVisible(visible, reason){
  try{
    const renderer = liquidGlassRendererByKey("npOverlay");
    if(!renderer) return;
    if(visible){
      if(renderer.setVisible) renderer.setVisible(true);
      forceNpOverlayGlassRender(reason || "np pill show", true);
      animateNpOverlayGlassTransition(reason || "np pill show", 260);
    }else{
      animateNpOverlayGlassTransition(reason || "np pill hide", 220);
    }
  }catch(e){}
}

function setNpPillVisible(visible, reason, pinnedValue){
  var nextVisible = !!visible;
  if(typeof pinnedValue === "boolean"){
    npPillPinned = !!pinnedValue;
    try{ localStorage.setItem("debripod_np_pill_pinned", npPillPinned ? "1" : "0"); }catch(e){}
  }
  try{ if(npPillHideTimer) clearTimeout(npPillHideTimer); }catch(e){}
  npPillHideTimer = null;
  if(!nextVisible){
    try{ if(npPillSwapTimer) clearTimeout(npPillSwapTimer); }catch(e){}
    npPillSwapTimer = null;
  }
  npPillVisible = nextVisible;
  try{
    if(!npOverlayPill){
      setNpOverlayLiquidGlassVisible(nextVisible, reason);
      return;
    }
    if(nextVisible){
      try{ if(typeof hideTransientListGlass === "function") hideTransientListGlass(reason || "np pill show"); }catch(e){}
      refreshNpOverlayGlassSource(reason || "np pill show");
      npOverlayPill.classList.remove("npPillHidden");
      npOverlayPill.classList.remove("npPillSwapHidden");
      npOverlayPill.style.pointerEvents = "";
      setNpOverlayLiquidGlassVisible(true, reason || "np pill show");
    }else{
      npOverlayPill.classList.add("npPillHidden");
      npOverlayPill.classList.remove("npPillSwapHidden");
      npOverlayPill.style.pointerEvents = "none";
      setNpOverlayLiquidGlassVisible(false, reason || "np pill hide");
    }
  }catch(e){}
}

function hideNpPillImmediate(reason, pinnedValue){
  setNpPillVisible(false, reason || "immediate hide", pinnedValue);
}

function toggleNpPillFromArt(){
    if(nowPlaying.style.display !== "block") return;
    if(isNpPillShown()){
      hideNpPillImmediate("art toggle", false);
    }else{
      setNpPillPinned(true);
    }
}

if(npArt){
  npArt.addEventListener("click", (ev)=>{ try{ ev.stopPropagation(); }catch(e){} toggleNpPillFromArt(); });
}
if(nowPlaying){
  nowPlaying.addEventListener("click", (ev)=>{
    try{
      const tgt = ev.target;
      if(tgt && tgt.closest && tgt.closest(".npOverlayPill, .npOverlaySurface, .npVideoOverlay, input, button, select, textarea")) return;
      toggleNpPillFromArt();
    }catch(e){}
  });
}


function clampByte(n){
  var v = Math.round(Number(n || 0));
  if(!isFinite(v)) return 0;
  return Math.max(0, Math.min(255, v));
}

function rgbaFrom(rgb, a){
  return "rgba(" + clampByte(rgb.r) + "," + clampByte(rgb.g) + "," + clampByte(rgb.b) + "," + Number(a).toFixed(3).replace(/0+$/,'').replace(/\.$/,'') + ")";
}

function mixRgb(a, b, t){
  var p = Math.max(0, Math.min(1, Number(t || 0)));
  return {
    r: Math.round((a.r || 0) + ((b.r || 0) - (a.r || 0)) * p),
    g: Math.round((a.g || 0) + ((b.g || 0) - (a.g || 0)) * p),
    b: Math.round((a.b || 0) + ((b.b || 0) - (a.b || 0)) * p)
  };
}

function themeFromBase(base){
  var white = {r:255,g:255,b:255};
  var black = {r:0,g:0,b:0};
  var a = mixRgb(base, white, .16);
  var b = mixRgb(base, {r:94,g:92,b:230}, .32);
  var c = mixRgb(base, {r:255,g:69,b:58}, .22);
  return {
    accent: rgbaFrom(a, .88),
    accentStrong: rgbaFrom(mixRgb(base, white, .12), 1),
    accentSoft: rgbaFrom(mixRgb(base, black, .06), .20),
    accentOutline: rgbaFrom(mixRgb(base, white, .10), .46),
    accentBar: rgbaFrom(mixRgb(base, white, .10), .94),
    accentGlow: rgbaFrom(base, .34),
    visualizerA: rgbaFrom(a, .46),
    visualizerB: rgbaFrom(b, .34),
    visualizerC: rgbaFrom(c, .22)
  };
}

function applyThemeVars(theme){
  var t = theme || defaultTheme;
  var root = document.documentElement;
  try{
    root.style.setProperty("--theme-accent", t.accent || defaultTheme.accent);
    root.style.setProperty("--theme-accent-strong", t.accentStrong || defaultTheme.accentStrong);
    root.style.setProperty("--theme-accent-soft", t.accentSoft || defaultTheme.accentSoft);
    root.style.setProperty("--theme-accent-outline", t.accentOutline || defaultTheme.accentOutline);
    root.style.setProperty("--theme-accent-bar", t.accentBar || defaultTheme.accentBar);
    root.style.setProperty("--theme-accent-glow", t.accentGlow || defaultTheme.accentGlow);
    root.style.setProperty("--theme-visualizer-a", t.visualizerA || defaultTheme.visualizerA);
    root.style.setProperty("--theme-visualizer-b", t.visualizerB || defaultTheme.visualizerB);
    root.style.setProperty("--theme-visualizer-c", t.visualizerC || defaultTheme.visualizerC);
  }catch(e){}
}

function visualizerShouldShow(){
  try{
    const media = currentVisualizerMediaElement();
    return !!(visualizerEnabled && media && !media.paused && !media.ended);
  }catch(e){
    return false;
  }
}

var visualizerResidualUntil = 0;
function visualizerResidualVisible(ts){
  try{
    return !!(visualizerEnabled && Number(ts || performance.now()) < visualizerResidualUntil);
  }catch(e){
    return false;
  }
}

function setVisualizerActive(on){
  var wasActive = !!visualizerActive;
  if(on && !ensureVisualizerWebGL()) on = false;
  visualizerActive = !!on;
  if(wasActive && !visualizerActive) visualizerResidualUntil = performance.now() + 2200;
  try{
    if(!visualizerBg) return;
    visualizerBg.classList.toggle("active", !!on);
    visualizerBg.classList.toggle("off", !on);
    renderVisualizerWebGL(performance.now());
    if(on && visualizerFrameTimer){
      clearTimeout(visualizerFrameTimer);
      visualizerFrameTimer = 0;
    }
    scheduleVisualizerFrame(0);
  }catch(e){}
}

function updateVisualizerState(){
  ensureVisualizerFrameLoop();
  setVisualizerActive(visualizerShouldShow());
}

function setVisualizerEnabled(on){
  visualizerEnabled = !!on;
  uiSettings.visualizer = visualizerEnabled;
  saveUiSettings();
  updateVisualizerState();
}

function setVisualizerStrength(value){
  var now = performance.now();
  var next = normalizeVisualizerStrength(value);
  visualizerStrengthTransition = {
    from: currentVisualizerStrengthConfig(now),
    to: visualizerStrengthConfigFor(next),
    start: now,
    duration: 460
  };
  visualizerStrength = next;
  uiSettings.visualizerStrength = visualizerStrength;
  saveUiSettings();
  visualizerCanvasDpr = 0;
  renderVisualizerWebGL(now);
  scheduleVisualizerFrame(0);
}

function cycleVisualizerStrength(){
  var order = ["low", "medium", "high"];
  var idx = order.indexOf(normalizeVisualizerStrength(visualizerStrength));
  setVisualizerStrength(order[(idx + 1) % order.length]);
}

function setVisualizerFpsLock(value){
  visualizerFpsLock = normalizeVisualizerFpsLock(value);
  uiSettings.visualizerFpsLock = visualizerFpsLock;
  saveUiSettings();
  visualizerLastFrameTs = 0;
  scheduleVisualizerFrame(0);
}

function cycleVisualizerFpsLock(){
  var order = [30, 60, 120];
  var idx = order.indexOf(normalizeVisualizerFpsLock(visualizerFpsLock));
  setVisualizerFpsLock(order[(idx + 1) % order.length]);
}

function rgbDistance(a, b){
  var dr = (a.r || 0) - (b.r || 0);
  var dg = (a.g || 0) - (b.g || 0);
  var db = (a.b || 0) - (b.b || 0);
  return Math.sqrt(dr * dr + dg * dg + db * db);
}

function rgbSaturation(rgb){
  var mx = Math.max(rgb.r || 0, rgb.g || 0, rgb.b || 0);
  var mn = Math.min(rgb.r || 0, rgb.g || 0, rgb.b || 0);
  return mx ? (mx - mn) / mx : 0;
}

function rgbLuma(rgb){
  return ((rgb.r || 0) * .299 + (rgb.g || 0) * .587 + (rgb.b || 0) * .114) / 255;
}

function rgbToHex(rgb){
  return "#" + [rgb.r, rgb.g, rgb.b].map(v=>clampByte(v).toString(16).padStart(2, "0")).join("");
}

function srgbChannelToLinear(value){
  var v = Math.max(0, Math.min(1, Number(value || 0) / 255));
  return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
}

function relativeLuminance(rgb){
  return srgbChannelToLinear(rgb.r) * 0.2126 + srgbChannelToLinear(rgb.g) * 0.7152 + srgbChannelToLinear(rgb.b) * 0.0722;
}

function contrastRatio(a, b){
  var la = relativeLuminance(a);
  var lb = relativeLuminance(b);
  var hi = Math.max(la, lb);
  var lo = Math.min(la, lb);
  return (hi + 0.05) / (lo + 0.05);
}

function brightenRgb(rgb, amount){
  var p = Math.max(0, Math.min(1, Number(amount || 0)));
  return {
    r: (rgb.r || 0) + (255 - (rgb.r || 0)) * p,
    g: (rgb.g || 0) + (255 - (rgb.g || 0)) * p,
    b: (rgb.b || 0) + (255 - (rgb.b || 0)) * p
  };
}

function darkenRgb(rgb, amount){
  var p = 1 - Math.max(0, Math.min(1, Number(amount || 0)));
  return {r:(rgb.r || 0) * p, g:(rgb.g || 0) * p, b:(rgb.b || 0) * p};
}

function bestContrastCandidate(bg, palette){
  var candidates = [];
  (palette || []).forEach((c)=>{
    candidates.push(c, brightenRgb(c, .42), brightenRgb(c, .72), darkenRgb(c, .44), darkenRgb(c, .72));
  });
  candidates.push({r:255,g:255,b:255}, {r:0,g:0,b:0});
  var best = candidates[0] || {r:255,g:255,b:255};
  var bestScore = -1;
  candidates.forEach((c)=>{
    var ratio = contrastRatio(bg, c);
    var paletteAffinity = (palette || []).some(p=> rgbDistance(p, c) < 2) ? 0.18 : 0;
    var score = ratio + paletteAffinity;
    if(score > bestScore){
      bestScore = score;
      best = c;
    }
  });
  return {rgb:{r:clampByte(best.r), g:clampByte(best.g), b:clampByte(best.b)}, contrast:bestScore};
}

function buildVisualizerPaletteObject(colors){
  var palette = (Array.isArray(colors) && colors.length ? colors : defaultVisualizerPalette)
    .map(c=>({r:clampByte(c.r), g:clampByte(c.g), b:clampByte(c.b)}));
  var roleNames = ["low", "lowHigh", "lowMid", "mid", "upperMid", "highLow", "high"];
  var roles = {};
  roleNames.forEach((name, idx)=>{
    var bg = palette[idx % palette.length] || defaultVisualizerPalette[idx % defaultVisualizerPalette.length];
    var best = bestContrastCandidate(bg, palette);
    roles[name] = {
      color: rgbToHex(bg),
      contrast: rgbToHex(best.rgb),
      contrastRatio: Number(best.contrast || 0)
    };
  });
  var darkText = bestContrastCandidate({r:18,g:18,b:22}, palette).rgb;
  var lightText = bestContrastCandidate({r:236,g:238,b:242}, palette).rgb;
  var selectedFallback = bestContrastCandidate(palette[0] || defaultVisualizerPalette[0], palette).rgb;
  return {
    version: 1,
    colors: palette.map(rgbToHex),
    roles: roles,
    ui: {
      darkText: rgbToHex(darkText),
      lightText: rgbToHex(lightText),
      clearEngraveA: roles.low.contrast,
      clearEngraveB: roles.high.contrast,
      selectedFallbackText: rgbToHex(selectedFallback),
      selectedFallbackPillText: rgbToHex(selectedFallback),
      selectedPillEdge: roles.mid.contrast,
      wheelText: rgbToHex(selectedFallback)
    }
  };
}

function rgbFromHex(hex, fallback){
  var s = String(hex || "").trim().replace(/^#/, "");
  if(s.length === 3) s = s.split("").map(ch=>ch + ch).join("");
  if(s.length !== 6) return fallback || {r:255,g:255,b:255};
  var n = parseInt(s, 16);
  if(!Number.isFinite(n)) return fallback || {r:255,g:255,b:255};
  return {r:(n >> 16) & 255, g:(n >> 8) & 255, b:n & 255};
}

function colorsFromPaletteObject(paletteObj){
  try{
    const colors = paletteObj && Array.isArray(paletteObj.colors) ? paletteObj.colors : [];
    const out = colors.map(c=>rgbFromHex(c, null)).filter(Boolean);
    return out.length ? out : null;
  }catch(e){
    return null;
  }
}

function roleWeightsForSelectedText(){
  try{
    var bands = visualizerBands && visualizerBands.length ? visualizerBands : [visualizerBass, visualizerBass, visualizerMid, visualizerMid, visualizerMid, visualizerTreble, visualizerTreble];
    var low = clamp01(((bands[0] || 0) + (bands[1] || 0)) * .5 + visualizerBass * .45 + visualizerBeatPulse * .18);
    var mid = clamp01(((bands[2] || 0) + (bands[3] || 0) + (bands[4] || 0)) / 3 + visualizerMid * .42);
    var high = clamp01(((bands[5] || 0) + (bands[6] || 0)) * .5 + visualizerTreble * .48);
    var rowBias = .5;
    const row = libList ? libList.querySelector(".ipodItem.sel") : null;
    if(row){
      const rect = row.getBoundingClientRect();
      rowBias = clamp01((rect.top + rect.height * .5) / Math.max(1, window.innerHeight || 1));
    }
    low *= 0.82 + rowBias * 0.34;
    high *= 1.16 - rowBias * 0.32;
    var total = low + mid + high;
    if(total < 0.001) return {low:0.18, mid:0.42, high:0.40};
    return {low:low / total, mid:mid / total, high:high / total};
  }catch(e){
    return {low:0.18, mid:0.42, high:0.40};
  }
}

function blendRoleContrast(roles, mix){
  var low = rgbFromHex(roles.low && roles.low.contrast);
  var mid = rgbFromHex(roles.mid && roles.mid.contrast);
  var high = rgbFromHex(roles.high && roles.high.contrast);
  return {
    r: low.r * mix.low + mid.r * mix.mid + high.r * mix.high,
    g: low.g * mix.low + mid.g * mix.mid + high.g * mix.high,
    b: low.b * mix.low + mid.b * mix.mid + high.b * mix.high
  };
}

function applySelectedTextContrast(){
  try{
    const list = libList || document.getElementById("libList");
    if(!list) return;
    const paletteObj = currentVisualizerPalette || buildVisualizerPaletteObject(defaultVisualizerPalette);
    const nextMix = roleWeightsForSelectedText();
    selectedTextContrastMix = {
      low: selectedTextContrastMix.low + (nextMix.low - selectedTextContrastMix.low) * 0.16,
      mid: selectedTextContrastMix.mid + (nextMix.mid - selectedTextContrastMix.mid) * 0.16,
      high: selectedTextContrastMix.high + (nextMix.high - selectedTextContrastMix.high) * 0.16
    };
    var next = blendRoleContrast(paletteObj.roles || {}, selectedTextContrastMix);
    selectedContrastRgb = {
      r: selectedContrastRgb.r + (next.r - selectedContrastRgb.r) * 0.22,
      g: selectedContrastRgb.g + (next.g - selectedContrastRgb.g) * 0.22,
      b: selectedContrastRgb.b + (next.b - selectedContrastRgb.b) * 0.22
    };
    selectedPillContrastRgb = {
      r: selectedPillContrastRgb.r + (next.r - selectedPillContrastRgb.r) * 0.20,
      g: selectedPillContrastRgb.g + (next.g - selectedPillContrastRgb.g) * 0.20,
      b: selectedPillContrastRgb.b + (next.b - selectedPillContrastRgb.b) * 0.20
    };
    const rootEl = document.documentElement;
    const contrast = rgbToHex(selectedContrastRgb);
    const pillContrast = rgbToHex(selectedPillContrastRgb);
    const pillEdge = paletteObj.ui && paletteObj.ui.selectedPillEdge ? paletteObj.ui.selectedPillEdge : rgbToHex(selectedPillContrastRgb);
    rootEl.style.setProperty("--lib-selected-contrast", contrast);
    rootEl.style.setProperty("--lib-selected-pill-contrast", pillContrast);
    rootEl.style.setProperty("--lib-selected-pill-edge", pillEdge);
    list.style.setProperty("--lib-selected-contrast", contrast);
    list.style.setProperty("--lib-selected-pill-contrast", pillContrast);
    list.style.setProperty("--lib-selected-pill-edge", pillEdge);
  }catch(e){}
}

function setVisualizerPalette(palette){
  var paletteObj = (palette && typeof palette === "object" && !Array.isArray(palette)) ? palette : null;
  var sourceColors = paletteObj ? colorsFromPaletteObject(paletteObj) : palette;
  var colors = (Array.isArray(sourceColors) && sourceColors.length ? sourceColors : defaultVisualizerPalette)
    .map(c=>({r:clampByte(c.r), g:clampByte(c.g), b:clampByte(c.b)}))
    .slice(0, MAX_VISUALIZER_PALETTE_COLORS);
  visualizerTargetPalette = colors.length ? colors : defaultVisualizerPalette.slice();
  currentVisualizerPalette = paletteObj || buildVisualizerPaletteObject(visualizerTargetPalette);
  var rootTheme = themeFromBase(visualizerTargetPalette[0] || defaultVisualizerPalette[0]);
  if(visualizerTargetPalette.length >= 3){
    rootTheme.visualizerA = rgbaFrom(visualizerTargetPalette[0], .46);
    rootTheme.visualizerB = rgbaFrom(visualizerTargetPalette[1], .34);
    rootTheme.visualizerC = rgbaFrom(visualizerTargetPalette[2], .24);
  }
  applyThemeVars(rootTheme);
  applySelectedTextContrast();
}

function applyVisualizerPresetPalette(){
  if(visualizerTrackKey && visualizerPaletteCache.has(visualizerTrackKey)){
    setVisualizerPalette(visualizerPaletteCache.get(visualizerTrackKey));
  }else{
    setVisualizerPalette(defaultVisualizerPalette);
  }
}

function setVisualizerPreset(value){
  visualizerPresetName = normalizeVisualizerPreset(value);
  uiSettings.visualizerPreset = visualizerPresetName;
  saveUiSettings();
  try{ if(state) state.visualizerPreset = visualizerPresetName; }catch(e){}
  resetVisualizerTempo();
  applyVisualizerPresetPalette();
  renderVisualizerWebGL(performance.now());
  scheduleLiquidGlassSnapshot("visualizer preset", true);
}

function cycleVisualizerPreset(){
  var order = Object.keys(VISUALIZER_PRESETS);
  var idx = order.indexOf(normalizeVisualizerPreset(visualizerPresetName));
  setVisualizerPreset(order[(idx + 1) % order.length] || "album");
}

function cacheVisualizerPalette(key, palette, paletteObj){
  try{
    const colors = paletteObj ? colorsFromPaletteObject(paletteObj) : palette;
    visualizerPaletteCache.set(key, colors || palette || defaultVisualizerPalette);
    if(paletteObj && typeof paletteObj === "object") currentVisualizerPalette = paletteObj;
    if(key && currentVisualizerPalette) saveVisualizerPaletteLocal(key, currentVisualizerPalette);
    while(visualizerPaletteCache.size > 48){
      const first = visualizerPaletteCache.keys().next().value;
      visualizerPaletteCache.delete(first);
    }
  }catch(e){}
}

function openVisualizerPaletteDb(){
  try{
    if(!("indexedDB" in window)) return Promise.resolve(null);
    if(visualizerPaletteDbPromise) return visualizerPaletteDbPromise;
    visualizerPaletteDbPromise = new Promise((resolve)=>{
      const req = indexedDB.open("debripod-visualizer-cache", 1);
      req.onupgradeneeded = ()=>{
        try{
          const db = req.result;
          if(!db.objectStoreNames.contains("palettes")){
            db.createObjectStore("palettes", {keyPath:"key"});
          }
        }catch(e){}
      };
      req.onsuccess = ()=>resolve(req.result || null);
      req.onerror = ()=>resolve(null);
      req.onblocked = ()=>resolve(null);
    });
    return visualizerPaletteDbPromise;
  }catch(e){
    return Promise.resolve(null);
  }
}

function saveVisualizerPaletteLocal(key, paletteObj){
  try{
    if(!key || !paletteObj) return;
    openVisualizerPaletteDb().then((db)=>{
      try{
        if(!db) return;
        const tx = db.transaction("palettes", "readwrite");
        tx.objectStore("palettes").put({key:String(key), savedAt:Date.now(), palette:paletteObj});
      }catch(e){}
    });
  }catch(e){}
}

function loadVisualizerPaletteLocal(key, nonce){
  try{
    if(!key) return false;
    openVisualizerPaletteDb().then((db)=>{
      try{
        if(!db || nonce !== visualizerSampleNonce) return;
        const tx = db.transaction("palettes", "readonly");
        const req = tx.objectStore("palettes").get(String(key));
        req.onsuccess = ()=>{
          try{
            if(nonce !== visualizerSampleNonce) return;
            const paletteObj = req.result && req.result.palette;
            const colors = colorsFromPaletteObject(paletteObj);
            if(!colors || !paletteObj) return;
            cacheVisualizerPalette(key, colors, paletteObj);
            setVisualizerPalette(colors);
            currentVisualizerPalette = paletteObj;
            applySelectedTextContrast();
            updateVisualizerState();
          }catch(e){}
        };
      }catch(e){}
    });
    return true;
  }catch(e){
    return false;
  }
}

function persistVisualizerPalette(key, sourceIdentity){
  try{
    if(!key || !currentVisualizerPalette) return;
    saveVisualizerPaletteLocal(key, currentVisualizerPalette);
  }catch(e){}
}

function loadPersistedVisualizerPalette(key, sourceIdentity, nonce){
  try{
    if(!key || typeof apiGet !== "function") return false;
    apiGet("/api/library/palette?key=" + encodeURIComponent(key))
      .then((res)=>{
        try{
          if(nonce !== visualizerSampleNonce) return;
          const paletteObj = res && res.palette;
          const colors = colorsFromPaletteObject(paletteObj);
          if(!colors || !paletteObj){
            if(!visualizerPaletteCache.has(key)) setVisualizerPalette(defaultVisualizerPalette);
            updateVisualizerState();
            return;
          }
          cacheVisualizerPalette(key, colors, paletteObj);
          setVisualizerPalette(colors);
          currentVisualizerPalette = paletteObj;
          applySelectedTextContrast();
          updateVisualizerState();
        }catch(e){}
      })
      .catch(()=>{
        try{
          if(nonce === visualizerSampleNonce && !visualizerPaletteCache.has(key)){
            setVisualizerPalette(defaultVisualizerPalette);
            updateVisualizerState();
          }
        }catch(e){}
      });
    return true;
  }catch(e){
    return false;
  }
}

function sampleThemeFromArt(src){
  var art = nowPlayingArtSrcValue(src);
  var key = nowPlayingArtCompareKey(art);
  if(key && key !== visualizerTrackKey) resetVisualizerTempo();
  if(!key || !art){
    visualizerTrackKey = "";
    setVisualizerPalette(defaultVisualizerPalette);
    updateVisualizerState();
    return;
  }
  visualizerTrackKey = key;
  if(visualizerPaletteCache.has(key)){
    setVisualizerPalette(visualizerPaletteCache.get(key));
    updateVisualizerState();
    return;
  }
  var myNonce = ++visualizerSampleNonce;
  const loadedLocal = loadVisualizerPaletteLocal(key, myNonce);
  const requested = loadPersistedVisualizerPalette(key, art, myNonce);
  if(!loadedLocal && !requested){
    setVisualizerPalette(defaultVisualizerPalette);
    updateVisualizerState();
  }
}

function nowPlayingArtSrcValue(src){
  return String(src || "").trim();
}

function nowPlayingArtCompareKey(src){
  var v = nowPlayingArtSrcValue(src);
  if(!v) return "";
  try{
    const u = new URL(v, window.location.href);
    return (u.pathname || "") + "|" + (u.searchParams.get("v") || "");
  }catch(e){
    const q = v.split("?");
    let ver = "";
    try{
      const sp = new URLSearchParams(q[1] || "");
      ver = sp.get("v") || "";
    }catch(err){}
    return (q[0] || "") + "|" + ver;
  }
}

applyVisualizerPresetPalette();
