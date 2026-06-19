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
var visualizerCtx = null;
var visualizerCanvasDpr = 0;
var visualizerCanvasW = 0;
var visualizerCanvasH = 0;
var visualizerVideoSampleCanvas = null;
var visualizerVideoSampleCtx = null;
var visualizerVideoSampleLastTs = 0;
var visualizerArtBounds = null;
var visualizerArtBoundsLastTs = 0;

var VISUALIZER_STRENGTHS = {
  low: {dpr: 0.62, interval: 33, bassFields: 1, midFields: 1, trebleFields: 1, speed: 0.58, alpha: 0.42, bright: 0.72, coverage: 0.72},
  medium: {dpr: 0.86, interval: 17, bassFields: 2, midFields: 2, trebleFields: 2, speed: 0.82, alpha: 0.68, bright: 0.92, coverage: 1.0},
  high: {dpr: 1.05, interval: 17, bassFields: 3, midFields: 3, trebleFields: 3, speed: 1.02, alpha: 0.86, bright: 1.06, coverage: 1.22}
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

function rgbForPaletteIndex(i){
  var palette = visualizerPalette && visualizerPalette.length ? visualizerPalette : defaultVisualizerPalette;
  return palette[i % palette.length] || defaultVisualizerPalette[i % defaultVisualizerPalette.length];
}

function rgbaCss(rgb, alpha, bright){
  var b = Number.isFinite(bright) ? bright : 1;
  return "rgba(" + clampByte((rgb.r || 0) * b) + "," + clampByte((rgb.g || 0) * b) + "," + clampByte((rgb.b || 0) * b) + "," + clamp01(alpha).toFixed(3) + ")";
}

function drawRadialField(ctx, w, h, x, y, radius, rgb, alpha, bright, midStop){
  var grad = ctx.createRadialGradient(x, y, 0, x, y, Math.max(1, radius));
  grad.addColorStop(0, rgbaCss(rgb, alpha, bright));
  grad.addColorStop(Math.max(0.12, Math.min(0.82, midStop || 0.42)), rgbaCss(rgb, alpha * 0.32, bright));
  grad.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, w, h);
}

function drawLinearGlow(ctx, w, h, x0, y0, x1, y1, rgb, alpha, bright){
  var grad = ctx.createLinearGradient(x0, y0, x1, y1);
  grad.addColorStop(0, "rgba(0,0,0,0)");
  grad.addColorStop(0.50, rgbaCss(rgb, alpha, bright));
  grad.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, w, h);
}

function visualizerAnchorForCanvas(w, h, ts){
  var minDim = Math.min(w, h);
  var maxDim = Math.max(w, h);
  return {cx: w * 0.5, cy: h * 0.50, rx: maxDim * 0.36, ry: maxDim * 0.36, art: minDim * 0.52};
}

function resizeVisualizerCanvas(cfg){
  try{
    if(!visualizerBg || !visualizerBg.getContext) return false;
    const dpr = Math.max(0.45, Math.min(cfg.dpr, window.devicePixelRatio || 1));
    const w = Math.max(1, Math.round(window.innerWidth * dpr));
    const h = Math.max(1, Math.round(window.innerHeight * dpr));
    if(!visualizerCtx) visualizerCtx = visualizerBg.getContext("2d", {alpha:true});
    if(!visualizerCtx) return false;
    if(w !== visualizerCanvasW || h !== visualizerCanvasH || dpr !== visualizerCanvasDpr){
      visualizerBg.width = w;
      visualizerBg.height = h;
      visualizerCanvasW = w;
      visualizerCanvasH = h;
      visualizerCanvasDpr = dpr;
    }
    return true;
  }catch(e){
    return false;
  }
}

function blendVisualizerPalette(){
  try{
    const target = visualizerTargetPalette && visualizerTargetPalette.length ? visualizerTargetPalette : defaultVisualizerPalette;
    const maxLen = Math.max(4, target.length);
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

function renderVisualizerCanvas(ts){
  try{
    if(!visualizerBg) return;
    const cfg = currentVisualizerStrengthConfig(ts);
    if(!resizeVisualizerCanvas(cfg)) return;
    const ctx = visualizerCtx;
    const w = visualizerCanvasW;
    const h = visualizerCanvasH;
    const preset = currentVisualizerPreset();
    const style = String(preset.style || "orbit");
    const t = visualizerMotionTime(ts) * cfg.speed;
    const drawActive = visualizerActive || visualizerResidualVisible(ts);
    const e = drawActive ? clamp01(visualizerEnergy) : 0;
    const b = drawActive ? clamp01(visualizerBass) : 0;
    const m = drawActive ? clamp01(visualizerMid) : 0;
    const tr = drawActive ? clamp01(visualizerTreble) : 0;
    const beat = drawActive ? clamp01(visualizerBeatPulse) : 0;
    blendVisualizerPalette();
    const anchor = visualizerAnchorForCanvas(w, h, ts);

    ctx.globalCompositeOperation = "source-over";
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "rgb(0,0,0)";
    ctx.fillRect(0, 0, w, h);

    const minDim = Math.min(w, h);
    const maxDim = Math.max(w, h);
    ctx.globalCompositeOperation = "lighter";

    if(style === "ribbon" || style === "prism" || style === "cascade"){
      const bands = style === "prism" ? 6 : (style === "cascade" ? 5 : 4);
      for(let i = 0; i < bands; i++){
        const col = rgbForPaletteIndex(i + 1);
        const swing = Math.sin(t * (style === "cascade" ? 1.25 : 0.72) + i * 1.7);
        if(style === "cascade"){
          const x = ((i + 0.2 + (t * (0.08 + i * 0.012))) % bands) / bands * w;
          const drift = swing * anchor.rx * (0.18 + m * 0.16);
          drawLinearGlow(ctx, w, h, x + drift, -h * 0.1, x - drift * 0.55, h * 1.08, col, cfg.alpha * (0.05 + visualizerBands[i % 7] * 0.13), cfg.bright * (0.76 + i * 0.08));
        }else if(style === "prism"){
          const xA = anchor.cx + Math.cos(i * 1.37 + t * 0.24) * anchor.rx * 1.55;
          const yA = anchor.cy + Math.sin(i * 0.91 - t * 0.18) * anchor.ry * 1.38;
          const xB = anchor.cx - Math.sin(i * 1.11 + t * 0.38) * anchor.rx * 1.62;
          const yB = anchor.cy + Math.cos(i * 1.49 + t * 0.32) * anchor.ry * 1.46;
          drawLinearGlow(ctx, w, h, xA, yA, xB, yB, col, cfg.alpha * (0.055 + tr * 0.12 + beat * 0.06), cfg.bright * 1.24);
        }else{
          const yA = anchor.cy + (i - (bands - 1) / 2) * anchor.ry * 0.42 + swing * anchor.ry * (0.32 + m * 0.18);
          const yB = anchor.cy - (i - (bands - 1) / 2) * anchor.ry * 0.36 - swing * anchor.ry * (0.26 + tr * 0.18);
          drawLinearGlow(ctx, w, h, -w * 0.05, yA, w * 1.05, yB, col, cfg.alpha * (0.05 + m * 0.12 + tr * 0.08), cfg.bright * 1.02);
        }
      }
    }

    if(style === "rings" || style === "nova"){
      const ringCount = style === "nova" ? 4 : 6;
      for(let i = 0; i < ringCount; i++){
        const col = rgbForPaletteIndex(i);
        const phase = (t * (style === "nova" ? 1.18 : 0.72) + i / ringCount) % 1;
        const radius = (anchor.art * (style === "nova" ? 0.16 : 0.22) + minDim * (style === "nova" ? (phase * 0.34) : (0.10 + phase * 0.48))) * cfg.coverage * (1 + beat * (style === "nova" ? 0.32 : 0.14));
        const alpha = cfg.alpha * (style === "nova" ? (0.08 + (1 - phase) * 0.20 + beat * 0.12) : (0.13 + (1 - phase) * 0.10 + (i < 2 ? b * 0.14 : tr * 0.10)));
        drawRadialField(ctx, w, h, anchor.cx, anchor.cy, radius, col, alpha, cfg.bright * (style === "nova" ? (0.80 + i * 0.13) : (0.58 + i * 0.14)), style === "nova" ? 0.26 : 0.72);
      }
    }

    if(style === "lattice"){
      const lines = visualizerStrength === "high" ? 7 : 5;
      for(let i = 0; i < lines; i++){
        const level = clamp01(visualizerBands[i % 7] || (i < 2 ? b : (i < 4 ? m : tr)));
        const col = rgbForPaletteIndex(i);
        const phase = i / Math.max(1, lines - 1);
        const skew = Math.sin(t * 0.42 + i * 0.8) * minDim * 0.10;
        drawLinearGlow(ctx, w, h, w * phase + skew, 0, w * (1 - phase) - skew, h, col, cfg.alpha * (0.035 + level * 0.13), cfg.bright * (0.72 + i * 0.08));
        drawLinearGlow(ctx, w, h, 0, h * phase - skew * 0.55, w, h * (1 - phase) + skew * 0.55, col, cfg.alpha * (0.026 + level * 0.08), cfg.bright * (0.68 + i * 0.06));
      }
    }

    if(style === "bloom"){
      const sparks = visualizerStrength === "high" ? 10 : 6;
      for(let i = 0; i < sparks; i++){
        const level = clamp01(visualizerBands[i % 7] || (i < 3 ? b : (i < 6 ? m : tr)));
        const phase = (t * (0.10 + i * 0.006) + i * 0.173) % 1;
        const side = (i % 2 ? -1 : 1);
        const x = anchor.cx + side * anchor.rx * (0.18 + (i % 4) * 0.16) + Math.sin(t * 0.9 + i) * anchor.rx * 0.08;
        const y = anchor.cy + anchor.ry * 0.52 - phase * anchor.ry * 1.65;
        const radius = (anchor.art * 0.045 + minDim * 0.035) * (1 + level * 1.1 + beat * 0.22);
        drawRadialField(ctx, w, h, x, y, radius, rgbForPaletteIndex(i + 2), cfg.alpha * (0.08 + level * 0.20), cfg.bright * (0.95 + phase * 0.28), 0.24);
      }
      drawRadialField(ctx, w, h, anchor.cx, anchor.cy + anchor.ry * 0.28, anchor.art * 0.58 * (1 + b * 0.22 + beat * 0.16), rgbForPaletteIndex(0), cfg.alpha * (0.12 + b * 0.28), cfg.bright * 0.62, 0.64);
    }

    if(visualizerStrength === "high"){
      const layers = [
        {idx:0, scale:.42, bright:.46, alpha:.18, orbit:.34},
        {idx:1, scale:.52, bright:.58, alpha:.17, orbit:.50},
        {idx:2, scale:.36, bright:.74, alpha:.15, orbit:.72},
        {idx:3, scale:.30, bright:.92, alpha:.13, orbit:.92},
        {idx:4, scale:.24, bright:1.05, alpha:.12, orbit:1.08},
        {idx:5, scale:.18, bright:1.18, alpha:.11, orbit:1.22},
        {idx:6, scale:.13, bright:1.30, alpha:.10, orbit:1.34}
      ];
      for(const layer of layers){
        const level = clamp01(visualizerBands[layer.idx] || 0);
        const angle = t * (0.42 + layer.idx * 0.09) + layer.idx * 0.92;
        const wobble = Math.sin(t * (0.62 + layer.idx * 0.05) + layer.idx) * 0.10;
        const orbit = layer.orbit + level * 0.16 + beat * 0.06;
        const x = anchor.cx + Math.cos(angle + wobble) * anchor.rx * orbit;
        const y = anchor.cy + Math.sin(angle - wobble) * anchor.ry * orbit;
        const radius = (anchor.art * layer.scale + minDim * layer.scale * 0.72) * cfg.coverage * (1 + level * 0.42 + beat * 0.08);
        drawRadialField(ctx, w, h, x, y, radius, rgbForPaletteIndex(layer.idx), cfg.alpha * (layer.alpha + level * 0.22), cfg.bright * layer.bright, 0.38);
      }
    }

    for(let i = 0; i < cfg.bassFields; i++){
      const col = rgbForPaletteIndex(i);
      const spread = cfg.bassFields <= 1 ? 0 : (i / (cfg.bassFields - 1) - 0.5);
      const angleBase = style === "bloom" ? Math.PI * 0.5 : (style === "rings" ? t * 0.28 : (style === "nova" ? t * 0.95 : (style === "cascade" ? Math.PI * 0.08 : Math.PI * 0.5)));
      const angle = angleBase + spread * Math.PI * (style === "prism" ? 1.35 : 0.72) + Math.sin(t * 0.72 + i) * 0.10;
      const orbitScale = style === "bloom" ? 0.16 : (style === "rings" ? 0.36 : (style === "nova" ? 0.08 + beat * 0.12 : (style === "cascade" ? 0.58 : (style === "lattice" ? 0.72 : 0.88))));
      const x = anchor.cx + Math.cos(angle) * anchor.rx * (orbitScale + b * 0.10);
      const yOffset = style === "cascade" ? ((t * 0.11 + i * 0.28) % 1 - 0.5) * h * 0.72 : Math.sin(angle) * anchor.ry * (orbitScale + 0.10 + b * 0.12);
      const y = style === "cascade" ? anchor.cy + yOffset : anchor.cy + yOffset;
      const radius = (anchor.art * (style === "nova" ? 0.32 : 0.42) + minDim * (0.26 + i * 0.055)) * cfg.coverage * (1 + b * 0.30 + e * 0.12 + beat * (style === "nova" ? 0.38 : 0.16));
      drawRadialField(ctx, w, h, x, y, radius, col, cfg.alpha * (0.18 + b * 0.34 + e * 0.12), cfg.bright * 0.62, 0.52);
    }

    for(let i = 0; i < cfg.midFields; i++){
      const col = rgbForPaletteIndex(i + cfg.bassFields);
      const angle = (i / Math.max(1, cfg.midFields)) * Math.PI * 2 + t * (style === "prism" ? 1.18 : (style === "lattice" ? 0.18 : (style === "cascade" ? 0.68 : 0.46))) + Math.sin(t * 0.58 + i) * 0.12;
      const spread = style === "bloom" ? 0.48 : (style === "rings" ? 0.78 : (style === "nova" ? 0.34 + beat * 0.20 : (style === "lattice" ? 1.18 : 1.02)));
      const x = anchor.cx + Math.cos(angle) * anchor.rx * (spread + m * 0.12);
      const y = anchor.cy + Math.sin(angle) * anchor.ry * (spread + m * 0.10);
      const radius = (anchor.art * 0.24 + minDim * (0.15 + i * 0.035)) * cfg.coverage * (1 + m * 0.26 + e * 0.08 + beat * 0.08);
      drawRadialField(ctx, w, h, x, y, radius, col, cfg.alpha * (0.16 + m * 0.30 + e * 0.08), cfg.bright * 0.90, 0.42);
    }

    for(let i = 0; i < cfg.trebleFields; i++){
      const col = rgbForPaletteIndex(i + cfg.bassFields + cfg.midFields);
      const angle = (i / Math.max(1, cfg.trebleFields)) * Math.PI * 2 + Math.PI / Math.max(2, cfg.trebleFields) + t * (style === "ribbon" ? 1.12 : (style === "prism" ? -1.26 : (style === "nova" ? 1.72 : 0.88)));
      const spread = style === "bloom" ? 1.05 : (style === "rings" ? 1.36 : (style === "cascade" ? 1.48 : (style === "lattice" ? 1.05 : 1.16)));
      const x = anchor.cx + Math.cos(angle) * anchor.rx * (spread + tr * 0.14);
      const y = anchor.cy + Math.sin(angle) * anchor.ry * (spread * 0.95 + tr * 0.12);
      const radius = (anchor.art * 0.13 + minDim * (0.075 + i * 0.018)) * cfg.coverage * (1 + tr * 0.38 + e * 0.06 + beat * 0.10);
      drawRadialField(ctx, w, h, x, y, radius, col, cfg.alpha * (0.08 + tr * 0.30 + e * 0.08), cfg.bright * 1.16, 0.34);
    }

    if(visualizerStrength !== "low"){
      drawLinearGlow(ctx, w, h, anchor.cx - anchor.rx * 1.8, anchor.cy - anchor.ry * (0.95 + tr * 0.2), anchor.cx + anchor.rx * 1.8, anchor.cy + anchor.ry * (0.95 - m * 0.14), rgbForPaletteIndex(1), cfg.alpha * (0.035 + m * 0.08), cfg.bright);
    }
    if(visualizerStrength === "high"){
      drawLinearGlow(ctx, w, h, anchor.cx - anchor.rx * 1.2, anchor.cy - anchor.ry * 1.65, anchor.cx + anchor.rx * 1.2, anchor.cy + anchor.ry * 1.65, rgbForPaletteIndex(3), cfg.alpha * (0.04 + tr * 0.10), cfg.bright * 1.08);
    }

    ctx.globalCompositeOperation = "source-over";
    const vignette = ctx.createRadialGradient(w * .5, h * .5, minDim * .08, w * .5, h * .5, maxDim * .68);
    vignette.addColorStop(0, "rgba(0,0,0,0)");
    vignette.addColorStop(0.62, "rgba(0,0,0,.20)");
    vignette.addColorStop(1, "rgba(0,0,0,.86)");
    ctx.fillStyle = vignette;
    ctx.fillRect(0, 0, w, h);
  }catch(e){}
}

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
    selectedTextContrastMix: selectedTextContrastMix
  };
}

function scheduleVisualizerFrame(delayMs){
  try{
    if(visualizerFrameHandle || visualizerFrameTimer) return;
    const delay = Math.max(0, Number(delayMs || 0));
    if(delay > 34){
      visualizerFrameTimer = setTimeout(()=>{
        visualizerFrameTimer = 0;
        visualizerFrameHandle = requestAnimationFrame(visualizerFrame);
      }, delay);
      return;
    }
    visualizerFrameHandle = requestAnimationFrame(visualizerFrame);
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
    const interval = glassNeedsFrame ? cfg.interval : 180;
    if(visualizerLastFrameTs && (nowTs - visualizerLastFrameTs) < interval){
      scheduleVisualizerFrame(interval - (nowTs - visualizerLastFrameTs));
      return;
    }
    visualizerLastFrameTs = nowTs;
    const el = currentVisualizerMediaElement();
    const canAnalyze = !!(visualizerEnabled && visualizerActive && !document.hidden && el && ensureVisualizerAudioGraphFor(el) && visualizerAnalyser && visualizerData);
    let nextBass = 0;
    let nextMid = 0;
    let nextTreble = 0;
    let nextEnergy = 0;
    let nextBands = [0, 0, 0, 0, 0, 0, 0];
    if(canAnalyze){
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
    updateVisualizerTempo(nowTs, nextBands[0] || nextBass, nextEnergy);
    try{ if(state) state.visualizerBpm = Math.round(visualizerBpm); }catch(e){}
    sampleLiveVideoPalette(nowTs);
    renderVisualizerCanvas(nowTs);
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
  visualizerActive = !!on;
  if(wasActive && !visualizerActive) visualizerResidualUntil = performance.now() + 2200;
  try{
    if(!visualizerBg) return;
    visualizerBg.classList.toggle("active", !!on);
    visualizerBg.classList.toggle("off", !on);
    renderVisualizerCanvas(performance.now());
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
  renderVisualizerCanvas(now);
  scheduleVisualizerFrame(0);
}

function cycleVisualizerStrength(){
  var order = ["low", "medium", "high"];
  var idx = order.indexOf(normalizeVisualizerStrength(visualizerStrength));
  setVisualizerStrength(order[(idx + 1) % order.length]);
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
    list.style.setProperty("--lib-selected-contrast", rgbToHex(selectedContrastRgb));
    list.style.setProperty("--lib-selected-pill-contrast", rgbToHex(selectedPillContrastRgb));
    list.style.setProperty("--lib-selected-pill-edge", paletteObj.ui && paletteObj.ui.selectedPillEdge ? paletteObj.ui.selectedPillEdge : rgbToHex(selectedPillContrastRgb));
  }catch(e){}
}

function setVisualizerPalette(palette){
  var colors = (Array.isArray(palette) && palette.length ? palette : defaultVisualizerPalette)
    .map(c=>({r:clampByte(c.r), g:clampByte(c.g), b:clampByte(c.b)}))
    .slice(0, 8);
  visualizerTargetPalette = colors.length ? colors : defaultVisualizerPalette.slice();
  currentVisualizerPalette = buildVisualizerPaletteObject(visualizerTargetPalette);
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
  renderVisualizerCanvas(performance.now());
  scheduleLiquidGlassSnapshot("visualizer preset", true);
}

function cycleVisualizerPreset(){
  var order = Object.keys(VISUALIZER_PRESETS);
  var idx = order.indexOf(normalizeVisualizerPreset(visualizerPresetName));
  setVisualizerPreset(order[(idx + 1) % order.length] || "album");
}

function cacheVisualizerPalette(key, palette, paletteObj){
  try{
    visualizerPaletteCache.set(key, palette);
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
    if(!key || !currentVisualizerPalette || typeof apiPost !== "function") return;
    saveVisualizerPaletteLocal(key, currentVisualizerPalette);
    apiPost("/api/library/palette", {
      key: key,
      source_kind: "art",
      source_identity: String(sourceIdentity || key),
      palette: currentVisualizerPalette
    }).catch(()=>{});
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
          if(!colors || !paletteObj) return;
          cacheVisualizerPalette(key, colors, paletteObj);
          setVisualizerPalette(colors);
          currentVisualizerPalette = paletteObj;
          applySelectedTextContrast();
          updateVisualizerState();
        }catch(e){}
      })
      .catch(()=>{});
    return true;
  }catch(e){
    return false;
  }
}

function distinctPaletteFromImageData(data){
  var buckets = new Map();
  for(let i = 0; i < data.length; i += 4){
    const a = Number(data[i + 3] || 0);
    if(a < 24) continue;
    const rr = Number(data[i] || 0);
    const gg = Number(data[i + 1] || 0);
    const bb = Number(data[i + 2] || 0);
    const rgb = {r:rr, g:gg, b:bb};
    const sat = rgbSaturation(rgb);
    const lum = rgbLuma(rgb);
    const colorful = sat >= .18 && lum >= .08 && lum <= .92;
    const key2 = (rr >> 3) + "," + (gg >> 3) + "," + (bb >> 3);
    const prev = buckets.get(key2);
    const score = (colorful ? 2.2 : .25) * (sat + .15) * (1 - Math.abs(lum - .50) * .78);
    if(!prev || score > prev.score){
      buckets.set(key2, {rgb:rgb, score:score, colorful:colorful});
    }
  }
  var candidates = Array.from(buckets.values())
    .sort((a,b)=> b.score - a.score)
    .map(x=>x.rgb);
  var selected = [];
  var saturated = candidates.filter(c=> rgbSaturation(c) >= .18 && rgbLuma(c) >= .08 && rgbLuma(c) <= .92);
  var pool = saturated.length ? saturated : candidates;
  var minDist = saturated.length ? 58 : 34;
  for(const color of pool){
    if(selected.every(prev=> rgbDistance(prev, color) >= minDist)){
      selected.push(color);
      if(selected.length >= 8) break;
    }
  }
  while(selected.length < Math.min(4, pool.length)){
    const next = pool.find(c=> selected.indexOf(c) < 0);
    if(!next) break;
    selected.push(next);
  }
  return selected;
}

function sampleLiveVideoPalette(ts){
  try{
    if(!visualizerEnabled || !visualizerActive || document.hidden) return;
    if(!isVideoActive || !isVideoActive() || !npVideo || npVideo.paused || npVideo.readyState < 2) return;
    const interval = visualizerStrength === "high" ? 1400 : (visualizerStrength === "low" ? 3200 : 2200);
    const nowTs = Number(ts || performance.now() || 0);
    if(visualizerVideoSampleLastTs && nowTs - visualizerVideoSampleLastTs < interval) return;
    visualizerVideoSampleLastTs = nowTs;

    if(!visualizerVideoSampleCanvas){
      visualizerVideoSampleCanvas = document.createElement("canvas");
      visualizerVideoSampleCtx = visualizerVideoSampleCanvas.getContext("2d", {willReadFrequently:true});
    }
    if(!visualizerVideoSampleCtx) return;
    const vw = Number(npVideo.videoWidth || 0);
    const vh = Number(npVideo.videoHeight || 0);
    if(!(vw > 0) || !(vh > 0)) return;
    const sampleW = visualizerStrength === "high" ? 42 : (visualizerStrength === "low" ? 24 : 32);
    const sampleH = Math.max(12, Math.round(sampleW * Math.min(1.4, vh / vw)));
    if(visualizerVideoSampleCanvas.width !== sampleW || visualizerVideoSampleCanvas.height !== sampleH){
      visualizerVideoSampleCanvas.width = sampleW;
      visualizerVideoSampleCanvas.height = sampleH;
    }
    visualizerVideoSampleCtx.clearRect(0, 0, sampleW, sampleH);
    visualizerVideoSampleCtx.drawImage(npVideo, 0, 0, sampleW, sampleH);
    const data = visualizerVideoSampleCtx.getImageData(0, 0, sampleW, sampleH).data;
    const palette = distinctPaletteFromImageData(data);
    if(palette && palette.length){
      setVisualizerPalette(palette);
      persistVisualizerPalette("video:" + nowPlayingArtCompareKey(String(npVideo.currentSrc || npVideo.src || "")), String(npVideo.currentSrc || npVideo.src || ""));
    }
  }catch(e){}
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
  loadVisualizerPaletteLocal(key, myNonce);
  loadPersistedVisualizerPalette(key, art, myNonce);
  var img = new Image();
  img.decoding = "async";
  try{
    const u = new URL(art, window.location.href);
    if(u.origin === window.location.origin) img.crossOrigin = "anonymous";
  }catch(e){}
  img.onload = ()=>{
    if(myNonce !== visualizerSampleNonce) return;
    try{
      const w = Math.max(12, Math.min(56, img.naturalWidth || 32));
      const h = Math.max(12, Math.min(56, img.naturalHeight || 32));
      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d", {willReadFrequently:true});
      if(!ctx) throw new Error("no canvas context");
      ctx.drawImage(img, 0, 0, w, h);
      const data = ctx.getImageData(0, 0, w, h).data;
      const selected = distinctPaletteFromImageData(data);
      if(!selected.length) throw new Error("empty sample");
      cacheVisualizerPalette(key, selected);
      setVisualizerPalette(selected);
      persistVisualizerPalette(key, art);
    }catch(err){
      setVisualizerPalette(defaultVisualizerPalette);
    }
    updateVisualizerState();
  };
  img.onerror = ()=>{
    if(myNonce !== visualizerSampleNonce) return;
    setVisualizerPalette(defaultVisualizerPalette);
    updateVisualizerState();
  };
  img.src = art;
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
